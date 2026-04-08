"""
dataLayer Crawler — fashiondays.ro
Intercepts every dataLayer.push() call across key pages.
Audits GA4/GTM ecommerce tracking coverage and extracts product data.

Usage:
    python datalayer_crawler.py --url https://www.fashiondays.ro
    python datalayer_crawler.py --url https://www.fashiondays.ro --headless false
"""

import asyncio
import json
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse
from collections import defaultdict

from playwright.async_api import async_playwright, Page, BrowserContext


# ── GA4 expected ecommerce events ────────────────────────────────────────────
GA4_ECOMMERCE_EVENTS = {
    "view_item_list":    "Product list/category page viewed",
    "select_item":       "Product clicked in listing",
    "view_item":         "Product detail page viewed",
    "add_to_cart":       "Item added to cart",
    "remove_from_cart":  "Item removed from cart",
    "view_cart":         "Cart viewed",
    "begin_checkout":    "Checkout initiated",
    "add_payment_info":  "Payment info entered",
    "add_shipping_info": "Shipping info entered",
    "purchase":          "Purchase completed",
    "view_promotion":    "Promotion viewed",
    "select_promotion":  "Promotion clicked",
}

GA4_REQUIRED_ITEM_FIELDS = [
    "item_id", "item_name", "item_brand", "item_category",
    "item_variant", "price", "quantity",
]


# ── Page type classifier ──────────────────────────────────────────────────────
def classify_page(url: str) -> str:
    path = urlparse(url).path.lower()
    if path in ("/", ""):
        return "homepage"
    if any(x in path for x in ["/cart", "/cos", "/basket"]):
        return "cart"
    if any(x in path for x in ["/checkout", "/comanda", "/order"]):
        return "checkout"
    if re.search(r"/p/|/product|/produs|/\d{5,}|\.html", path):
        return "product"
    if any(x in path for x in ["/search", "/cautare", "?q=", "?s="]):
        return "search"
    return "category"


# ── dataLayer injection ───────────────────────────────────────────────────────
INJECT_SCRIPT = """
() => {
    window.__dlCapture = [];
    window.__dlOriginal = window.dataLayer || [];

    // Capture existing entries
    window.__dlOriginal.forEach(e => window.__dlCapture.push({...e, __ts: Date.now(), __type: 'existing'}));

    // Proxy the array
    const handler = {
        get(target, prop) {
            if (prop === 'push') {
                return function(...args) {
                    args.forEach(a => {
                        window.__dlCapture.push({
                            ...JSON.parse(JSON.stringify(a)),
                            __ts: Date.now(),
                            __type: 'push'
                        });
                    });
                    return Array.prototype.push.apply(target, args);
                };
            }
            return target[prop];
        }
    };

    try {
        window.dataLayer = new Proxy(window.__dlOriginal, handler);
    } catch(e) {
        // Fallback: patch push directly
        const origPush = window.dataLayer.push.bind(window.dataLayer);
        window.dataLayer.push = function(...args) {
            args.forEach(a => {
                try { window.__dlCapture.push({...JSON.parse(JSON.stringify(a)), __ts: Date.now(), __type: 'push'}); } catch(e2){}
            });
            return origPush(...args);
        };
    }
}
"""

GET_CAPTURE_SCRIPT = "() => window.__dlCapture || []"
GET_GTM_SCRIPT = """
() => {
    const scripts = Array.from(document.querySelectorAll('script')).map(s => s.src + s.textContent);
    const gtmIds = [];
    scripts.forEach(s => {
        const m = s.match(/GTM-[A-Z0-9]+/g);
        if (m) m.forEach(id => gtmIds.push(id));
    });
    const gaIds = [];
    scripts.forEach(s => {
        const m = s.match(/G-[A-Z0-9]+/g) || s.match(/UA-\d+-\d+/g);
        if (m) m.forEach(id => gaIds.push(id));
    });
    return { gtm: [...new Set(gtmIds)], ga: [...new Set(gaIds)] };
}
"""


# ── Crawler ───────────────────────────────────────────────────────────────────

