# GA4 Ecommerce Analysis — Setup Guide

## What This Does

Connects to your GA4 property, pulls 12 months of ecommerce data via the Google Analytics Data API, applies statistical methods, and prints a rich report with prioritized growth insights.

**Analyses performed:**
- Traffic trends (OLS regression, anomaly detection, day-of-week patterns)
- Ecommerce KPIs (revenue trends, CVR, AOV, funnel analysis)
- Product performance (Pareto analysis, clustering, hidden gems, underperformers)
- Device & browser breakdown (mobile/desktop CVR gap)
- Acquisition channel analysis (revenue per session, over-reliance detection)
- Geographic performance (opportunity market detection)
- Landing page analysis (high-traffic / low-CVR identification)
- New vs Returning user cohort analysis (LTV indicators)

---

## Prerequisites

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create a Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select or create a project
3. Enable the **Google Analytics Data API**:
   - APIs & Services → Library → search "Google Analytics Data API" → Enable
4. Create a service account:
   - APIs & Services → Credentials → Create Credentials → Service Account
   - Give it a name (e.g. `ga4-analysis`)
   - Click Done
5. Create a JSON key:
   - Click on the service account → Keys tab → Add Key → Create new key → JSON
   - Download the `.json` file

### 3. Grant Service Account Access to GA4

1. Open [Google Analytics](https://analytics.google.com/)
2. Go to Admin → Property → Property Access Management
3. Click **+** → Add users
4. Enter the service account email (looks like `name@project.iam.gserviceaccount.com`)
5. Set role to **Viewer** → Add

### 4. Get Your GA4 Property ID

- In GA4: Admin → Property Settings → **Property ID** (top right, numeric)

---

## Running the Analysis

Place your JSON key file in this directory as `sa_key.json`, then:

```bash
python run_analysis.py --property-id YOUR_PROPERTY_ID
```

Or specify the credentials path explicitly:

```bash
python run_analysis.py --property-id 320145678 --credentials /path/to/key.json
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--property-id` / `-p` | required | GA4 Property ID |
| `--credentials` / `-c` | `sa_key.json` | Path to service account JSON |
| `--output-dir` / `-o` | `reports/` | Output directory |
| `--no-excel` | off | Skip Excel report |
| `--no-json` | off | Skip JSON output |

---

## Output

- **Terminal**: Rich formatted report with tables and color-coded insights
- `reports/ga4_report_YYYYMMDD_HHMM.xlsx` — Excel workbook with all raw data + insight sheet
- `reports/ga4_analysis_YYYYMMDD_HHMM.json` — Full results as JSON

---

## File Structure

```
claude_analysis/
├── run_analysis.py       ← Main entry point
├── ga4_fetcher.py        ← GA4 API data fetching (8 report types)
├── ga4_analysis.py       ← Statistical analysis engine
├── ga4_report.py         ← Report generation + insight synthesis
├── requirements.txt      ← Python dependencies
├── sa_key.json           ← Your service account key (place here)
└── reports/              ← Generated output files
```
