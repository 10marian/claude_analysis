"""
GA4 Data Fetcher
Pulls all relevant ecommerce metrics from GA4 Data API v1 (last 12 months).
"""

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
    OrderBy,
)
from google.oauth2 import service_account
import pandas as pd
from datetime import date, timedelta
import json
import os


def _client(credentials_path: str) -> BetaAnalyticsDataClient:
    creds = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    return BetaAnalyticsDataClient(credentials=creds, transport="rest")


def _date_range(months: int = 12) -> DateRange:
    end = date.today() - timedelta(days=1)
    start = date(end.year - (1 if months == 12 else 0), end.month, end.day)
    if months == 12:
        start = end - timedelta(days=365)
    return DateRange(start_date=start.strftime("%Y-%m-%d"), end_date=end.strftime("%Y-%m-%d"))


def _response_to_df(response) -> pd.DataFrame:
    rows = []
    dim_headers = [h.name for h in response.dimension_headers]
    met_headers = [h.name for h in response.metric_headers]
    for row in response.rows:
        record = {}
        for i, dv in enumerate(row.dimension_values):
            record[dim_headers[i]] = dv.value
        for i, mv in enumerate(row.metric_values):
            record[met_headers[i]] = mv.value
        rows.append(record)
    return pd.DataFrame(rows)


# ── 1. Daily traffic overview ─────────────────────────────────────────────────
def fetch_daily_traffic(client, property_id: str) -> pd.DataFrame:
    req = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="date"), Dimension(name="sessionDefaultChannelGroup")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="bounceRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="screenPageViewsPerSession"),
            Metric(name="engagementRate"),
        ],
        date_ranges=[_date_range(12)],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
        limit=100000,
    )
    df = _response_to_df(client.run_report(req))
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    numeric = ["sessions","totalUsers","newUsers","bounceRate",
               "averageSessionDuration","screenPageViewsPerSession","engagementRate"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    return df


# ── 2. Ecommerce overview ─────────────────────────────────────────────────────
def fetch_ecommerce_overview(client, property_id: str) -> pd.DataFrame:
    req = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="date")],
        metrics=[
            Metric(name="transactions"),
            Metric(name="totalRevenue"),
            Metric(name="purchaseRevenue"),
            Metric(name="ecommercePurchases"),
            Metric(name="averagePurchaseRevenue"),
            Metric(name="sessionConversionRate"),
            Metric(name="cartToViewRate"),
            Metric(name="checkoutCompletionRate"),
            Metric(name="itemsAddedToCart"),
            Metric(name="itemsPurchased"),
        ],
        date_ranges=[_date_range(12)],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
        limit=100000,
    )
    df = _response_to_df(client.run_report(req))
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df.iloc[:, 1:] = df.iloc[:, 1:].apply(pd.to_numeric, errors="coerce")
    return df