class DataLayerCrawler:
    def __init__(self, base_url: str, headless: bool = True, max_products: int = 5):
        self.base_url = base_url.rstrip("/")
        self.domain = urlparse(base_url).netloc
        self.headless = headless
        self.max_products = max_products
        self.results: list[dict] = []
        self.errors: list[dict] = []

    async def _setup_page(self, context: BrowserContext) -> Page:
        page = await context.new_page()
        await page.add_init_script(INJECT_SCRIPT)
        page.on("console", lambda msg: None)  # suppress console noise
        return page

    async def _visit(self, page: Page, url: str, label: str, wait_for: str = "networkidle") -> dict:
        print(f"  → [{label}] {url}")
        events = []
        tag_info = {}
        error = None

        try:
            await page.goto(url, wait_until=wait_for, timeout=30000)
            await page.wait_for_timeout(2000)  # let deferred pushes fire

            # Scroll to trigger lazy-loaded events
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await page.wait_for_timeout(1000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)

            events = await page.evaluate(GET_CAPTURE_SCRIPT)
            tag_info = await page.evaluate(GET_GTM_SCRIPT)

        except Exception as e:
            error = str(e)
            print(f"    !! Error: {error}")
            self.errors.append({"url": url, "label": label, "error": error})

        page_type = classify_page(url)
        return {
            "url": url,
            "label": label,
            "page_type": page_type,
            "events": events,
            "tag_info": tag_info,
            "error": error,
            "event_count": len(events),
        }

    async def _find_links(self, page: Page, selector: str, base: str, limit: int) -> list[str]:
        try:
            hrefs = await page.evaluate(f"""
                () => Array.from(document.querySelectorAll('{selector}'))
                    .map(a => a.href)
                    .filter(h => h && h.startsWith('{base}'))
                    .slice(0, {limit * 3})
            """)
            seen = set()
            unique = []
            for h in hrefs:
                clean = h.split("?")[0].rstrip("/")
                if clean not in seen:
                    seen.add(clean)
                    unique.append(h)
            return unique[:limit]
        except Exception:
            return []

    async def crawl(self) -> list[dict]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="ro-RO",
                extra_http_headers={"Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8"},
            )

            page = await self._setup_page(context)

            # 1. Homepage
            print("\n[1/5] Crawling homepage...")
            home = await self._visit(page, self.base_url, "Homepage")
            self.results.append(home)

            # 2. Discover & visit category pages
            print("\n[2/5] Finding category pages...")
            cat_links = await self._find_links(
                page,
                "nav a, .menu a, header a, [class*='category'] a, [class*='nav'] a",
                self.base_url,
                limit=4
            )
            # Also grab from homepage links
            more_links = await self._find_links(page, "a[href]", self.base_url, limit=30)
            cat_candidates = [l for l in more_links if classify_page(l) == "category"][:3]
            cat_links = list(dict.fromkeys(cat_links + cat_candidates))[:4]

            for i, url in enumerate(cat_links, 1):
                await page.add_init_script(INJECT_SCRIPT)
                result = await self._visit(page, url, f"Category {i}")
                self.results.append(result)

            # 3. Discover & visit product pages
            print("\n[3/5] Finding product pages...")
            prod_links = await self._find_links(
                page,
                "a[href*='/p/'], a[href*='/product'], a[href*='.html'], [class*='product'] a, [class*='item'] a",
                self.base_url,
                limit=self.max_products * 2
            )
            # Filter to likely product URLs
            prod_links = [l for l in prod_links if classify_page(l) == "product"][:self.max_products]

            for i, url in enumerate(prod_links, 1):
                await page.add_init_script(INJECT_SCRIPT)
                result = await self._visit(page, url, f"Product {i}")
                self.results.append(result)

            # 4. Cart page
            print("\n[4/5] Visiting cart...")
            for cart_path in ["/cart", "/cos", "/basket", "/shopping-cart", "/my/cart"]:
                cart_url = self.base_url + cart_path
                await page.add_init_script(INJECT_SCRIPT)
                result = await self._visit(page, cart_url, "Cart", wait_for="domcontentloaded")
                if not result["error"]:
                    self.results.append(result)
                    break

            # 5. Try add-to-cart on first product (if found)
            if prod_links:
                print("\n[5/5] Simulating add-to-cart on first product...")
                await page.add_init_script(INJECT_SCRIPT)
                await page.goto(prod_links[0], wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(1500)

                # Try common add-to-cart selectors
                atc_selectors = [
                    "button[class*='add-to-cart']",
                    "button[class*='addToCart']",
                    "button[class*='add_to_cart']",
                    "[data-action='add-to-cart']",
                    "button:has-text('Adaugă în coș')",
                    "button:has-text('Add to cart')",
                    "button:has-text('Adauga in cos')",
                    ".add-to-cart", "#add-to-cart",
                ]
                clicked = False
                for sel in atc_selectors:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=2000):
                            await btn.click(timeout=3000)
                            await page.wait_for_timeout(2000)
                            clicked = True
                            print(f"    ✓ Clicked add-to-cart: {sel}")
                            break
                    except Exception:
                        continue

                events_after_atc = await page.evaluate(GET_CAPTURE_SCRIPT)
                self.results.append({
                    "url": prod_links[0],
                    "label": "Add-to-cart interaction",
                    "page_type": "product",
                    "events": events_after_atc,
                    "tag_info": {},
                    "error": None if clicked else "Could not find add-to-cart button",
                    "event_count": len(events_after_atc),
                    "atc_clicked": clicked,
                })

            await browser.close()
        return self.results


