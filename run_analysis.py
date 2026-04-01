#!/usr/bin/env python3
"""
GA4 Ecommerce Analysis — Main Runner
Usage:
    python run_analysis.py --property-id 123456789 --credentials path/to/key.json
    python run_analysis.py --property-id 123456789  # looks for sa_key.json in current dir
"""

import argparse
import sys
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="GA4 Ecommerce Statistical Analysis & Growth Insights"
    )
    parser.add_argument(
        "--property-id", "-p",
        required=True,
        help="GA4 Property ID (numeric, e.g. 320145678)",
    )
    parser.add_argument(
        "--credentials", "-c",
        default=None,
        help="Path to service account JSON key file (default: looks for sa_key.json in current dir)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="reports",
        help="Directory for output reports (default: reports/)",
    )
    parser.add_argument(
        "--no-excel",
        action="store_true",
        help="Skip Excel report generation",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Skip JSON results file",
    )
    args = parser.parse_args()

    # Resolve credentials path
    creds_path = args.credentials
    if creds_path is None:
        # Try common defaults
        for candidate in ["sa_key.json", "credentials.json", "service_account.json"]:
            if Path(candidate).exists():
                creds_path = candidate
                break
    if creds_path is None:
        print("ERROR: No credentials file found.")
        print("  Provide --credentials /path/to/key.json")
        print("  Or place your service account key as sa_key.json in the current directory.")
        sys.exit(1)
    if not Path(creds_path).exists():
        print(f"ERROR: Credentials file not found: {creds_path}")
        sys.exit(1)

    print(f"Credentials: {creds_path}")
    print(f"Property ID: {args.property_id}")
    print(f"Output dir:  {args.output_dir}")
    print()

    # Import here so missing deps show clean errors
    try:
        from ga4_fetcher import fetch_all
        from ga4_analysis import run_all_analyses
        from ga4_report import print_report, generate_growth_insights, save_excel_report, save_json_results
    except ImportError as e:
        print(f"ERROR: Missing dependency — {e}")
        print("Run: pip install -r requirements.txt")
        sys.exit(1)

    # Step 1: Fetch data
    data = fetch_all(creds_path, args.property_id)

    # Step 2: Analyse
    results = run_all_analyses(data)

    # Step 3: Generate insights
    print("\nGenerating growth insights...")
    insights = generate_growth_insights(results)

    # Step 4: Print report to terminal
    print_report(results, insights, args.property_id)

    # Step 5: Save outputs
    if not args.no_excel:
        try:
            save_excel_report(data, results, insights, args.output_dir)
        except Exception as e:
            print(f"Warning: Could not save Excel report: {e}")

    if not args.no_json:
        try:
            save_json_results(results, insights, args.output_dir)
        except Exception as e:
            print(f"Warning: Could not save JSON results: {e}")

    print(f"\nDone. {len(insights)} growth insights generated.")


if __name__ == "__main__":
    main()
