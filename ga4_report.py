"""
GA4 Report Generator
Synthesizes analysis results into actionable growth insights.
Outputs a rich terminal report + saves HTML and Excel reports.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich import box
from rich.text import Text
from rich.rule import Rule
import pandas as pd
import json
from datetime import datetime
from pathlib import Path


console = Console(width=120)


# ─────────────────────────────────────────────────────────────────────────────
# INSIGHT GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def _trend_label(trend: dict) -> str:
    if not trend or trend.get("slope") is None:
        return "N/A"
    direction = "↑" if trend["direction"] == "up" else "↓"
    sig = "*" if trend.get("significant") else ""
    return f"{direction}{sig} (R²={trend['r2']:.2f}, p={trend['p']:.3f})"


def _delta_str(val) -> str:
    if val is None:
        return "N/A"
    sign = "+" if val > 0 else ""
    color = "green" if val > 0 else "red"
    return f"[{color}]{sign}{val}%[/{color}]"


def generate_growth_insights(results: dict) -> list[dict]:
    """
    Synthesize all analysis results into prioritized growth recommendations.
    Returns a list of insight dicts: {priority, area, insight, action}.
    """
    insights = []
    traffic = results.get("traffic", {})
    ecom = results.get("ecommerce", {})
    products = results.get("products", {})
    devices = results.get("devices", {})
    acq = results.get("acquisition", {})
    geo = results.get("geo", {})
    lp = results.get("landing_pages", {})
    cohorts = results.get("cohorts", {})

    # ── Traffic insights ──────────────────────────────────────────────────────
    if traffic:
        trend = traffic.get("trend", {})
        if trend and trend.get("significant") and trend.get("direction") == "down":
            insights.append({
                "priority": "HIGH",
                "area": "Traffic",
                "insight": f"Sessions are in a statistically significant decline (slope={trend['slope']}, R²={trend['r2']}).",
                "action": "Audit top acquisition channels for budget cuts or algorithm changes. Review SEO health and check for technical issues (crawlability, page speed).",
            })

        bounce = traffic.get("avg_bounce_rate", 0)
        if bounce > 60:
            insights.append({
                "priority": "HIGH",
                "area": "Engagement",
                "insight": f"Bounce rate is {bounce}% — above the 60% warning threshold.",
                "action": "Audit landing pages for load speed, relevance, and CTA clarity. Use heatmaps to identify drop-off points.",
            })
        elif bounce > 45:
            insights.append({
                "priority": "MEDIUM",
                "area": "Engagement",
                "insight": f"Bounce rate of {bounce}% has room for improvement.",
                "action": "A/B test landing page copy and hero sections. Ensure ad/email messaging matches landing page content.",
            })

        new_pct = traffic.get("new_user_pct", 50)
        if new_pct > 80:
            insights.append({
                "priority": "MEDIUM",
                "area": "Retention",
                "insight": f"{new_pct}% of users are new — the site is not retaining customers.",
                "action": "Implement email capture with post-purchase sequences, loyalty programs, or retargeting campaigns.",
            })

        over_reliant = acq.get("over_reliant_on_one_channel")
        top_ch = acq.get("top_traffic_channel", "")
        top_share = acq.get("top_channel_traffic_share_pct", 0)
        if over_reliant:
            insights.append({
                "priority": "HIGH",
                "area": "Acquisition",
                "insight": f"Over-reliance on '{top_ch}' ({top_share}% of sessions). Single-channel dependency is a business risk.",
                "action": "Diversify into 2-3 additional channels. If organic is dominant, invest in paid social or email. If paid is dominant, invest in SEO/content.",
            })

    # ── Ecommerce insights ────────────────────────────────────────────────────
    if ecom:
        cvr = ecom.get("avg_conversion_rate_pct", 0)
        if cvr < 1.0:
            insights.append({
                "priority": "HIGH",
                "area": "Conversion",
                "insight": f"Conversion rate of {cvr}% is below the 1% industry floor for ecommerce.",
                "action": "Run UX audit on checkout flow. Reduce friction: guest checkout, trust badges, payment options. A/B test product page CTA buttons.",
            })
        elif cvr < 2.0:
            insights.append({
                "priority": "MEDIUM",
                "area": "Conversion",
                "insight": f"Conversion rate of {cvr}% is below the 2% ecommerce benchmark.",
                "action": "Implement exit-intent popups, urgency signals (limited stock), and social proof (reviews). Optimize mobile checkout.",
            })

        cvr_trend = ecom.get("cvr_trend", {})
        if cvr_trend and cvr_trend.get("significant") and cvr_trend.get("direction") == "down":
            insights.append({
                "priority": "HIGH",
                "area": "Conversion",
                "insight": "Conversion rate is in a statistically significant downward trend.",
                "action": "Check for recent site changes, price increases, or checkout bugs. Compare current vs prior period funnel drop-off rates.",
            })

        cart_to_purchase = ecom.get("cart_to_purchase_rate_pct", 0)
        if cart_to_purchase < 30:
            insights.append({
                "priority": "HIGH",
                "area": "Cart Abandonment",
                "insight": f"Only {cart_to_purchase}% of add-to-cart events result in a purchase.",
                "action": "Set up cart abandonment email sequence (1h, 24h, 72h). Add cart persistence across sessions. Offer cart-save discount.",
            })

        checkout_rate = ecom.get("avg_checkout_completion_rate_pct", 0)
        if checkout_rate and checkout_rate < 50:
            insights.append({
                "priority": "HIGH",
                "area": "Checkout",
                "insight": f"Checkout completion rate is {checkout_rate}% — more than half of initiated checkouts are abandoned.",
                "action": "Reduce checkout steps. Show progress indicator. Add trust signals at payment step. Offer more payment methods (BNPL, PayPal).",
            })

        aov_trend = ecom.get("aov_trend", {})
        if aov_trend and aov_trend.get("significant") and aov_trend.get("direction") == "down":
            insights.append({
                "priority": "MEDIUM",
                "area": "Revenue",
                "insight": "Average order value is trending down significantly.",
                "action": "Implement product bundling, minimum-order free shipping thresholds, and upsell/cross-sell recommendations at checkout.",
            })

    # ── Product insights ──────────────────────────────────────────────────────
    if products:
        pareto = products.get("pareto_top20_revenue_share_pct", 0)
        if pareto > 80:
            insights.append({
                "priority": "MEDIUM",
                "area": "Product Mix",
                "insight": f"Top 20 products drive {pareto}% of revenue — catalog is heavily concentrated.",
                "action": "Protect top-selling products with safety stock. Diversify catalog to reduce dependency. Promote mid-tier products with targeted campaigns.",
            })

        gems = products.get("hidden_gems", [])
        if gems:
            gem_names = ", ".join([g["itemName"] for g in gems[:3]])
            insights.append({
                "priority": "MEDIUM",
                "area": "Product Growth",
                "insight": f"Hidden gem products with high conversion but low exposure: {gem_names}.",
                "action": "Increase visibility of these products via homepage features, collection placements, or paid promotion. They convert well — just need more traffic.",
            })

        underperformers = products.get("underperformers", [])
        if underperformers:
            up_names = ", ".join([u["itemName"] for u in underperformers[:3]])
            insights.append({
                "priority": "LOW",
                "area": "Product Mix",
                "insight": f"High-traffic, low-conversion products: {up_names}.",
                "action": "Improve product pages: better images, clearer descriptions, competitive pricing. Consider removing or repricing if they don't improve.",
            })

    # ── Device insights ───────────────────────────────────────────────────────
    if devices:
        gap = devices.get("mobile_desktop_cvr_gap_pct")
        device_summary = devices.get("device_summary", {})
        mobile_sessions_pct = device_summary.get("mobile", {}).get("session_share_pct", 0)

        if gap is not None and gap < -20 and mobile_sessions_pct > 40:
            insights.append({
                "priority": "HIGH",
                "area": "Mobile Experience",
                "insight": f"Mobile CVR is {abs(gap)}% lower than desktop, but mobile drives {mobile_sessions_pct}% of traffic.",
                "action": "Prioritize mobile UX: simplify navigation, increase tap target sizes, streamline mobile checkout, optimize page load speed (Core Web Vitals).",
            })
        elif gap is not None and gap < -10:
            insights.append({
                "priority": "MEDIUM",
                "area": "Mobile Experience",
                "insight": f"Mobile conversion rate is {abs(gap)}% lower than desktop.",
                "action": "Review mobile checkout funnel with session recordings. Test one-tap payment options (Apple Pay, Google Pay).",
            })

    # ── Geo insights ──────────────────────────────────────────────────────────
    if geo:
        opp = geo.get("opportunity_markets", {})
        if opp:
            opp_countries = list(opp.keys())[:3]
            insights.append({
                "priority": "MEDIUM",
                "area": "Geographic Growth",
                "insight": f"High-value markets with untapped traffic potential: {', '.join(opp_countries)}.",
                "action": "Create localized campaigns, translated landing pages, or region-specific promotions for these markets. They show strong purchase intent.",
            })

        conc = geo.get("geo_concentration_top5_pct", 0)
        if conc > 90:
            insights.append({
                "priority": "LOW",
                "area": "Geographic Growth",
                "insight": f"Top 5 countries generate {conc}% of revenue — geographic concentration risk.",
                "action": "Test international expansion campaigns in high-GDP markets where your product category has demand.",
            })

    # ── Landing page insights ─────────────────────────────────────────────────
    if lp:
        fix_pages = lp.get("high_traffic_low_cvr_pages", [])
        if fix_pages:
            page_urls = [p["landingPage"] for p in fix_pages[:3]]
            insights.append({
                "priority": "HIGH",
                "area": "Landing Pages",
                "insight": f"High-traffic pages with poor conversion: {', '.join(page_urls)}.",
                "action": "Run A/B tests on these pages immediately. Prioritize CTA placement, above-the-fold content, and page load speed.",
            })

    # ── Cohort insights ───────────────────────────────────────────────────────
    if cohorts:
        ret_cvr = cohorts.get("returning_user_cvr_pct", 0)
        new_cvr = cohorts.get("new_user_cvr_pct", 0)
        ret_rpu = cohorts.get("returning_user_revenue_per_user", 0)
        new_rpu = cohorts.get("new_user_revenue_per_user", 0)
        ret_rev_share = cohorts.get("returning_revenue_share_pct", 0)

        if ret_rev_share and ret_rev_share < 30:
            insights.append({
                "priority": "HIGH",
                "area": "Retention / LTV",
                "insight": f"Returning customers generate only {ret_rev_share}% of revenue — retention is critically low.",
                "action": "Launch a loyalty program, post-purchase email flows, and personalized re-engagement campaigns. Focus on LTV, not just acquisition.",
            })

        if ret_rpu > 0 and new_rpu > 0:
            rpu_multiplier = round(ret_rpu / new_rpu, 1)
            if rpu_multiplier >= 2:
                insights.append({
                    "priority": "MEDIUM",
                    "area": "Retention / LTV",
                    "insight": f"Returning customers spend {rpu_multiplier}x more per user than new customers (${ret_rpu:.2f} vs ${new_rpu:.2f}).",
                    "action": "Double down on retention. Even small improvements in return rate have outsized revenue impact. Test win-back campaigns.",
                })

    # Sort by priority
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    insights.sort(key=lambda x: priority_order.get(x["priority"], 3))

    return insights


# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL REPORT
# ─────────────────────────────────────────────────────────────────────────────

def print_report(results: dict, insights: list[dict], property_id: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    console.print()
    console.print(Panel.fit(
        f"[bold cyan]GA4 Ecommerce Intelligence Report[/bold cyan]\n"
        f"[dim]Property: {property_id}  |  Generated: {now}  |  Period: Last 12 months[/dim]",
        box=box.DOUBLE_EDGE,
    ))

    traffic = results.get("traffic", {})
    ecom = results.get("ecommerce", {})
    devices = results.get("devices", {})
    acq = results.get("acquisition", {})
    cohorts = results.get("cohorts", {})
    products = results.get("products", {})

    # ── KPI Summary ───────────────────────────────────────────────────────────
    console.print(Rule("[bold]EXECUTIVE SUMMARY — 12-MONTH KPIs[/bold]"))
    kpi_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    kpi_table.add_column("Metric", style="cyan", width=30)
    kpi_table.add_column("Value", justify="right", width=20)
    kpi_table.add_column("30d Change", justify="right", width=15)
    kpi_table.add_column("Trend", justify="center", width=25)

    if traffic:
        kpi_table.add_row(
            "Total Sessions",
            f"{traffic.get('total_sessions', 0):,}",
            _delta_str(traffic.get("sessions_delta_30d")),
            _trend_label(traffic.get("trend", {})),
        )
        kpi_table.add_row(
            "Total Users",
            f"{traffic.get('total_users', 0):,}",
            _delta_str(traffic.get("users_delta_30d")),
            "",
        )
        kpi_table.add_row(
            "Avg Bounce Rate",
            f"{traffic.get('avg_bounce_rate', 0):.1f}%",
            "", "",
        )
        kpi_table.add_row(
            "Avg Session Duration",
            f"{traffic.get('avg_session_duration_sec', 0):.0f}s",
            "", "",
        )
        kpi_table.add_row(
            "Engagement Rate",
            f"{traffic.get('avg_engagement_rate', 0):.1f}%",
            "", "",
        )

    if ecom:
        kpi_table.add_row("", "", "", "")
        kpi_table.add_row(
            "Total Revenue",
            f"${ecom.get('total_revenue', 0):,.2f}",
            _delta_str(ecom.get("revenue_delta_30d")),
            _trend_label(ecom.get("revenue_trend", {})),
        )
        kpi_table.add_row(
            "Total Transactions",
            f"{ecom.get('total_transactions', 0):,}",
            _delta_str(ecom.get("transactions_delta_30d")),
            "",
        )
        kpi_table.add_row(
            "Avg Order Value",
            f"${ecom.get('avg_order_value', 0):,.2f}",
            "",
            _trend_label(ecom.get("aov_trend", {})),
        )
        kpi_table.add_row(
            "Conversion Rate",
            f"{ecom.get('avg_conversion_rate_pct', 0):.2f}%",
            _delta_str(ecom.get("cvr_delta_30d")),
            _trend_label(ecom.get("cvr_trend", {})),
        )
        kpi_table.add_row(
            "Cart→Purchase Rate",
            f"{ecom.get('cart_to_purchase_rate_pct', 0):.1f}%",
            "", "",
        )
        kpi_table.add_row(
            "Checkout Completion",
            f"{ecom.get('avg_checkout_completion_rate_pct', 0):.1f}%",
            "", "",
        )

    console.print(kpi_table)

    # ── Channel Breakdown ─────────────────────────────────────────────────────
    if acq:
        console.print(Rule("[bold]ACQUISITION CHANNELS[/bold]"))
        ch_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        ch_table.add_column("Channel", style="cyan", width=25)
        ch_table.add_column("Sessions", justify="right", width=12)
        ch_table.add_column("Sess %", justify="right", width=10)
        ch_table.add_column("Revenue", justify="right", width=14)
        ch_table.add_column("Rev %", justify="right", width=10)
        ch_table.add_column("CVR %", justify="right", width=10)
        ch_table.add_column("Rev/Session", justify="right", width=13)

        ch_sum = acq.get("channel_summary", {})
        for ch, v in list(ch_sum.items())[:10]:
            ch_table.add_row(
                ch,
                f"{v.get('sessions', 0):,.0f}",
                f"{v.get('session_share_pct', 0):.1f}%",
                f"${v.get('revenue', 0):,.2f}",
                f"{v.get('revenue_share_pct', 0):.1f}%",
                f"{v.get('avg_cvr_pct', 0):.2f}%",
                f"${v.get('revenue_per_session', 0):.2f}",
            )
        console.print(ch_table)

    # ── Device Performance ────────────────────────────────────────────────────
    if devices:
        console.print(Rule("[bold]DEVICE PERFORMANCE[/bold]"))
        dev_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        dev_table.add_column("Device", style="cyan", width=12)
        dev_table.add_column("Sessions", justify="right", width=12)
        dev_table.add_column("Sess %", justify="right", width=10)
        dev_table.add_column("Revenue", justify="right", width=14)
        dev_table.add_column("Rev %", justify="right", width=10)
        dev_table.add_column("CVR %", justify="right", width=10)
        dev_table.add_column("Bounce %", justify="right", width=10)
        dev_table.add_column("Rev/Session", justify="right", width=13)

        dev_sum = devices.get("device_summary", {})
        for dev, v in dev_sum.items():
            dev_table.add_row(
                dev,
                f"{v.get('sessions', 0):,.0f}",
                f"{v.get('session_share_pct', 0):.1f}%",
                f"${v.get('revenue', 0):,.2f}",
                f"{v.get('revenue_share_pct', 0):.1f}%",
                f"{v.get('avg_cvr_pct', 0):.2f}%",
                f"{v.get('avg_bounce_pct', 0):.1f}%",
                f"${v.get('revenue_per_session', 0):.2f}",
            )
        console.print(dev_table)

        gap = devices.get("mobile_desktop_cvr_gap_pct")
        if gap is not None:
            color = "red" if gap < -10 else "green"
            console.print(f"  Mobile vs Desktop CVR gap: [{color}]{gap:+.1f}%[/{color}]")

    # ── Top Products ──────────────────────────────────────────────────────────
    if products:
        console.print(Rule("[bold]TOP 10 PRODUCTS BY REVENUE[/bold]"))
        prod_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        prod_table.add_column("Product", style="cyan", width=35)
        prod_table.add_column("Category", width=20)
        prod_table.add_column("Revenue", justify="right", width=14)
        prod_table.add_column("Units", justify="right", width=10)
        prod_table.add_column("Views", justify="right", width=10)
        prod_table.add_column("V→Cart%", justify="right", width=10)

        for p in products.get("top_10_by_revenue", []):
            prod_table.add_row(
                str(p.get("itemName", ""))[:34],
                str(p.get("itemCategory", ""))[:19],
                f"${p.get('itemRevenue', 0):,.2f}",
                f"{p.get('itemsPurchased', 0):,.0f}",
                f"{p.get('itemsViewed', 0):,.0f}",
                f"{p.get('cartToViewRate', 0)*100:.1f}%" if p.get('cartToViewRate') else "N/A",
            )
        console.print(prod_table)

        console.print(f"  Revenue concentration: top 20 products = [bold]{products.get('pareto_top20_revenue_share_pct', 0):.1f}%[/bold] of total revenue")

    # ── User Cohorts ──────────────────────────────────────────────────────────
    if cohorts:
        console.print(Rule("[bold]NEW VS RETURNING USERS[/bold]"))
        coh_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        coh_table.add_column("Segment", style="cyan", width=20)
        coh_table.add_column("User %", justify="right", width=12)
        coh_table.add_column("CVR %", justify="right", width=12)
        coh_table.add_column("Rev/User", justify="right", width=14)
        coh_table.add_column("Rev Share %", justify="right", width=14)

        coh_table.add_row(
            "New Users",
            f"{cohorts.get('new_user_pct', 0):.1f}%",
            f"{cohorts.get('new_user_cvr_pct', 0):.2f}%",
            f"${cohorts.get('new_user_revenue_per_user', 0):.2f}",
            f"{100 - cohorts.get('returning_revenue_share_pct', 0):.1f}%",
        )
        coh_table.add_row(
            "Returning Users",
            f"{cohorts.get('returning_user_pct', 0):.1f}%",
            f"{cohorts.get('returning_user_cvr_pct', 0):.2f}%",
            f"${cohorts.get('returning_user_revenue_per_user', 0):.2f}",
            f"{cohorts.get('returning_revenue_share_pct', 0):.1f}%",
        )
        console.print(coh_table)

    # ── Growth Insights ───────────────────────────────────────────────────────
    console.print(Rule("[bold]GROWTH INSIGHTS & RECOMMENDATIONS[/bold]"))
    priority_colors = {"HIGH": "bold red", "MEDIUM": "bold yellow", "LOW": "dim cyan"}

    for i, ins in enumerate(insights, 1):
        color = priority_colors.get(ins["priority"], "white")
        console.print(Panel(
            f"[bold]{ins['area']}[/bold]\n\n"
            f"[white]{ins['insight']}[/white]\n\n"
            f"[green]Action:[/green] {ins['action']}",
            title=f"[{color}][{ins['priority']}] #{i}[/{color}]",
            expand=False,
            box=box.ROUNDED,
        ))

    console.print()
    console.print(f"[dim]Total insights generated: {len(insights)} "
                  f"({sum(1 for i in insights if i['priority']=='HIGH')} High, "
                  f"{sum(1 for i in insights if i['priority']=='MEDIUM')} Medium, "
                  f"{sum(1 for i in insights if i['priority']=='LOW')} Low)[/dim]")
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# SAVE REPORTS
# ─────────────────────────────────────────────────────────────────────────────

def save_excel_report(data: dict, results: dict, insights: list[dict], output_dir: str = "reports"):
    Path(output_dir).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"{output_dir}/ga4_report_{ts}.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # Raw data sheets
        for key, df in data.items():
            if not df.empty:
                df.to_excel(writer, sheet_name=key[:31], index=False)

        # Insights sheet
        if insights:
            ins_df = pd.DataFrame(insights)
            ins_df.to_excel(writer, sheet_name="Growth Insights", index=False)

        # Summary KPIs
        summary_rows = []
        traffic = results.get("traffic", {})
        ecom = results.get("ecommerce", {})
        for k, v in {**traffic, **ecom}.items():
            if isinstance(v, (int, float, str)):
                summary_rows.append({"Metric": k, "Value": v})
        if summary_rows:
            pd.DataFrame(summary_rows).to_excel(writer, sheet_name="KPI Summary", index=False)

    print(f"\nExcel report saved: {path}")
    return path


def save_json_results(results: dict, insights: list[dict], output_dir: str = "reports"):
    Path(output_dir).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"{output_dir}/ga4_analysis_{ts}.json"

    def _serialize(obj):
        if isinstance(obj, (pd.Timestamp, pd.Period)):
            return str(obj)
        if isinstance(obj, float) and (obj != obj):  # NaN
            return None
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    payload = {"results": results, "insights": insights, "generated_at": datetime.now().isoformat()}
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=_serialize)

    print(f"JSON results saved: {path}")
    return path
