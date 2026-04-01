"""
GA4 HTML Report Generator
Produces a self-contained HTML dashboard with charts and insights.
Opens in any browser — no dependencies needed to view it.
"""

import json
import os
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np


def _fmt_currency(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    return f"${val:,.2f}"

def _fmt_number(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    return f"{int(val):,}"

def _fmt_pct(val, decimals=1):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    return f"{val:.{decimals}f}%"

def _delta_badge(val):
    if val is None:
        return '<span class="badge neutral">N/A</span>'
    color = "up" if val > 0 else "down"
    arrow = "▲" if val > 0 else "▼"
    return f'<span class="badge {color}">{arrow} {abs(val):.1f}%</span>'

def _trend_badge(trend):
    if not trend or trend.get("slope") is None:
        return '<span class="badge neutral">No data</span>'
    sig = trend.get("significant", False)
    direction = trend.get("direction", "unknown")
    r2 = trend.get("r2", 0)
    if not sig:
        return f'<span class="badge neutral">Flat (R²={r2:.2f})</span>'
    if direction == "up":
        return f'<span class="badge up">↑ Growing (R²={r2:.2f})</span>'
    return f'<span class="badge down">↓ Declining (R²={r2:.2f})</span>'

def _priority_color(p):
    return {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#6b7280"}.get(p, "#6b7280")

def _priority_bg(p):
    return {"HIGH": "#fef2f2", "MEDIUM": "#fffbeb", "LOW": "#f9fafb"}.get(p, "#f9fafb")

def _safe(val, default="N/A"):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    return val


# ── Chart data helpers ────────────────────────────────────────────────────────

def _monthly_revenue_chart(ecom_results):
    monthly = ecom_results.get("monthly_revenue", {})
    if not monthly:
        return ""
    labels = [str(k) for k in monthly.keys()]
    values = [round(float(v), 2) if v else 0 for v in monthly.values()]
    return json.dumps({"labels": labels, "values": values})

def _channel_chart(acq_results):
    ch = acq_results.get("channel_summary", {})
    if not ch:
        return ""
    items = sorted(ch.items(), key=lambda x: x[1].get("revenue", 0), reverse=True)[:8]
    labels = [k for k, _ in items]
    revenues = [round(v.get("revenue", 0), 2) for _, v in items]
    sessions = [int(v.get("sessions", 0)) for _, v in items]
    return json.dumps({"labels": labels, "revenues": revenues, "sessions": sessions})

def _device_chart(device_results):
    dev = device_results.get("device_summary", {})
    if not dev:
        return ""
    labels = list(dev.keys())
    sessions = [int(v.get("sessions", 0)) for v in dev.values()]
    revenues = [round(v.get("revenue", 0), 2) for v in dev.values()]
    cvrs = [round(v.get("avg_cvr_pct", 0), 2) for v in dev.values()]
    return json.dumps({"labels": labels, "sessions": sessions, "revenues": revenues, "cvrs": cvrs})

def _top_products_chart(prod_results):
    prods = prod_results.get("top_10_by_revenue", [])
    if not prods:
        return ""
    labels = [p.get("itemName", "")[:30] for p in prods[:8]]
    revenues = [round(p.get("itemRevenue", 0), 2) for p in prods[:8]]
    return json.dumps({"labels": labels, "revenues": revenues})

def _category_chart(prod_results):
    cats = prod_results.get("category_performance", {})
    if not cats:
        return ""
    items = sorted(cats.items(), key=lambda x: x[1].get("revenue", 0), reverse=True)[:8]
    labels = [k for k, _ in items]
    revenues = [round(v.get("revenue", 0), 2) for _, v in items]
    return json.dumps({"labels": labels, "revenues": revenues})


# ── HTML sections ─────────────────────────────────────────────────────────────

def _kpi_cards(results):
    t = results.get("traffic", {})
    e = results.get("ecommerce", {})
    cards = [
        ("Total Revenue", _fmt_currency(e.get("total_revenue")), _delta_badge(e.get("revenue_delta_30d")), _trend_badge(e.get("revenue_trend")), "💰"),
        ("Total Transactions", _fmt_number(e.get("total_transactions")), _delta_badge(e.get("transactions_delta_30d")), "", "🛒"),
        ("Avg Order Value", _fmt_currency(e.get("avg_order_value")), "", _trend_badge(e.get("aov_trend")), "📦"),
        ("Conversion Rate", _fmt_pct(e.get("avg_conversion_rate_pct"), 2), _delta_badge(e.get("cvr_delta_30d")), _trend_badge(e.get("cvr_trend")), "🎯"),
        ("Total Sessions", _fmt_number(t.get("total_sessions")), _delta_badge(t.get("sessions_delta_30d")), _trend_badge(t.get("trend")), "👥"),
        ("Total Users", _fmt_number(t.get("total_users")), _delta_badge(t.get("users_delta_30d")), "", "🌐"),
        ("Bounce Rate", _fmt_pct(t.get("avg_bounce_rate")), "", "", "↩️"),
        ("Avg Session Duration", f"{int(t.get('avg_session_duration_sec') or 0)}s", "", "", "⏱️"),
    ]
    html = '<div class="kpi-grid">'
    for title, value, delta, trend, icon in cards:
        html += f"""
        <div class="kpi-card">
            <div class="kpi-icon">{icon}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-title">{title}</div>
            <div class="kpi-meta">{delta} {trend}</div>
        </div>"""
    html += "</div>"
    return html


def _funnel_section(results):
    e = results.get("ecommerce", {})
    steps = [
        ("Sessions", 100, "#3b82f6"),
        ("Add to Cart", _safe(e.get("avg_cart_to_view_rate_pct"), 0), "#8b5cf6"),
        ("Checkout Started", _safe(e.get("avg_checkout_completion_rate_pct"), 0) * 0.8, "#ec4899"),
        ("Purchase", _safe(e.get("avg_conversion_rate_pct"), 0), "#10b981"),
    ]
    html = '<div class="funnel-section"><h3>Conversion Funnel</h3><div class="funnel">'
    for label, pct, color in steps:
        width = max(5, float(pct))
        html += f"""
        <div class="funnel-step">
            <div class="funnel-bar-wrap">
                <div class="funnel-bar" style="width:{min(width,100)}%; background:{color}"></div>
            </div>
            <span class="funnel-label">{label} <strong>{pct:.1f}%</strong></span>
        </div>"""
    html += "</div></div>"
    return html


def _cohort_section(results):
    c = results.get("cohorts", {})
    if not c:
        return ""
    rows = [
        ("New Users", _fmt_pct(c.get("new_user_pct")), _fmt_pct(c.get("new_user_cvr_pct"), 2), _fmt_currency(c.get("new_user_revenue_per_user")), _fmt_pct(100 - (c.get("returning_revenue_share_pct") or 0))),
        ("Returning Users", _fmt_pct(c.get("returning_user_pct")), _fmt_pct(c.get("returning_user_cvr_pct"), 2), _fmt_currency(c.get("returning_user_revenue_per_user")), _fmt_pct(c.get("returning_revenue_share_pct"))),
    ]
    html = """<div class="section"><h2>New vs Returning Users</h2>
    <table class="data-table"><thead><tr>
        <th>Segment</th><th>% of Users</th><th>CVR</th><th>Revenue/User</th><th>Revenue Share</th>
    </tr></thead><tbody>"""
    for row in rows:
        html += "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
    html += "</tbody></table></div>"
    return html


def _geo_section(results):
    g = results.get("geo", {})
    countries = g.get("top_10_countries", {})
    if not countries:
        return ""
    html = """<div class="section"><h2>Top Countries by Revenue</h2>
    <table class="data-table"><thead><tr>
        <th>Country</th><th>Sessions</th><th>Revenue</th><th>Rev Share</th><th>CVR</th><th>Rev/User</th>
    </tr></thead><tbody>"""
    for country, v in list(countries.items())[:10]:
        html += f"""<tr>
            <td><strong>{country}</strong></td>
            <td>{_fmt_number(v.get("sessions"))}</td>
            <td>{_fmt_currency(v.get("revenue"))}</td>
            <td>{_fmt_pct(v.get("revenue_share_pct"))}</td>
            <td>{_fmt_pct(v.get("avg_cvr_pct"), 2)}</td>
            <td>{_fmt_currency(v.get("revenue_per_user"))}</td>
        </tr>"""
    opp = g.get("opportunity_markets", {})
    if opp:
        html += f"""</tbody></table>
        <div class="callout callout-green">
        <strong>📈 Opportunity Markets</strong> — High revenue/user but low traffic:
        {", ".join(list(opp.keys())[:5])}. Consider targeted campaigns here.
        </div>"""
    else:
        html += "</tbody></table>"
    html += "</div>"
    return html


def _landing_pages_section(results):
    lp = results.get("landing_pages", {})
    fix = lp.get("high_traffic_low_cvr_pages", [])
    top = lp.get("top_10_by_revenue", [])
    if not top and not fix:
        return ""
    html = '<div class="section"><h2>Landing Pages</h2>'
    if fix:
        html += '<h3>⚠️ High Traffic, Low Conversion — Fix These First</h3>'
        html += '<table class="data-table"><thead><tr><th>Page</th><th>Sessions</th><th>CVR</th><th>Bounce Rate</th></tr></thead><tbody>'
        for p in fix:
            html += f"""<tr>
                <td class="page-url">{p.get("landingPage", "")}</td>
                <td>{_fmt_number(p.get("sessions"))}</td>
                <td class="bad">{_fmt_pct(p.get("sessionConversionRate", 0)*100, 2)}</td>
                <td class="bad">{_fmt_pct(p.get("bounceRate", 0)*100, 1)}</td>
            </tr>"""
        html += '</tbody></table>'
    if top:
        html += '<h3 style="margin-top:1.5rem">Top Revenue Pages</h3>'
        html += '<table class="data-table"><thead><tr><th>Page</th><th>Sessions</th><th>Revenue</th><th>CVR</th></tr></thead><tbody>'
        for p in top[:5]:
            html += f"""<tr>
                <td class="page-url">{p.get("landingPage", "")}</td>
                <td>{_fmt_number(p.get("sessions"))}</td>
                <td>{_fmt_currency(p.get("totalRevenue"))}</td>
                <td>{_fmt_pct(p.get("sessionConversionRate", 0)*100, 2)}</td>
            </tr>"""
        html += '</tbody></table>'
    html += '</div>'
    return html


def _insights_section(insights):
    if not insights:
        return ""
    html = '<div class="section"><h2>Growth Insights & Recommendations</h2><div class="insights-grid">'
    for i, ins in enumerate(insights, 1):
        p = ins["priority"]
        color = _priority_color(p)
        bg = _priority_bg(p)
        html += f"""
        <div class="insight-card" style="border-left:4px solid {color}; background:{bg}">
            <div class="insight-header">
                <span class="priority-badge" style="background:{color}">{'🔴' if p=='HIGH' else '🟡' if p=='MEDIUM' else '⚪'} {p}</span>
                <span class="insight-area">{ins['area']}</span>
                <span class="insight-num">#{i}</span>
            </div>
            <div class="insight-text">{ins['insight']}</div>
            <div class="insight-action"><strong>→ Action:</strong> {ins['action']}</div>
        </div>"""
    html += "</div></div>"
    return html


def _products_section(results):
    p = results.get("products", {})
    if not p:
        return ""
    top = p.get("top_10_by_revenue", [])
    gems = p.get("hidden_gems", [])
    under = p.get("underperformers", [])

    html = f"""<div class="section"><h2>Product Performance</h2>
    <div class="stat-row">
        <div class="stat-pill">Total Products: <strong>{_fmt_number(p.get("total_products"))}</strong></div>
        <div class="stat-pill">Total Revenue: <strong>{_fmt_currency(p.get("total_product_revenue"))}</strong></div>
        <div class="stat-pill">Top 20 = <strong>{_fmt_pct(p.get("pareto_top20_revenue_share_pct"))}</strong> of revenue</div>
    </div>"""

    if top:
        html += '<h3>Top 10 Products by Revenue</h3>'
        html += '<table class="data-table"><thead><tr><th>Product</th><th>Category</th><th>Revenue</th><th>Units</th><th>Views</th><th>View→Cart</th></tr></thead><tbody>'
        for prod in top:
            cvr_raw = prod.get("cartToViewRate", 0)
            cvr = cvr_raw * 100 if cvr_raw and cvr_raw <= 1 else (cvr_raw or 0)
            html += f"""<tr>
                <td><strong>{prod.get("itemName","")[:50]}</strong></td>
                <td>{prod.get("itemCategory","")}</td>
                <td>{_fmt_currency(prod.get("itemRevenue"))}</td>
                <td>{_fmt_number(prod.get("itemsPurchased"))}</td>
                <td>{_fmt_number(prod.get("itemsViewed"))}</td>
                <td>{_fmt_pct(cvr, 1)}</td>
            </tr>"""
        html += '</tbody></table>'

    if gems:
        html += '<div class="callout callout-blue"><strong>💎 Hidden Gems</strong> — High conversion but underexposed: '
        html += ", ".join([f"<strong>{g['itemName']}</strong> ({_fmt_pct(g.get('view_to_cart_pct'))} V→Cart)" for g in gems[:4]])
        html += ". Promote these — they convert well.</div>"

    if under:
        html += '<div class="callout callout-orange"><strong>⚠️ Underperformers</strong> — High views but low conversion: '
        html += ", ".join([f"<strong>{u['itemName']}</strong>" for u in under[:4]])
        html += ". Improve product pages or reprice.</div>"

    html += "</div>"
    return html


# ── Main HTML builder ─────────────────────────────────────────────────────────

def generate_html_report(results: dict, insights: list, property_id: str, output_dir: str = "reports") -> str:
    Path(output_dir).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"{output_dir}/ga4_dashboard_{ts}.html"

    t = results.get("traffic", {})
    e = results.get("ecommerce", {})
    acq = results.get("acquisition", {})
    prod = results.get("products", {})
    dev = results.get("devices", {})

    high_count = sum(1 for i in insights if i["priority"] == "HIGH")
    med_count = sum(1 for i in insights if i["priority"] == "MEDIUM")
    low_count = sum(1 for i in insights if i["priority"] == "LOW")

    monthly_chart = _monthly_revenue_chart(e)
    channel_chart = _channel_chart(acq)
    device_chart = _device_chart(dev)
    products_chart = _top_products_chart(prod)
    category_chart = _category_chart(prod)

    def _safe_json(s):
        return s if s else "null"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GA4 Ecommerce Report — Property {property_id}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; }}
  .header {{ background: linear-gradient(135deg, #1e3a5f 0%, #0f766e 100%); color: white; padding: 2rem 2.5rem; }}
  .header h1 {{ font-size: 1.8rem; font-weight: 700; }}
  .header .meta {{ margin-top: 0.5rem; opacity: 0.75; font-size: 0.9rem; }}
  .header .summary-chips {{ display: flex; gap: 1rem; margin-top: 1rem; flex-wrap: wrap; }}
  .chip {{ padding: 0.3rem 0.8rem; border-radius: 999px; font-size: 0.8rem; font-weight: 600; }}
  .chip-red {{ background: #ef4444; }}
  .chip-yellow {{ background: #f59e0b; }}
  .chip-gray {{ background: rgba(255,255,255,0.2); }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 2rem 1.5rem; }}
  .section {{ background: white; border-radius: 12px; padding: 1.75rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.07); }}
  .section h2 {{ font-size: 1.2rem; font-weight: 700; color: #1e293b; margin-bottom: 1.25rem; border-bottom: 2px solid #f1f5f9; padding-bottom: 0.75rem; }}
  .section h3 {{ font-size: 1rem; font-weight: 600; color: #475569; margin: 1rem 0 0.75rem; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 1rem; }}
  .kpi-card {{ background: white; border-radius: 12px; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.07); border-top: 3px solid #3b82f6; }}
  .kpi-icon {{ font-size: 1.4rem; margin-bottom: 0.5rem; }}
  .kpi-value {{ font-size: 1.5rem; font-weight: 800; color: #1e293b; }}
  .kpi-title {{ font-size: 0.78rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin: 0.25rem 0; }}
  .kpi-meta {{ font-size: 0.8rem; margin-top: 0.5rem; display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }}
  .badge {{ padding: 0.2rem 0.5rem; border-radius: 999px; font-size: 0.72rem; font-weight: 600; }}
  .badge.up {{ background: #d1fae5; color: #065f46; }}
  .badge.down {{ background: #fee2e2; color: #991b1b; }}
  .badge.neutral {{ background: #f1f5f9; color: #64748b; }}
  .charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }}
  .chart-card {{ background: white; border-radius: 12px; padding: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.07); }}
  .chart-card h3 {{ font-size: 1rem; font-weight: 700; color: #1e293b; margin-bottom: 1rem; }}
  .chart-wrap {{ position: relative; height: 260px; }}
  .data-table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
  .data-table th {{ background: #f8fafc; padding: 0.65rem 0.75rem; text-align: left; font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: #64748b; border-bottom: 2px solid #e2e8f0; }}
  .data-table td {{ padding: 0.6rem 0.75rem; border-bottom: 1px solid #f1f5f9; }}
  .data-table tr:hover td {{ background: #f8fafc; }}
  .data-table tr:last-child td {{ border-bottom: none; }}
  .page-url {{ font-family: monospace; font-size: 0.8rem; color: #3b82f6; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .bad {{ color: #ef4444; font-weight: 600; }}
  .good {{ color: #10b981; font-weight: 600; }}
  .insights-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 1rem; }}
  .insight-card {{ border-radius: 8px; padding: 1.1rem 1.25rem; }}
  .insight-header {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.6rem; flex-wrap: wrap; }}
  .priority-badge {{ padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.72rem; font-weight: 700; color: white; }}
  .insight-area {{ font-size: 0.85rem; font-weight: 700; color: #1e293b; flex: 1; }}
  .insight-num {{ font-size: 0.75rem; color: #94a3b8; }}
  .insight-text {{ font-size: 0.88rem; color: #374151; margin-bottom: 0.6rem; line-height: 1.5; }}
  .insight-action {{ font-size: 0.85rem; color: #1e40af; background: rgba(59,130,246,0.08); padding: 0.6rem 0.8rem; border-radius: 6px; line-height: 1.5; }}
  .funnel-section {{ margin-top: 1.25rem; }}
  .funnel {{ display: flex; flex-direction: column; gap: 0.6rem; }}
  .funnel-step {{ display: flex; align-items: center; gap: 1rem; }}
  .funnel-bar-wrap {{ flex: 1; background: #f1f5f9; border-radius: 999px; height: 28px; overflow: hidden; }}
  .funnel-bar {{ height: 100%; border-radius: 999px; transition: width 0.3s; min-width: 4px; }}
  .funnel-label {{ width: 180px; font-size: 0.85rem; color: #374151; white-space: nowrap; }}
  .callout {{ padding: 0.9rem 1rem; border-radius: 8px; font-size: 0.875rem; line-height: 1.6; margin-top: 1rem; }}
  .callout-green {{ background: #f0fdf4; border-left: 4px solid #22c55e; }}
  .callout-blue {{ background: #eff6ff; border-left: 4px solid #3b82f6; }}
  .callout-orange {{ background: #fff7ed; border-left: 4px solid #f97316; }}
  .stat-row {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1rem; }}
  .stat-pill {{ background: #f1f5f9; padding: 0.4rem 0.9rem; border-radius: 999px; font-size: 0.85rem; color: #475569; }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
  @media (max-width: 900px) {{
    .charts-grid, .two-col {{ grid-template-columns: 1fr; }}
    .insights-grid {{ grid-template-columns: 1fr; }}
    .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>📊 GA4 Ecommerce Intelligence Report</h1>
  <div class="meta">Property ID: {property_id} &nbsp;|&nbsp; Period: Last 12 months &nbsp;|&nbsp; Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}</div>
  <div class="summary-chips">
    <span class="chip chip-red">🔴 {high_count} High-priority insights</span>
    <span class="chip chip-yellow">🟡 {med_count} Medium-priority insights</span>
    <span class="chip chip-gray">⚪ {low_count} Low-priority insights</span>
  </div>
</div>

<div class="container">

<!-- KPI Cards -->
<div class="section">
  <h2>Executive Summary — 12-Month KPIs</h2>
  {_kpi_cards(results)}
  <div class="two-col" style="margin-top:1.5rem">
    <div>
      {_funnel_section(results)}
    </div>
    <div>
      <h3>New vs Returning</h3>
      {'<canvas id="cohortChart" height="200"></canvas>' if results.get("cohorts") else '<p style="color:#94a3b8">No cohort data</p>'}
    </div>
  </div>
</div>

<!-- Charts Row 1 -->
<div class="charts-grid">
  <div class="chart-card">
    <h3>📅 Monthly Revenue</h3>
    <div class="chart-wrap"><canvas id="monthlyRevChart"></canvas></div>
  </div>
  <div class="chart-card">
    <h3>📣 Revenue by Channel</h3>
    <div class="chart-wrap"><canvas id="channelChart"></canvas></div>
  </div>
</div>

<!-- Charts Row 2 -->
<div class="charts-grid">
  <div class="chart-card">
    <h3>📱 Sessions & Revenue by Device</h3>
    <div class="chart-wrap"><canvas id="deviceChart"></canvas></div>
  </div>
  <div class="chart-card">
    <h3>🏆 Top Products by Revenue</h3>
    <div class="chart-wrap"><canvas id="productsChart"></canvas></div>
  </div>
</div>

<!-- Acquisition -->
{_acquisition_section(results)}

<!-- Products -->
{_products_section(results)}

<!-- Geo -->
{_geo_section(results)}

<!-- Landing Pages -->
{_landing_pages_section(results)}

<!-- Cohorts table -->
{_cohort_section(results)}

<!-- Insights -->
{_insights_section(insights)}

</div>

<script>
const MONTHLY = {_safe_json(monthly_chart)};
const CHANNELS = {_safe_json(channel_chart)};
const DEVICES = {_safe_json(device_chart)};
const PRODUCTS = {_safe_json(products_chart)};

const PALETTE = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#06b6d4','#84cc16'];

// Monthly Revenue
if (MONTHLY) {{
  new Chart(document.getElementById('monthlyRevChart'), {{
    type: 'bar',
    data: {{
      labels: MONTHLY.labels,
      datasets: [{{ label: 'Revenue', data: MONTHLY.values, backgroundColor: '#3b82f6', borderRadius: 6 }}]
    }},
    options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }}}},
      scales: {{ y: {{ ticks: {{ callback: v => '$' + v.toLocaleString() }}}}, x: {{ ticks: {{ maxRotation: 45 }}}}}}
    }}
  }});
}}

// Channel Chart
if (CHANNELS) {{
  new Chart(document.getElementById('channelChart'), {{
    type: 'bar',
    data: {{
      labels: CHANNELS.labels,
      datasets: [
        {{ label: 'Revenue ($)', data: CHANNELS.revenues, backgroundColor: '#3b82f6', borderRadius: 4, yAxisID: 'y' }},
        {{ label: 'Sessions', data: CHANNELS.sessions, backgroundColor: '#10b981', borderRadius: 4, yAxisID: 'y2' }}
      ]
    }},
    options: {{ responsive: true, maintainAspectRatio: false,
      scales: {{
        y: {{ type:'linear', position:'left', ticks: {{ callback: v => '$' + v.toLocaleString() }}}},
        y2: {{ type:'linear', position:'right', grid: {{ drawOnChartArea: false }}}}
      }}
    }}
  }});
}}

// Device Chart
if (DEVICES) {{
  new Chart(document.getElementById('deviceChart'), {{
    type: 'bar',
    data: {{
      labels: DEVICES.labels,
      datasets: [
        {{ label: 'Sessions', data: DEVICES.sessions, backgroundColor: PALETTE.slice(0,3), borderRadius: 6 }},
      ]
    }},
    options: {{ responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }}}},
    }}
  }});
}}

// Products Chart
if (PRODUCTS) {{
  new Chart(document.getElementById('productsChart'), {{
    type: 'bar',
    data: {{
      labels: PRODUCTS.labels,
      datasets: [{{ label: 'Revenue', data: PRODUCTS.revenues, backgroundColor: PALETTE, borderRadius: 6 }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }}}},
      scales: {{ x: {{ ticks: {{ callback: v => '$' + v.toLocaleString() }}}}}}
    }}
  }});
}}

// Cohort doughnut
const cohortData = {json.dumps({"new": results.get("cohorts", {}).get("new_user_pct", 0), "returning": results.get("cohorts", {}).get("returning_user_pct", 0)})};
if (cohortData.new || cohortData.returning) {{
  new Chart(document.getElementById('cohortChart'), {{
    type: 'doughnut',
    data: {{
      labels: ['New Users', 'Returning Users'],
      datasets: [{{ data: [cohortData.new, cohortData.returning], backgroundColor: ['#3b82f6','#10b981'], borderWidth: 0 }}]
    }},
    options: {{ responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ position: 'bottom' }}}}
    }}
  }});
}}
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nHTML dashboard saved: {path}")
    return path


def _acquisition_section(results):
    acq = results.get("acquisition", {})
    if not acq:
        return ""
    ch = acq.get("channel_summary", {})
    if not ch:
        return ""
    html = """<div class="section"><h2>Acquisition Channels</h2>
    <table class="data-table"><thead><tr>
        <th>Channel</th><th>Sessions</th><th>Sess %</th><th>Revenue</th><th>Rev %</th><th>CVR</th><th>Rev/Session</th><th>Bounce</th>
    </tr></thead><tbody>"""
    for channel, v in list(ch.items())[:10]:
        rps = v.get("revenue_per_session", 0)
        cvr = v.get("avg_cvr_pct", 0)
        html += f"""<tr>
            <td><strong>{channel}</strong></td>
            <td>{_fmt_number(v.get("sessions"))}</td>
            <td>{_fmt_pct(v.get("session_share_pct"))}</td>
            <td>{_fmt_currency(v.get("revenue"))}</td>
            <td>{_fmt_pct(v.get("revenue_share_pct"))}</td>
            <td class="{'good' if cvr > 2 else 'bad' if cvr < 1 else ''}">{_fmt_pct(cvr, 2)}</td>
            <td>{_fmt_currency(rps)}</td>
            <td>{_fmt_pct(v.get("avg_bounce_pct"))}</td>
        </tr>"""
    html += "</tbody></table></div>"
    return html
