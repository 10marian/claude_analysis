"""
GA4 Statistical Analysis Engine
Applies trend analysis, seasonality detection, anomaly detection,
correlation analysis, and product/channel insights.
"""

import pandas as pd
import numpy as np
from scipy import stats
from scipy.signal import find_peaks
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _safe_pct(new, old):
    if old == 0 or pd.isna(old):
        return None
    return round((new - old) / abs(old) * 100, 1)


def _linear_trend(series: pd.Series) -> dict:
    """Fit OLS trend, return slope, r2, p-value, direction."""
    s = series.dropna()
    if len(s) < 7:
        return {"slope": None, "r2": None, "p": None, "direction": "unknown"}
    x = np.arange(len(s)).reshape(-1, 1)
    y = s.values
    model = LinearRegression().fit(x, y)
    y_pred = model.predict(x)
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0
    slope, intercept, r, p, se = stats.linregress(x.ravel(), y)
    return {
        "slope": round(float(slope), 4),
        "r2": round(float(r2), 4),
        "p": round(float(p), 4),
        "direction": "up" if slope > 0 else "down",
        "significant": p < 0.05,
    }


def _detect_anomalies_zscore(series: pd.Series, threshold: float = 2.5) -> pd.Series:
    """Return boolean mask of anomalies using z-score."""
    z = np.abs(stats.zscore(series.fillna(series.median())))
    return pd.Series(z > threshold, index=series.index)


def _mom_growth(df: pd.DataFrame, date_col: str, value_col: str) -> pd.DataFrame:
    """Month-over-month growth rates."""
    monthly = df.groupby(df[date_col].dt.to_period("M"))[value_col].sum()
    monthly = monthly.to_frame()
    monthly["mom_pct"] = monthly[value_col].pct_change() * 100
    return monthly