# ── 3. Product performance ────────────────────────────────────────────────────
def fetch_product_performance(client, property_id: str) -> pd.DataFrame:
    req = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="itemName"), Dimension(name="itemCategory")],
        metrics=[
            Metric(name="itemRevenue"),
            Metric(name="itemsPurchased"),
            Metric(name="itemsViewed"),
            Metric(name="itemsAddedToCart"),
            Metric(name="cartToViewRate"),
            Metric(name="itemPurchaseQuantity"),
            Metric(name="averagePurchaseRevenuePerUser"),
        ],
        date_ranges=[_date_range(12)],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="itemRevenue"), desc=True)],
        limit=200,
    )
    df = _response_to_df(client.run_report(req))
    numeric = ["itemRevenue","itemsPurchased","itemsViewed","itemsAddedToCart",
               "cartToViewRate","itemPurchaseQuantity","averagePurchaseRevenuePerUser"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    return df


# ── 4. Device & platform breakdown ───────────────────────────────────────────
def fetch_device_breakdown(client, property_id: str) -> pd.DataFrame:
    req = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[
            Dimension(name="deviceCategory"),
            Dimension(name="operatingSystem"),
            Dimension(name="browser"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="transactions"),
            Metric(name="totalRevenue"),
            Metric(name="sessionConversionRate"),
            Metric(name="bounceRate"),
        ],
        date_ranges=[_date_range(12)],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=500,
    )
    df = _response_to_df(client.run_report(req))
    numeric = ["sessions","totalUsers","transactions","totalRevenue",
               "sessionConversionRate","bounceRate"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    return df


# ── 5. Acquisition channels ───────────────────────────────────────────────────
def fetch_acquisition(client, property_id: str) -> pd.DataFrame:
    req = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[
            Dimension(name="sessionDefaultChannelGroup"),
            Dimension(name="sessionSourceMedium"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="transactions"),
            Metric(name="totalRevenue"),
            Metric(name="sessionConversionRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="bounceRate"),
        ],
        date_ranges=[_date_range(12)],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalRevenue"), desc=True)],
        limit=200,
    )
    df = _response_to_df(client.run_report(req))
    numeric = ["sessions","totalUsers","newUsers","transactions","totalRevenue",
               "sessionConversionRate","averageSessionDuration","bounceRate"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    return df


# ── 6. Geographic performance ─────────────────────────────────────────────────
def fetch_geo(client, property_id: str) -> pd.DataFrame:
    req = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="country"), Dimension(name="region")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="transactions"),
            Metric(name="totalRevenue"),
            Metric(name="sessionConversionRate"),
        ],
        date_ranges=[_date_range(12)],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalRevenue"), desc=True)],
        limit=200,
    )
    df = _response_to_df(client.run_report(req))
    numeric = ["sessions","totalUsers","transactions","totalRevenue","sessionConversionRate"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    return df


# ── 7. Landing page performance ───────────────────────────────────────────────
def fetch_landing_pages(client, property_id: str) -> pd.DataFrame:
    req = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="landingPage")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="bounceRate"),
            Metric(name="engagementRate"),
            Metric(name="transactions"),
            Metric(name="totalRevenue"),
            Metric(name="sessionConversionRate"),
        ],
        date_ranges=[_date_range(12)],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=100,
    )
    df = _response_to_df(client.run_report(req))
    numeric = ["sessions","totalUsers","bounceRate","engagementRate",
               "transactions","totalRevenue","sessionConversionRate"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    return df


# ── 8. Monthly cohort (new vs returning) ─────────────────────────────────────
def fetch_user_type_monthly(client, property_id: str) -> pd.DataFrame:
    req = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="yearMonth"), Dimension(name="newVsReturning")],
        metrics=[
            Metric(name="totalUsers"),
            Metric(name="sessions"),
            Metric(name="transactions"),
            Metric(name="totalRevenue"),
            Metric(name="sessionConversionRate"),
        ],
        date_ranges=[_date_range(12)],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="yearMonth"))],
        limit=10000,
    )
    df = _response_to_df(client.run_report(req))
    numeric = ["totalUsers","sessions","transactions","totalRevenue","sessionConversionRate"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    return df


# ── Master fetch ──────────────────────────────────────────────────────────────
def fetch_all(credentials_path: str, property_id: str) -> dict[str, pd.DataFrame]:
    print("Connecting to GA4 Data API...")
    client = _client(credentials_path)
    pid = str(property_id)

    datasets = {
        "daily_traffic":    ("Daily traffic by channel",     fetch_daily_traffic),
        "ecommerce":        ("Ecommerce KPIs by day",         fetch_ecommerce_overview),
        "products":         ("Product performance (top 200)", fetch_product_performance),
        "devices":          ("Device & browser breakdown",    fetch_device_breakdown),
        "acquisition":      ("Acquisition channels",          fetch_acquisition),
        "geo":              ("Geographic performance",        fetch_geo),
        "landing_pages":    ("Landing page performance",      fetch_landing_pages),
        "user_type_monthly":("New vs Returning by month",     fetch_user_type_monthly),
    }

    data = {}
    for key, (label, fn) in datasets.items():
        print(f"  Fetching: {label}...")
        try:
            data[key] = fn(client, pid)
            print(f"    -> {len(data[key])} rows")
        except Exception as e:
            print(f"    !! Error fetching {label}: {e}")
            data[key] = pd.DataFrame()

    return data