# ── Analysis engine ───────────────────────────────────────────────────────────

def analyze_results(results: list[dict]) -> dict:
    all_events = []
    for page_result in results:
        for ev in page_result.get("events", []):
            ev["__page_url"] = page_result["url"]
            ev["__page_label"] = page_result["label"]
            ev["__page_type"] = page_result["page_type"]
            all_events.append(ev)

    # Event frequency
    event_names = defaultdict(int)
    for ev in all_events:
        name = ev.get("event") or ev.get("eventName") or ev.get("event_name") or "__unknown__"
        event_names[name] += 1

    # GA4 ecommerce events found
    ga4_found = {k: v for k, v in event_names.items() if k in GA4_ECOMMERCE_EVENTS}
    ga4_missing = {k: v for k, v in GA4_ECOMMERCE_EVENTS.items() if k not in event_names}

    # Collect all GA4 items found
    products_found = []
    for ev in all_events:
        items = ev.get("ecommerce", {}).get("items", []) if ev.get("ecommerce") else []
        if not items:
            items = ev.get("items", [])
        for item in items:
            products_found.append({
                "event": ev.get("event"),
                "page": ev.get("__page_label"),
                "item_id": item.get("item_id", ""),
                "item_name": item.get("item_name", ""),
                "item_brand": item.get("item_brand", ""),
                "item_category": item.get("item_category", ""),
                "price": item.get("price", ""),
                "currency": ev.get("ecommerce", {}).get("currency", "") if ev.get("ecommerce") else "",
            })

    # Field completeness audit on GA4 items
    item_field_audit = {}
    if products_found:
        for field in GA4_REQUIRED_ITEM_FIELDS:
            filled = sum(1 for p in products_found if p.get(field))
            item_field_audit[field] = {
                "filled": filled,
                "total": len(products_found),
                "pct": round(filled / len(products_found) * 100, 1),
            }

    # GTM/GA IDs found
    all_gtm = set()
    all_ga = set()
    for r in results:
        for gid in r.get("tag_info", {}).get("gtm", []):
            all_gtm.add(gid)
        for gid in r.get("tag_info", {}).get("ga", []):
            all_ga.add(gid)

    # Per-page summary
    page_summary = []
    for r in results:
        page_events = r.get("events", [])
        ev_names = [e.get("event") or e.get("eventName") or "?" for e in page_events]
        ev_counter = defaultdict(int)
        for n in ev_names:
            ev_counter[n] += 1
        has_ecommerce = any(e.get("ecommerce") or e.get("items") for e in page_events)
        page_summary.append({
            "label": r["label"],
            "url": r["url"],
            "page_type": r["page_type"],
            "total_events": len(page_events),
            "unique_events": len(ev_counter),
            "event_names": dict(ev_counter),
            "has_ecommerce": has_ecommerce,
            "error": r.get("error"),
        })

    # Tracking issues
    issues = []
    for ps in page_summary:
        if ps["error"]:
            issues.append({"severity": "ERROR", "page": ps["label"], "issue": f"Page failed to load: {ps['error']}"})
            continue
        ptype = ps["page_type"]
        ev_names_set = set(ps["event_names"].keys())

        if ptype == "homepage" and "page_view" not in ev_names_set:
            issues.append({"severity": "HIGH", "page": ps["label"], "issue": "No page_view event on homepage"})

        if ptype == "product":
            if "view_item" not in ev_names_set:
                issues.append({"severity": "HIGH", "page": ps["label"], "issue": "Missing view_item on product page"})
            if not ps["has_ecommerce"]:
                issues.append({"severity": "HIGH", "page": ps["label"], "issue": "No ecommerce object on product page"})

        if ptype == "category" and "view_item_list" not in ev_names_set:
            issues.append({"severity": "MEDIUM", "page": ps["label"], "issue": "Missing view_item_list on category page"})

        if ptype == "cart" and "view_cart" not in ev_names_set:
            issues.append({"severity": "MEDIUM", "page": ps["label"], "issue": "Missing view_cart on cart page"})

    # Check add_to_cart fired during interaction
    atc_result = next((r for r in results if r.get("atc_clicked")), None)
    if atc_result:
        atc_events = {e.get("event") for e in atc_result.get("events", [])}
        if "add_to_cart" not in atc_events:
            issues.append({"severity": "HIGH", "page": "Add-to-cart interaction", "issue": "add_to_cart event did NOT fire after clicking add-to-cart button"})
        else:
            pass  # good

    # Item field issues
    for field, audit in item_field_audit.items():
        if audit["pct"] < 80:
            issues.append({"severity": "MEDIUM", "page": "Items data", "issue": f"Field '{field}' is only {audit['pct']}% populated across product items"})

    return {
        "all_events": all_events,
        "event_frequency": dict(sorted(event_names.items(), key=lambda x: x[1], reverse=True)),
        "ga4_events_found": ga4_found,
        "ga4_events_missing": ga4_missing,
        "products_found": products_found[:100],
        "item_field_audit": item_field_audit,
        "gtm_ids": list(all_gtm),
        "ga_ids": list(all_ga),
        "page_summary": page_summary,
        "issues": issues,
        "total_events_captured": len(all_events),
        "total_pages_crawled": len(results),
    }