def _pareto_share(series: pd.Series, top_n: int = 20) -> float:
    """What % of total value is in top N items."""
    total = series.sum()
    if total == 0:
        return 0.0
    return round(series.nlargest(top_n).sum() / total * 100, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 1. TRAFFIC ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_traffic(daily_traffic: pd.DataFrame) -> dict:
    if daily_traffic.empty:
        return {}

    df = daily_traffic.groupby("date").agg(
        sessions=("sessions", "sum"),
        users=("totalUsers", "sum"),
        new_users=("newUsers", "sum"),
        bounce_rate=("bounceRate", "mean"),
        avg_session_dur=("averageSessionDuration", "mean"),
        engagement_rate=("engagementRate", "mean"),
    ).reset_index().sort_values("date")

    # Overall totals
    total_sessions = df["sessions"].sum()
    total_users = df["users"].sum()
    avg_daily_sessions = df["sessions"].mean()

    # 30-day vs prior-30-day comparison
    recent = df.tail(30)
    prior = df.iloc[-60:-30] if len(df) >= 60 else df.head(30)
    sessions_delta = _safe_pct(recent["sessions"].sum(), prior["sessions"].sum())
    users_delta = _safe_pct(recent["users"].sum(), prior["users"].sum())

    # Trend
    trend = _linear_trend(df["sessions"])

    # Anomalies
    df["is_anomaly"] = _detect_anomalies_zscore(df["sessions"])
    anomaly_dates = df[df["is_anomaly"]]["date"].dt.strftime("%Y-%m-%d").tolist()

    # Day-of-week pattern
    df["dow"] = df["date"].dt.day_name()
    dow_avg = df.groupby("dow")["sessions"].mean().round(0)
    best_dow = dow_avg.idxmax()
    worst_dow = dow_avg.idxmin()

    # Monthly trend
    mom = _mom_growth(df, "date", "sessions")
    avg_mom_growth = mom["mom_pct"].dropna().mean()

    # Weekday vs weekend
    df["is_weekend"] = df["date"].dt.dayofweek >= 5
    weekday_avg = df[~df["is_weekend"]]["sessions"].mean()
    weekend_avg = df[df["is_weekend"]]["sessions"].mean()

    # New vs returning ratio
    df["returning_users"] = df["users"] - df["new_users"]
    new_pct = (df["new_users"].sum() / df["users"].sum() * 100).round(1) if df["users"].sum() > 0 else 0

    # Channel share
    channel_share = daily_traffic.groupby("sessionDefaultChannelGroup")["sessions"].sum()
    channel_share_pct = (channel_share / channel_share.sum() * 100).round(1).sort_values(ascending=False)

    return {
        "total_sessions": int(total_sessions),
        "total_users": int(total_users),
        "avg_daily_sessions": round(avg_daily_sessions, 0),
        "sessions_delta_30d": sessions_delta,
        "users_delta_30d": users_delta,
        "trend": trend,
        "avg_mom_growth_pct": round(avg_mom_growth, 1),
        "anomaly_dates": anomaly_dates[:10],
        "best_day_of_week": best_dow,
        "worst_day_of_week": worst_dow,
        "weekday_avg_sessions": round(weekday_avg, 0),
        "weekend_avg_sessions": round(weekend_avg, 0),
        "new_user_pct": float(new_pct),
        "avg_bounce_rate": round(df["bounce_rate"].mean() * 100, 1),
        "avg_session_duration_sec": round(df["avg_session_dur"].mean(), 0),
        "avg_engagement_rate": round(df["engagement_rate"].mean() * 100, 1),
        "channel_share_pct": channel_share_pct.to_dict(),
        "monthly_sessions": mom[["sessions"]].tail(12).to_dict()["sessions"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. ECOMMERCE ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_ecommerce(ecommerce: pd.DataFrame) -> dict:
    if ecommerce.empty:
        return {}

    df = ecommerce.sort_values("date")

    total_revenue = df["totalRevenue"].sum()
    total_transactions = df["transactions"].sum()
    avg_order_value = total_revenue / total_transactions if total_transactions > 0 else 0
    avg_cvr = df["sessionConversionRate"].mean() * 100

    # 30d vs prior 30d
    recent = df.tail(30)
    prior = df.iloc[-60:-30] if len(df) >= 60 else df.head(30)
    rev_delta = _safe_pct(recent["totalRevenue"].sum(), prior["totalRevenue"].sum())
    txn_delta = _safe_pct(recent["transactions"].sum(), prior["transactions"].sum())
    cvr_delta = _safe_pct(recent["sessionConversionRate"].mean(), prior["sessionConversionRate"].mean())

    # Trends
    rev_trend = _linear_trend(df["totalRevenue"])
    cvr_trend = _linear_trend(df["sessionConversionRate"])
    aov_series = df["totalRevenue"] / df["transactions"].replace(0, np.nan)
    aov_trend = _linear_trend(aov_series)

    # Monthly MoM
    rev_mom = _mom_growth(df, "date", "totalRevenue")
    txn_mom = _mom_growth(df, "date", "transactions")

    # Revenue anomalies
    df["rev_anomaly"] = _detect_anomalies_zscore(df["totalRevenue"])
    rev_anomaly_dates = df[df["rev_anomaly"]]["date"].dt.strftime("%Y-%m-%d").tolist()

    # Funnel metrics
    avg_cart_to_view = df["cartToViewRate"].mean() * 100
    avg_checkout_completion = df["checkoutCompletionRate"].mean() * 100
    avg_add_to_cart = df["itemsAddedToCart"].mean()
    cart_to_purchase_rate = (df["itemsPurchased"].sum() / df["itemsAddedToCart"].sum() * 100) if df["itemsAddedToCart"].sum() > 0 else 0

    # Revenue per day distribution
    rev_percentiles = {
        "p25": round(df["totalRevenue"].quantile(0.25), 2),
        "p50": round(df["totalRevenue"].quantile(0.50), 2),
        "p75": round(df["totalRevenue"].quantile(0.75), 2),
        "p90": round(df["totalRevenue"].quantile(0.90), 2),
    }

    # Seasonality: day-of-week revenue
    df["dow"] = df["date"].dt.day_name()
    dow_rev = df.groupby("dow")["totalRevenue"].mean().round(2)
    best_revenue_dow = dow_rev.idxmax()

    # Monthly revenue table
    monthly_rev = rev_mom[["totalRevenue"]].tail(12).round(2).to_dict()["totalRevenue"]

    return {
        "total_revenue": round(float(total_revenue), 2),
        "total_transactions": int(total_transactions),
        "avg_order_value": round(float(avg_order_value), 2),
        "avg_conversion_rate_pct": round(avg_cvr, 2),
        "revenue_delta_30d": rev_delta,
        "transactions_delta_30d": txn_delta,
        "cvr_delta_30d": cvr_delta,
        "revenue_trend": rev_trend,
        "cvr_trend": cvr_trend,
        "aov_trend": aov_trend,
        "avg_mom_revenue_growth_pct": round(rev_mom["mom_pct"].dropna().mean(), 1),
        "avg_mom_transactions_growth_pct": round(txn_mom["mom_pct"].dropna().mean(), 1),
        "revenue_anomaly_dates": rev_anomaly_dates[:10],
        "avg_cart_to_view_rate_pct": round(avg_cart_to_view, 1),
        "avg_checkout_completion_rate_pct": round(avg_checkout_completion, 1),
        "cart_to_purchase_rate_pct": round(cart_to_purchase_rate, 1),
        "revenue_percentiles": rev_percentiles,
        "best_revenue_day_of_week": best_revenue_dow,
        "monthly_revenue": monthly_rev,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. PRODUCT ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_products(products: pd.DataFrame) -> dict:
    if products.empty:
        return {}

    df = products.copy()

    # Revenue concentration (Pareto)
    pareto_top20 = _pareto_share(df["itemRevenue"], 20)

    # Top 10 by revenue
    top_revenue = df.nlargest(10, "itemRevenue")[
        ["itemName","itemCategory","itemRevenue","itemsPurchased",
         "itemsViewed","cartToViewRate","itemsAddedToCart"]
    ].round(2).to_dict(orient="records")

    # Top 10 by volume
    top_volume = df.nlargest(10, "itemsPurchased")[
        ["itemName","itemCategory","itemsPurchased","itemRevenue"]
    ].round(2).to_dict(orient="records")

    # Conversion funnel per product: view -> add-to-cart -> purchase
    df["view_to_cart_pct"] = (df["itemsAddedToCart"] / df["itemsViewed"].replace(0, np.nan) * 100).round(1)
    df["cart_to_purchase_pct"] = (df["itemsPurchased"] / df["itemsAddedToCart"].replace(0, np.nan) * 100).round(1)

    # Hidden gems: high conversion but low revenue (underexposed products)
    df_valid = df[(df["itemsViewed"] >= 50) & (df["itemRevenue"] > 0)].copy()
    if not df_valid.empty:
        rev_median = df_valid["itemRevenue"].median()
        cvr_median = df_valid["view_to_cart_pct"].median()
        hidden_gems = df_valid[
            (df_valid["itemRevenue"] < rev_median) &
            (df_valid["view_to_cart_pct"] > cvr_median)
        ].nlargest(5, "view_to_cart_pct")[["itemName","itemCategory","itemRevenue","view_to_cart_pct"]].to_dict(orient="records")
    else:
        hidden_gems = []

    # Underperformers: high views but low conversion
    if not df_valid.empty:
        underperformers = df_valid[
            (df_valid["itemsViewed"] > df_valid["itemsViewed"].quantile(0.75)) &
            (df_valid["view_to_cart_pct"] < df_valid["view_to_cart_pct"].quantile(0.25))
        ].nlargest(5, "itemsViewed")[["itemName","itemCategory","itemsViewed","view_to_cart_pct"]].to_dict(orient="records")
    else:
        underperformers = []

    # Category performance
    cat_perf = df.groupby("itemCategory").agg(
        revenue=("itemRevenue", "sum"),
        units=("itemsPurchased", "sum"),
        products=("itemName", "nunique"),
    ).sort_values("revenue", ascending=False).round(2)
    cat_perf["revenue_share_pct"] = (cat_perf["revenue"] / cat_perf["revenue"].sum() * 100).round(1)

    # Product clustering: group by revenue and conversion rate
    cluster_cols = ["itemRevenue", "view_to_cart_pct", "itemsViewed"]
    df_cluster = df_valid[cluster_cols].fillna(0)
    if len(df_cluster) >= 4:
        scaler = StandardScaler()
        scaled = scaler.fit_transform(df_cluster)
        km = KMeans(n_clusters=min(4, len(df_cluster)), random_state=42, n_init=10)
        df_valid = df_valid.copy()
        df_valid["cluster"] = km.fit_predict(scaled)
        cluster_summary = df_valid.groupby("cluster").agg(
            count=("itemName", "count"),
            avg_revenue=("itemRevenue", "mean"),
            avg_cvr=("view_to_cart_pct", "mean"),
            avg_views=("itemsViewed", "mean"),
        ).round(2).to_dict(orient="index")
    else:
        cluster_summary = {}

    return {
        "total_products": len(df),
        "total_product_revenue": round(float(df["itemRevenue"].sum()), 2),
        "pareto_top20_revenue_share_pct": pareto_top20,
        "top_10_by_revenue": top_revenue,
        "top_10_by_volume": top_volume,
        "hidden_gems": hidden_gems,
        "underperformers": underperformers,
        "category_performance": cat_perf.to_dict(orient="index"),
        "product_clusters": cluster_summary,
        "avg_view_to_cart_pct": round(df_valid["view_to_cart_pct"].mean(), 1) if not df_valid.empty else None,
        "avg_cart_to_purchase_pct": round(df_valid["cart_to_purchase_pct"].mean(), 1) if not df_valid.empty else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. DEVICE ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_devices(devices: pd.DataFrame) -> dict:
    if devices.empty:
        return {}

    df = devices.copy()

    # By device category
    device_agg = df.groupby("deviceCategory").agg(
        sessions=("sessions", "sum"),
        users=("totalUsers", "sum"),
        transactions=("transactions", "sum"),
        revenue=("totalRevenue", "sum"),
        avg_cvr=("sessionConversionRate", "mean"),
        avg_bounce=("bounceRate", "mean"),
    ).round(2)
    device_agg["session_share_pct"] = (device_agg["sessions"] / device_agg["sessions"].sum() * 100).round(1)
    device_agg["revenue_share_pct"] = (device_agg["revenue"] / device_agg["revenue"].sum() * 100).round(1)
    device_agg["avg_cvr_pct"] = (device_agg["avg_cvr"] * 100).round(2)
    device_agg["avg_bounce_pct"] = (device_agg["avg_bounce"] * 100).round(1)

    # Revenue per session by device (efficiency)
    device_agg["revenue_per_session"] = (device_agg["revenue"] / device_agg["sessions"]).round(2)

    # Mobile vs Desktop gap
    mobile_cvr = device_agg.loc["mobile", "avg_cvr_pct"] if "mobile" in device_agg.index else None
    desktop_cvr = device_agg.loc["desktop", "avg_cvr_pct"] if "desktop" in device_agg.index else None
    mobile_desktop_cvr_gap = None
    if mobile_cvr and desktop_cvr and desktop_cvr > 0:
        mobile_desktop_cvr_gap = round(((mobile_cvr - desktop_cvr) / desktop_cvr) * 100, 1)

    # Top browsers by revenue
    browser_agg = df.groupby("browser").agg(
        sessions=("sessions", "sum"),
        revenue=("totalRevenue", "sum"),
        avg_cvr=("sessionConversionRate", "mean"),
    ).nlargest(10, "sessions").round(2)
    browser_agg["revenue_share_pct"] = (browser_agg["revenue"] / browser_agg["revenue"].sum() * 100).round(1)

    # OS breakdown
    os_agg = df.groupby("operatingSystem").agg(
        sessions=("sessions", "sum"),
        revenue=("totalRevenue", "sum"),
    ).nlargest(10, "sessions").round(2)

    return {
        "device_summary": device_agg.to_dict(orient="index"),
        "mobile_desktop_cvr_gap_pct": mobile_desktop_cvr_gap,
        "top_browsers": browser_agg.to_dict(orient="index"),
        "top_os": os_agg.to_dict(orient="index"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. ACQUISITION ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_acquisition(acquisition: pd.DataFrame) -> dict:
    if acquisition.empty:
        return {}

    df = acquisition.copy()

    # Channel performance
    channel_agg = df.groupby("sessionDefaultChannelGroup").agg(
        sessions=("sessions", "sum"),
        users=("totalUsers", "sum"),
        new_users=("newUsers", "sum"),
        transactions=("transactions", "sum"),
        revenue=("totalRevenue", "sum"),
        avg_cvr=("sessionConversionRate", "mean"),
        avg_duration=("averageSessionDuration", "mean"),
        avg_bounce=("bounceRate", "mean"),
    ).round(2)
    channel_agg["session_share_pct"] = (channel_agg["sessions"] / channel_agg["sessions"].sum() * 100).round(1)
    channel_agg["revenue_share_pct"] = (channel_agg["revenue"] / channel_agg["revenue"].sum() * 100).round(1)
    channel_agg["avg_cvr_pct"] = (channel_agg["avg_cvr"] * 100).round(2)
    channel_agg["avg_bounce_pct"] = (channel_agg["avg_bounce"] * 100).round(1)
    channel_agg["revenue_per_session"] = (channel_agg["revenue"] / channel_agg["sessions"]).round(2)
    channel_agg = channel_agg.sort_values("revenue", ascending=False)

    # Best channel for CVR vs traffic volume
    top_cvr_channel = channel_agg["avg_cvr_pct"].idxmax()
    top_revenue_channel = channel_agg["revenue"].idxmax()
    top_traffic_channel = channel_agg["sessions"].idxmax()

    # Efficiency: revenue per session (quality of traffic)
    best_rps_channel = channel_agg["revenue_per_session"].idxmax()

    # Over-reliance check: top channel > 60% of sessions
    top_channel_share = channel_agg["session_share_pct"].max()
    over_reliant = bool(top_channel_share > 60)

    # Source/medium top performers
    sm_agg = df.groupby("sessionSourceMedium").agg(
        sessions=("sessions", "sum"),
        revenue=("totalRevenue", "sum"),
        transactions=("transactions", "sum"),
        avg_cvr=("sessionConversionRate", "mean"),
    ).nlargest(15, "revenue").round(2)

    return {
        "channel_summary": channel_agg.to_dict(orient="index"),
        "top_revenue_channel": top_revenue_channel,
        "top_traffic_channel": top_traffic_channel,
        "top_cvr_channel": top_cvr_channel,
        "best_revenue_per_session_channel": best_rps_channel,
        "top_channel_traffic_share_pct": round(float(top_channel_share), 1),
        "over_reliant_on_one_channel": over_reliant,
        "top_source_mediums": sm_agg.to_dict(orient="index"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. GEO ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_geo(geo: pd.DataFrame) -> dict:
    if geo.empty:
        return {}

    df = geo.copy()

    country_agg = df.groupby("country").agg(
        sessions=("sessions", "sum"),
        users=("totalUsers", "sum"),
        transactions=("transactions", "sum"),
        revenue=("totalRevenue", "sum"),
        avg_cvr=("sessionConversionRate", "mean"),
    ).round(2)
    country_agg["revenue_share_pct"] = (country_agg["revenue"] / country_agg["revenue"].sum() * 100).round(1)
    country_agg["revenue_per_user"] = (country_agg["revenue"] / country_agg["users"].replace(0, np.nan)).round(2)
    country_agg["avg_cvr_pct"] = (country_agg["avg_cvr"] * 100).round(2)
    top_countries = country_agg.nlargest(10, "revenue")

    # High value markets (high revenue_per_user but lower traffic — growth opportunity)
    median_users = country_agg["users"].median()
    median_rpu = country_agg["revenue_per_user"].median()
    opportunity_markets = country_agg[
        (country_agg["users"] < median_users) &
        (country_agg["revenue_per_user"] > median_rpu) &
        (country_agg["transactions"] > 0)
    ].nlargest(5, "revenue_per_user")[["sessions","revenue","revenue_per_user","avg_cvr_pct"]]

    return {
        "top_10_countries": top_countries.to_dict(orient="index"),
        "opportunity_markets": opportunity_markets.to_dict(orient="index"),
        "geo_concentration_top5_pct": round(float(top_countries.head(5)["revenue_share_pct"].sum()), 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. LANDING PAGE ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_landing_pages(landing_pages: pd.DataFrame) -> dict:
    if landing_pages.empty:
        return {}

    df = landing_pages.copy()
    df["revenue_per_session"] = (df["totalRevenue"] / df["sessions"].replace(0, np.nan)).round(2)

    top_by_sessions = df.nlargest(10, "sessions")[
        ["landingPage","sessions","bounceRate","engagementRate","sessionConversionRate","totalRevenue"]
    ].round(3).to_dict(orient="records")

    top_by_revenue = df.nlargest(10, "totalRevenue")[
        ["landingPage","sessions","totalRevenue","sessionConversionRate","revenue_per_session"]
    ].round(3).to_dict(orient="records")

    # High traffic but low conversion pages (fix opportunities)
    traffic_q75 = df["sessions"].quantile(0.75)
    cvr_q25 = df["sessionConversionRate"].quantile(0.25)
    fix_candidates = df[
        (df["sessions"] >= traffic_q75) &
        (df["sessionConversionRate"] <= cvr_q25)
    ].nlargest(5, "sessions")[
        ["landingPage","sessions","sessionConversionRate","bounceRate"]
    ].round(3).to_dict(orient="records")

    return {
        "top_10_by_traffic": top_by_sessions,
        "top_10_by_revenue": top_by_revenue,
        "high_traffic_low_cvr_pages": fix_candidates,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. USER TYPE COHORT ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_user_cohorts(user_type_monthly: pd.DataFrame) -> dict:
    if user_type_monthly.empty:
        return {}

    df = user_type_monthly.copy()

    # New vs Returning split
    new_df = df[df["newVsReturning"] == "new"].copy()
    ret_df = df[df["newVsReturning"] == "returning"].copy()

    new_total = new_df["totalUsers"].sum()
    ret_total = ret_df["totalUsers"].sum()
    total = new_total + ret_total

    new_rev = new_df["totalRevenue"].sum()
    ret_rev = ret_df["totalRevenue"].sum()

    new_cvr = new_df["sessionConversionRate"].mean() * 100
    ret_cvr = ret_df["sessionConversionRate"].mean() * 100

    # Revenue per user
    new_rpu = new_rev / new_total if new_total > 0 else 0
    ret_rpu = ret_rev / ret_total if ret_total > 0 else 0

    # Monthly trend: are we retaining better over time?
    ret_df_sorted = ret_df.sort_values("yearMonth")
    retention_trend = _linear_trend(ret_df_sorted["totalUsers"])

    return {
        "new_user_pct": round(new_total / total * 100, 1) if total > 0 else None,
        "returning_user_pct": round(ret_total / total * 100, 1) if total > 0 else None,
        "new_user_cvr_pct": round(float(new_cvr), 2),
        "returning_user_cvr_pct": round(float(ret_cvr), 2),
        "new_user_revenue_per_user": round(float(new_rpu), 2),
        "returning_user_revenue_per_user": round(float(ret_rpu), 2),
        "returning_revenue_share_pct": round(ret_rev / (new_rev + ret_rev) * 100, 1) if (new_rev + ret_rev) > 0 else None,
        "returning_user_trend": retention_trend,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MASTER ANALYSIS RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_all_analyses(data: dict) -> dict:
    print("\nRunning statistical analyses...")

    results = {}

    print("  Analyzing traffic...")
    results["traffic"] = analyze_traffic(data.get("daily_traffic", pd.DataFrame()))

    print("  Analyzing ecommerce KPIs...")
    results["ecommerce"] = analyze_ecommerce(data.get("ecommerce", pd.DataFrame()))

    print("  Analyzing product performance...")
    results["products"] = analyze_products(data.get("products", pd.DataFrame()))

    print("  Analyzing devices...")
    results["devices"] = analyze_devices(data.get("devices", pd.DataFrame()))

    print("  Analyzing acquisition channels...")
    results["acquisition"] = analyze_acquisition(data.get("acquisition", pd.DataFrame()))

    print("  Analyzing geographic performance...")
    results["geo"] = analyze_geo(data.get("geo", pd.DataFrame()))

    print("  Analyzing landing pages...")
    results["landing_pages"] = analyze_landing_pages(data.get("landing_pages", pd.DataFrame()))

    print("  Analyzing user cohorts...")
    results["cohorts"] = analyze_user_cohorts(data.get("user_type_monthly", pd.DataFrame()))

    return results
