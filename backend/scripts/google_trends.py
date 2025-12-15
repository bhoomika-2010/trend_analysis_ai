import sys
import os
import json
from datetime import datetime
from serpapi import GoogleSearch
from database.db import insert_raw_row

# --- CONFIGURATION ---
SERPAPI_KEY = os.getenv("SERPAPI_KEY")


def fetch_and_store_google_trends(keyword, start_date=None, end_date=None):
    print(f"--- Fetching SerpApi Google Trends data for '{keyword}' ---")

    if not SERPAPI_KEY:
        print("❌ SERPAPI_KEY is not set. Configure it in environment variables.")
        return False

    # 1. Build timeframe
    if start_date and end_date:
        timeframe = f"{start_date} {end_date}"
    elif start_date:
        today = datetime.now().strftime('%Y-%m-%d')
        timeframe = f"{start_date} {today}"
    else:
        timeframe = 'today 5-y'

    print(f"Using timeframe: {timeframe}")

    params = {
        "engine": "google_trends",
        "q": keyword,
        "date": timeframe,
        "geo": "US",
        "tz": "-360",
        "api_key": SERPAPI_KEY
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

        if "error" in results:
            print(f"❌ SerpApi Error: {results['error']}")
            return False

        timeline_data = results.get("interest_over_time", {}).get("timeline_data", [])

        if not timeline_data:
            print(f"⚠️ No Google Trends data returned for '{keyword}'.")
            return True

        rows_inserted = 0
        for item in timeline_data:
            score = item.get('values', [{}])[0].get('extracted_value', 0)
            post_time = datetime.fromtimestamp(int(item.get('timestamp')))

            insert_raw_row(
                platform="Google Trends",
                platform_post_id=f"googletrends_{keyword}_{post_time.strftime('%Y%m%d')}",
                keyword=keyword,
                post_time=post_time,
                author="N/A",
                title=f"Google Trends for {keyword}",
                content=f"Interest score: {score}",
                score=float(score),
                url="https://trends.google.com/",
                raw_json=json.dumps(item)
            )
            rows_inserted += 1

        print(f"✅ Google Trends fetch complete. Inserted {rows_inserted} rows.")
        return True

    except Exception as e:
        print(f"❌ Error during SerpApi fetch: {e}")
        return False