# ── HTML Report ───────────────────────────────────────────────────────────────

def generate_report(analysis: dict, base_url: str, output_dir: str = "reports") -> str:
    Path(output_dir).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"{output_dir}/datalayer_audit_{ts}.html"

    issues = analysis["issues"]
    high = [i for i in issues if i["severity"] == "HIGH"]
    medium = [i for i in issues if i["severity"] == "MEDIUM"]
    errors = [i for i in issues if i["severity"] == "ERROR"]

    gtm_ids = ", ".join(analysis["gtm_ids"]) or "None detected"
    ga_ids = ", ".join(analysis["ga_ids"]) or "None detected"

    # Build event frequency table
    ef_rows = ""
    for ev, count in list(analysis["event_frequency"].items())[:30]:
        is_ga4 = ev in GA4_ECOMMERCE_EVENTS
        badge = '<span style="background:#d1fae5;color:#065f46;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600">GA4 ✓</span>' if is_ga4 else ""
        ef_rows += f"<tr><td><code>{ev}</code> {badge}</td><td>{count}</td></tr>"

    # GA4 coverage table
    ga4_rows = ""
    for ev, desc in GA4_ECOMMERCE_EVENTS.items():
        found = ev in analysis["ga4_events_found"]
        count = analysis["ga4_events_found"].get(ev, 0)
        status = f'<span style="color:#10b981;font-weight:700">✓ Found ({count}x)</span>' if found else '<span style="color:#ef4444;font-weight:700">✗ Missing</span>'
        ga4_rows += f"<tr><td><code>{ev}</code></td><td>{desc}</td><td>{status}</td></tr>"

    # Field audit table
    field_rows = ""
    for field, data in analysis["item_field_audit"].items():
        pct = data["pct"]
        bar_color = "#10b981" if pct >= 90 else "#f59e0b" if pct >= 60 else "#ef4444"
        field_rows += f"""<tr>
            <td><code>{field}</code></td>
            <td>{data['filled']}/{data['total']}</td>
            <td>
                <div style="background:#f1f5f9;border-radius:4px;height:16px;width:100%;min-width:120px">
                    <div style="background:{bar_color};height:16px;border-radius:4px;width:{pct}%"></div>
                </div>
            </td>
            <td style="color:{bar_color};font-weight:700">{pct}%</td>
        </tr>"""

    # Issues list
    issues_html = ""
    for sev, color, bg in [("ERROR","#ef4444","#fef2f2"), ("HIGH","#dc2626","#fff1f2"), ("MEDIUM","#f59e0b","#fffbeb")]:
        these = [i for i in issues if i["severity"] == sev]
        for i in these:
            issues_html += f"""
            <div style="border-left:4px solid {color};background:{bg};padding:0.75rem 1rem;border-radius:0 8px 8px 0;margin-bottom:0.75rem">
                <span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700;margin-right:0.5rem">{sev}</span>
                <strong>{i['page']}</strong> — {i['issue']}
            </div>"""

    # Page summary table
    page_rows = ""
    for ps in analysis["page_summary"]:
        ecom_badge = '<span style="background:#d1fae5;color:#065f46;padding:2px 6px;border-radius:4px;font-size:0.75rem">ecommerce ✓</span>' if ps["has_ecommerce"] else '<span style="background:#fee2e2;color:#991b1b;padding:2px 6px;border-radius:4px;font-size:0.75rem">no ecommerce</span>'
        ev_list = ", ".join([f"<code>{k}</code>({v})" for k, v in list(ps["event_names"].items())[:6]])
        err = f'<span style="color:#ef4444">⚠ {ps["error"]}</span>' if ps["error"] else ""
        page_rows += f"""<tr>
            <td><strong>{ps["label"]}</strong><br><small style="color:#94a3b8">{ps["page_type"]}</small></td>
            <td style="font-size:0.8rem;max-width:280px;word-break:break-all"><a href="{ps["url"]}" style="color:#3b82f6">{ps["url"][:80]}{"..." if len(ps["url"])>80 else ""}</a></td>
            <td>{ps["total_events"]}</td>
            <td>{ecom_badge}</td>
            <td style="font-size:0.8rem">{ev_list} {err}</td>
        </tr>"""

    # Products sample table
    prod_rows = ""
    for p in analysis["products_found"][:20]:
        prod_rows += f"""<tr>
            <td><code style="font-size:0.8rem">{p.get("event","")}</code></td>
            <td>{p.get("item_name","")[:40]}</td>
            <td>{p.get("item_id","")}</td>
            <td>{p.get("item_brand","")}</td>
            <td>{p.get("item_category","")}</td>
            <td>{p.get("price","")}</td>
            <td>{p.get("currency","")}</td>
        </tr>"""

    # Raw event log (first 50)
    raw_log = json.dumps(analysis["all_events"][:50], indent=2, ensure_ascii=False, default=str)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>dataLayer Audit — {base_url}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; font-size: 14px; }}
  .header {{ background: linear-gradient(135deg, #1e3a5f 0%, #7c3aed 100%); color: white; padding: 2rem 2.5rem; }}
  .header h1 {{ font-size: 1.6rem; font-weight: 700; }}
  .header .meta {{ opacity: 0.75; margin-top: 0.4rem; font-size: 0.9rem; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin-top: 1rem; }}
  .chip {{ padding: 0.3rem 0.9rem; border-radius: 999px; font-size: 0.8rem; font-weight: 600; }}
  .container {{ max-width: 1300px; margin: 0 auto; padding: 2rem 1.5rem; }}
  .section {{ background: white; border-radius: 12px; padding: 1.75rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.07); }}
  .section h2 {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 1.25rem; border-bottom: 2px solid #f1f5f9; padding-bottom: 0.75rem; color: #1e293b; }}
  .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
  .kpi {{ background: #f8fafc; border-radius: 10px; padding: 1rem; text-align: center; border-top: 3px solid #7c3aed; }}
  .kpi-value {{ font-size: 2rem; font-weight: 800; color: #1e293b; }}
  .kpi-label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; margin-top: 0.3rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
  th {{ background: #f8fafc; padding: 0.6rem 0.75rem; text-align: left; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: #64748b; border-bottom: 2px solid #e2e8f0; }}
  td {{ padding: 0.55rem 0.75rem; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
  tr:hover td {{ background: #f8fafc; }}
  tr:last-child td {{ border-bottom: none; }}
  code {{ background: #f1f5f9; padding: 1px 5px; border-radius: 4px; font-size: 0.82rem; color: #7c3aed; }}
  pre {{ background: #0f172a; color: #e2e8f0; padding: 1.25rem; border-radius: 8px; overflow-x: auto; font-size: 0.78rem; line-height: 1.6; max-height: 500px; overflow-y: auto; }}
  .tag-badge {{ background: #ede9fe; color: #5b21b6; padding: 0.3rem 0.7rem; border-radius: 6px; font-family: monospace; font-size: 0.85rem; font-weight: 700; margin-right: 0.5rem; display: inline-block; }}
</style>
</head>
<body>
<div class="header">
  <h1>🔍 dataLayer Audit Report</h1>
  <div class="meta">{base_url} &nbsp;|&nbsp; Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')} &nbsp;|&nbsp; Pages crawled: {analysis['total_pages_crawled']}</div>
  <div class="chips">
    <span class="chip" style="background:#ef4444">🔴 {len(errors)} Errors &nbsp;{len(high)} High issues</span>
    <span class="chip" style="background:#f59e0b">🟡 {len(medium)} Medium issues</span>
    <span class="chip" style="background:rgba(255,255,255,0.2)">{analysis['total_events_captured']} total events captured</span>
    <span class="chip" style="background:rgba(255,255,255,0.2)">{len(analysis['products_found'])} product items found</span>
  </div>
</div>

<div class="container">

<!-- KPIs -->
<div class="kpi-row">
  <div class="kpi"><div class="kpi-value">{analysis['total_pages_crawled']}</div><div class="kpi-label">Pages Crawled</div></div>
  <div class="kpi"><div class="kpi-value">{analysis['total_events_captured']}</div><div class="kpi-label">Events Captured</div></div>
  <div class="kpi"><div class="kpi-value">{len(analysis['ga4_events_found'])}/{len(GA4_ECOMMERCE_EVENTS)}</div><div class="kpi-label">GA4 Events Found</div></div>
  <div class="kpi"><div class="kpi-value">{len(analysis['products_found'])}</div><div class="kpi-label">Product Items</div></div>
  <div class="kpi"><div class="kpi-value">{len(issues)}</div><div class="kpi-label">Tracking Issues</div></div>
</div>

<!-- Tags detected -->
<div class="section">
  <h2>Tags Detected</h2>
  <div style="margin-bottom:0.75rem"><strong>GTM Containers:</strong> {''.join(f'<span class="tag-badge">{g}</span>' for g in analysis['gtm_ids']) or '<span style="color:#ef4444">None detected</span>'}</div>
  <div><strong>GA4 / UA IDs:</strong> {''.join(f'<span class="tag-badge">{g}</span>' for g in analysis['ga_ids']) or '<span style="color:#ef4444">None detected</span>'}</div>
</div>

<!-- Issues -->
<div class="section">
  <h2>⚠️ Tracking Issues ({len(issues)} total)</h2>
  {issues_html if issues_html else '<p style="color:#10b981;font-weight:600">✓ No tracking issues detected</p>'}
</div>

<!-- GA4 Ecommerce Coverage -->
<div class="section">
  <h2>GA4 Ecommerce Event Coverage</h2>
  <table><thead><tr><th>Event</th><th>Description</th><th>Status</th></tr></thead>
  <tbody>{ga4_rows}</tbody></table>
</div>

<!-- Per-page summary -->
<div class="section">
  <h2>Page-by-Page Summary</h2>
  <table><thead><tr><th>Page</th><th>URL</th><th>Events</th><th>Ecommerce</th><th>Events fired</th></tr></thead>
  <tbody>{page_rows}</tbody></table>
</div>

<!-- All event names -->
<div class="section">
  <h2>All Events Captured (by frequency)</h2>
  <table><thead><tr><th>Event Name</th><th>Count</th></tr></thead>
  <tbody>{ef_rows}</tbody></table>
</div>

<!-- Item field audit -->
{'<div class="section"><h2>Product Item Field Completeness</h2><table><thead><tr><th>Field</th><th>Filled</th><th>Coverage</th><th>%</th></tr></thead><tbody>' + field_rows + '</tbody></table></div>' if field_rows else ''}

<!-- Products found -->
{'<div class="section"><h2>Product Data Extracted from dataLayer</h2><table><thead><tr><th>Event</th><th>Name</th><th>ID</th><th>Brand</th><th>Category</th><th>Price</th><th>Currency</th></tr></thead><tbody>' + prod_rows + '</tbody></table></div>' if prod_rows else ''}

<!-- Raw log -->
<div class="section">
  <h2>Raw Event Log (first 50 events)</h2>
  <pre>{raw_log}</pre>
</div>

</div>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="dataLayer crawler and GA4 audit")
    parser.add_argument("--url", default="https://www.fashiondays.ro", help="Base URL to crawl")
    parser.add_argument("--headless", default="true", help="Run headless (true/false)")
    parser.add_argument("--max-products", type=int, default=5, help="Max product pages to visit")
    parser.add_argument("--output-dir", default="reports", help="Output directory")
    args = parser.parse_args()

    headless = args.headless.lower() != "false"
    url = args.url if args.url.startswith("http") else "https://" + args.url

    print(f"Starting dataLayer crawl: {url}")
    print(f"Headless: {headless} | Max products: {args.max_products}")

    crawler = DataLayerCrawler(url, headless=headless, max_products=args.max_products)
    results = await crawler.crawl()

    print(f"\nAnalyzing {sum(len(r['events']) for r in results)} captured events...")
    analysis = analyze_results(results)

    # Print quick summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Pages crawled:      {analysis['total_pages_crawled']}")
    print(f"Events captured:    {analysis['total_events_captured']}")
    print(f"GA4 events found:   {len(analysis['ga4_events_found'])}/{len(GA4_ECOMMERCE_EVENTS)}")
    print(f"GTM IDs:            {', '.join(analysis['gtm_ids']) or 'none'}")
    print(f"GA IDs:             {', '.join(analysis['ga_ids']) or 'none'}")
    print(f"Tracking issues:    {len(analysis['issues'])}")
    if analysis["issues"]:
        for i in analysis["issues"]:
            print(f"  [{i['severity']}] {i['page']}: {i['issue']}")

    # Save raw JSON
    json_path = f"{args.output_dir}/datalayer_raw_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    Path(args.output_dir).mkdir(exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "analysis": {k: v for k, v in analysis.items() if k != "all_events"}},
                  f, indent=2, ensure_ascii=False, default=str)

    # Save HTML report
    html_path = generate_report(analysis, url, args.output_dir)
    print(f"\n✅ HTML audit report: {Path(html_path).resolve()}")
    print(f"📄 Raw JSON data:     {Path(json_path).resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
