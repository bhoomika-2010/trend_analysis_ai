import sys
import os
import pandas as pd
import math
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import json

# --- This block adds the project root to the path ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)
# ---------------------------------------------------

# --- Project-Specific Imports ---
from database.db import get_db_connection
from backend.analytics.forecasting import generate_forecast
from backend.ingest.reddit_connector import fetch_reddit_data
from backend.scripts.google_trends import fetch_and_store_google_trends

from backend.ingest.instagram_connector import fetch_instagram_data
from backend.ingest.twitter_connector import fetch_twitter_data
from backend.ingest.youtube_connector import fetch_youtube_data

# --- Import YOUR new analyzer ---
from backend.processing.analyzer import analyze_and_store_sentiment_and_entities
from backend.scripts.clean_and_aggregate import clean_and_aggregate_google_trends
from backend.analytics.geo_pipeline import enrich_geo_and_aggregate
from serpapi import GoogleSearch
from backend.analytics.influencer_pipeline import run_pipeline as run_influencer_pipeline

SERPAPI_KEY = os.getenv("SERPAPI_KEY")


# --- Flask App Initialization ---
TEMPLATE_FOLDER = os.path.join(PROJECT_ROOT, 'frontend')
STATIC_FOLDER = os.path.join(PROJECT_ROOT, 'frontend')

app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
CORS(app)

@app.route('/')
def index():
    """Serves the main HTML page from the frontend folder."""
    return render_template('index.html')

# --- THIS IS THE MASTER ENDPOINT ---
@app.route('/api/fetch-and-analyze', methods=['POST'])
def fetch_and_analyze():
    data = request.get_json()
    keyword = data.get('keyword')
    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400

    start_date = data.get('startDate')
    end_date = data.get('endDate')

    # --- CACHE LOGIC ---
    if not start_date and not end_date:
        connection = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cache_query = "SELECT created_at FROM trends_cleaned WHERE keyword = %s AND platform = 'Social Media'"
            cursor.execute(cache_query, (keyword,))
            result = cursor.fetchone()

            if result and result.get('created_at'):
                data_age = datetime.now() - result['created_at']
                if data_age < timedelta(hours=24):
                    print(f"--- ✅ CACHE HIT: Fresh data for '{keyword}' already exists. Skipping fetch. ---")
                    return jsonify({"message": "Data is already fresh. Analysis loaded from cache."}), 200

            print(f"--- CACHE MISS: Fetching new data for '{keyword}'... ---")

        except Exception as e:
            print(f"Cache check failed, proceeding with fetch: {e}")
        finally:
            if connection and connection.is_connected():
                cursor.close()
                connection.close()
    else:
        print(f"--- Custom date range requested for '{keyword}'. Bypassing cache. ---")

    print(f"--- Starting REAL-TIME data fetch for keyword: '{keyword}' ---")
    try:
        # ===== STEP 1: FETCH RAW DATA =====
        print("STEP 1: Starting Google Trends fetch...")
        google_success = fetch_and_store_google_trends(keyword, start_date=start_date, end_date=end_date)
        print(f"STEP 1: Google Trends done: {google_success}")

        print("STEP 1: Starting Reddit fetch...")
        reddit_success = fetch_reddit_data(keyword)
        print(f"STEP 1: Reddit done: {reddit_success}")

        print("STEP 1: Starting Instagram fetch...")
        insta_success = fetch_instagram_data(keyword, max_results=30)
        print(f"STEP 1: Instagram done: {insta_success}")

        print("STEP 1: Starting Twitter/X fetch...")
        twitter_success = fetch_twitter_data(keyword, max_results=10)
        print(f"STEP 1: Twitter/X done: {twitter_success}")

        print("STEP 1: Starting YouTube fetch...")
        youtube_success = fetch_youtube_data(keyword, max_results=25)
        print(f"STEP 1: YouTube done: {youtube_success}")

        social_success = any([reddit_success, insta_success, twitter_success, youtube_success])
        print(f"STEP 1 SUMMARY: social_success={social_success}")

        if not social_success:
            print(f"❌ Failed to fetch social media data for '{keyword}'.")
            return jsonify({"error": "Failed to fetch social media data. Try again later."}), 500

        if not google_success:
            print(f"⚠️ Warning: Google Trends fetch failed for '{keyword}'.")

        # ===== STEP 2: ANALYSIS & CLEANING =====
        print("STEP 2: Starting NLP analyzer...")
        sentiment_success = analyze_and_store_sentiment_and_entities(keyword)
        print(f"STEP 2: Analyzer done: {sentiment_success}")

        gtrends_clean_success = True
        if google_success:
            print("STEP 2: Starting Google Trends cleaning...")
            gtrends_clean_success = clean_and_aggregate_google_trends(keyword)
            print(f"STEP 2: Trends cleaning done: {gtrends_clean_success}")

        if not sentiment_success or not gtrends_clean_success:
            print(f"❌ Analysis/Cleaning failed for '{keyword}'.")
            return jsonify({"error": "Data fetched but analysis failed."}), 500

        # ===== STEP 3: INFLUENCER PIPELINE =====
        try:
            print("STEP 3: Running influencer pipeline...")
            inf_result = run_influencer_pipeline(keyword)
            print(f"STEP 3: Influencer pipeline done: {inf_result}")
        except Exception as pipe_error:
            print(f"⚠️ Influencer pipeline error: {pipe_error}")

        # ===== STEP 4: GEO ENRICHMENT (fills geo_metrics) =====
        try:
            print("STEP 4: Running geo enrichment...")
            geo_result = enrich_geo_and_aggregate(keyword, days_back=30)
            print(f"STEP 4: Geo enrichment done: {geo_result}")
        except Exception as geo_err:
            print(f"⚠️ Geo enrichment error: {geo_err}")


        print(f"--- ✅ Successfully fetched and analyzed all data for '{keyword}' ---")
        return jsonify({"message": f"Successfully fetched and analyzed all data for '{keyword}'"}), 200

    except Exception as e:
        print(f"❌ Critical error during fetch: {e}")
        return jsonify({"error": "Internal server error during data fetching."}), 500
# --- This is the "waiter" for the Google Trends / Sentiment Chart ---
@app.route('/api/trends', methods=['GET'])
def get_trends():
    """API endpoint to fetch trend data and aggregated sentiment data."""
    keyword = request.args.get('keyword')
    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400

    print(f"Querying database for /api/trends with keyword: '{keyword}'")
    connection = None
    try:
        connection = get_db_connection()
        if not connection:
             return jsonify({"error": "Database connection failed"}), 500
        
        cursor = connection.cursor(dictionary=True)
        response_data = {"keyword": keyword, "google_trends": [], "social_sentiment": None}
        
        # Get Google Trends data
        gt_query = "SELECT DATE_FORMAT(post_time, '%Y-%m-%d') as date, score FROM raw_data WHERE keyword = %s AND platform = 'Google Trends' ORDER BY post_time ASC"
        cursor.execute(gt_query, (keyword,))
        response_data['google_trends'] = cursor.fetchall()

        # Get Sentiment data FROM THE CLEANED TABLE
        sent_query = "SELECT sentiment_positive_pct, sentiment_negative_pct, sentiment_neutral_pct FROM trends_cleaned WHERE keyword = %s AND platform = 'Social Media'"
        cursor.execute(sent_query, (keyword,))
        sent_result = cursor.fetchone()
        
        if sent_result:
            response_data['social_sentiment'] = {
            "positive": float(sent_result.get('sentiment_positive_pct') or 0),
            "negative": float(sent_result.get('sentiment_negative_pct') or 0),
            "neutral":  float(sent_result.get('sentiment_neutral_pct') or 0)
            }
        else:
    # explicitly return zeroes to make front-end logic simpler
            response_data['social_sentiment'] = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}

        
        return jsonify(response_data)
    except Exception as e:
        print(f"An error occurred in /api/trends: {e}")
        return jsonify({"error": "An internal server error occurred"}), 500
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


@app.route('/api/topics', methods=['GET'])
def get_topics():
    keyword = request.args.get('keyword')
    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = "SELECT topic_id, topic_label, score FROM topics WHERE keyword = %s ORDER BY score DESC"
        cursor.execute(query, (keyword,))
        rows = cursor.fetchall()
        return jsonify({'keyword': keyword, 'topics': rows})
    except Exception as e:
        print(f"Error in /api/topics: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


@app.route('/api/geo/enrich', methods=['POST'])
def api_geo_enrich():
    data = request.get_json() or {}
    keyword = data.get('keyword')
    days_back = data.get('days_back')
    platform = data.get('platform')
    if not keyword:
        return jsonify({'error': 'Keyword is required'}), 400
    try:
        result = enrich_geo_and_aggregate(keyword, days_back=days_back, platform_filter=platform)
        if not result.get('success'):
            return jsonify({'error': result.get('error', 'Unknown error')}), 500
        return jsonify(result)
    except Exception as e:
        print(f"Error in /api/geo/enrich: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/geo/metrics', methods=['GET'])
def get_geo_metrics():
    keyword = request.args.get('keyword')
    level = request.args.get('level', 'country')  # country|region|city
    limit = int(request.args.get('limit', 50))
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    if not keyword:
        return jsonify({'error': 'Keyword is required'}), 400
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Build selection column
        col = 'country' if level == 'country' else ('region' if level == 'region' else 'city')
        query = f"SELECT {col} as location, AVG(metric) as metric_avg, COUNT(*) as row_count FROM geo_metrics WHERE keyword = %s"
        params = [keyword]
        if date_from:
            query += " AND `date` >= %s"
            params.append(date_from)
        if date_to:
            query += " AND `date` <= %s"
            params.append(date_to)
        query += f" GROUP BY {col} ORDER BY metric_avg DESC LIMIT %s"
        params.append(limit)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        return jsonify({'keyword': keyword, 'level': level, 'metrics': rows})
    except Exception as e:
        print(f"Error in /api/geo/metrics: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


@app.route('/api/geo/forecast', methods=['GET'])
def get_geo_forecast():
    keyword = request.args.get('keyword')
    country = request.args.get('country')
    platform = request.args.get('platform')
    if not keyword or not country:
        return jsonify({'error': 'keyword and country are required'}), 400
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        q = "SELECT `date` as date, metric as y FROM geo_metrics WHERE keyword = %s AND country = %s"
        params = [keyword, country]
        if platform:
            q += " AND platform = %s"
            params.append(platform)
        q += " ORDER BY `date` ASC"
        cursor.execute(q, tuple(params))
        history = cursor.fetchall()

        if not history or len(history) < 30:
            return jsonify({'error': 'Not enough regional historical data to forecast.'}), 404

        # Reuse generate_forecast which accepts historical records
        forecast_df = generate_forecast(history)
        if forecast_df is None:
            return jsonify({'error': 'Failed to generate forecast.'}), 500

        import pandas as pd, math
        if isinstance(forecast_df, list):
            forecast_df = pd.DataFrame(forecast_df)
        if 'ds' in forecast_df.columns:
            forecast_df['ds'] = pd.to_datetime(forecast_df['ds'])
        elif 'date' in forecast_df.columns:
            forecast_df.rename(columns={'date': 'ds'}, inplace=True)
            forecast_df['ds'] = pd.to_datetime(forecast_df['ds'])

        history_df = pd.DataFrame(history)
        history_df.rename(columns={'date': 'ds', 'y': 'y'}, inplace=True)
        history_df['ds'] = pd.to_datetime(history_df['ds'])

        full = pd.merge(history_df, forecast_df, on='ds', how='outer')
        full['ds'] = full['ds'].dt.strftime('%Y-%m-%d')
        records = full.to_dict('records')

        def _sanitize(rec):
            for k, v in rec.items():
                if isinstance(v, float) and math.isnan(v):
                    rec[k] = None
            return rec

        return jsonify([_sanitize(r) for r in records])
    except Exception as e:
        print(f"Error in /api/geo/forecast: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


@app.route('/api/geo/top_countries', methods=['GET'])
def get_top_countries_from_trends():
    """Query geo_metrics table (populated by Google Trends via SerpAPI) for top countries.
    Returns JSON: { keyword, top: [{country, value}, ...] }
    Uses ONLY Google Trends data stored in the database, not direct SerpAPI queries.
    """
    keyword = request.args.get('keyword')
    top_n = int(request.args.get('top', 10))
    if not keyword:
        return jsonify({'error': 'keyword is required'}), 400

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor(dictionary=True)
        # Query geo_metrics table for Google Trends data only
        query = ("""
            SELECT country as country, AVG(metric) as value 
            FROM geo_metrics 
            WHERE keyword = %s 
              AND platform = 'Google Trends'
              AND country IS NOT NULL 
            GROUP BY country 
            ORDER BY value DESC 
            LIMIT %s
        """)
        cursor.execute(query, (keyword, top_n))
        rows = cursor.fetchall()
        
        if rows:
            top = [{'country': r.get('country'), 'value': float(r.get('value') or 0)} for r in rows]
            return jsonify({
                'keyword': keyword, 
                'top': top, 
                'source': 'geo_metrics (Google Trends)',
                'note': 'Data from Google Trends stored in database'
            })
        else:
            return jsonify({
                'keyword': keyword, 
                'top': [], 
                'note': 'No geographic data found in database. Run geo enrichment first.'
            })
            
    except Exception as e:
        print(f"Error querying geo_metrics: {e}")
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@app.route('/api/entities', methods=['GET'])
def get_entities():
    keyword = request.args.get('keyword')
    limit = int(request.args.get('limit', 50))
    platform = request.args.get('platform')
    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if platform:
            query = "SELECT entity, entity_type, support FROM entities WHERE keyword = %s AND platform = %s ORDER BY support DESC LIMIT %s"
            cursor.execute(query, (keyword, platform, limit))
        else:
            query = "SELECT entity, entity_type, support FROM entities WHERE keyword = %s ORDER BY support DESC LIMIT %s"
            cursor.execute(query, (keyword, limit))
        rows = cursor.fetchall()
        return jsonify({'keyword': keyword, 'entities': rows})
    except Exception as e:
        print(f"Error in /api/entities: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


@app.route('/api/post_enrichment', methods=['GET'])
def get_post_enrichment():
    keyword = request.args.get('keyword')
    limit = int(request.args.get('limit', 100))
    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = "SELECT platform_post_id, platform, sentiment_compound, assigned_topic, topic_weight, created_at FROM post_enrichment WHERE keyword = %s ORDER BY created_at DESC LIMIT %s"
        cursor.execute(query, (keyword, limit))
        rows = cursor.fetchall()
        return jsonify({'keyword': keyword, 'post_enrichment': rows})
    except Exception as e:
        print(f"Error in /api/post_enrichment: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


@app.route('/api/influencers', methods=['GET'])
def get_influencers():
    keyword = request.args.get('keyword')
    limit = int(request.args.get('limit', 25))

    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Table might not exist
        cursor.execute("SHOW TABLES LIKE 'influencers'")
        if cursor.fetchone() is None:
            return jsonify({'keyword': keyword, 'influencers': []})

        # All platforms now fairly comparable (removed follower bias)
        query = """
            SELECT platform,
                   user_id,
                   username,
                   followers,
                   engagements,
                   influence_score
            FROM influencers
            WHERE keyword = %s
            ORDER BY influence_score DESC
            LIMIT %s
        """
        cursor.execute(query, (keyword, limit))
        rows = cursor.fetchall()

        return jsonify({'keyword': keyword, 'influencers': rows})

    except Exception as e:
        print(f"Error in /api/influencers: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()



@app.route('/api/influencers/refresh', methods=['POST'])
def refresh_influencers():
    """Run the influencer aggregation pipeline for a keyword and return updated top influencers."""
    data = request.get_json() or {}
    keyword = data.get('keyword')
    limit = int(data.get('limit', 20))
    if not keyword:
        return jsonify({'error': 'Keyword is required'}), 400
    try:
        result = run_influencer_pipeline(keyword)
        # After pipeline runs, fetch top influencers
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = "SELECT user_id, username, followers, engagements, influence_score FROM influencers WHERE keyword = %s ORDER BY influence_score DESC LIMIT %s"
        cursor.execute(query, (keyword, limit))
        rows = cursor.fetchall()
        return jsonify({'keyword': keyword, 'pipeline': result, 'influencers': rows})
    except Exception as e:
        print(f"Error in /api/influencers/refresh: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        try:
            if conn and conn.is_connected():
                cursor.close()
                conn.close()
        except Exception:
            pass


@app.route('/api/platforms/comparison', methods=['GET'])
def platforms_comparison():
    """
    Per-platform metrics for a keyword:
      - mentions: Number of posts/content items
      - total_engagement: Sum of all engagement scores (views, likes, comments, etc.)
      - avg_score: Average engagement per post
      - normalized_engagement (0–100): Log-normalized engagement index to account for platform scale differences
      - mentions_share (%): Share of total engagement volume (not just count) - more business-relevant
      - sentiment counts: pos/neg/neu + total

    Improvements:
    1. Share of Conversation now uses total engagement volume instead of row count
    2. Engagement Index uses log-normalization to prevent YouTube (with millions of views) from always winning
       over platforms like Instagram/Reddit (with thousands of likes/upvotes)

    Google Trends is excluded because it is already visualized separately.
    """
    keyword = request.args.get('keyword')
    if not keyword:
        return jsonify({'error': 'Keyword is required'}), 400

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # ---- 1) Base metrics from raw_data ----
        # Calculate total engagement (sum of scores) and average per platform
        base_sql = """
            SELECT
                platform,
                AVG(score) AS avg_score,
                SUM(COALESCE(score, 0)) AS total_engagement,
                COUNT(*)   AS mentions
            FROM raw_data
            WHERE keyword = %s
              AND platform <> 'Google Trends'
            GROUP BY platform
        """
        cursor.execute(base_sql, (keyword,))
        base_rows = cursor.fetchall()

        platforms = {}
        total_engagement_all_platforms = 0.0  # Total engagement across all platforms
        platform_avg_scores = {}  # Store avg_score per platform for normalization

        for r in base_rows:
            platform = r.get('platform') or 'Unknown'
            avg_score = float(r.get('avg_score') or 0.0)
            total_engagement = float(r.get('total_engagement') or 0.0)
            mentions = int(r.get('mentions') or 0)

            platforms[platform] = {
                "platform": platform,
                "avg_score": avg_score,
                "total_engagement": total_engagement,
                "mentions": mentions,
                # sentiment fields (filled later)
                "pos_count": 0,
                "neg_count": 0,
                "neu_count": 0,
                "sent_total": 0,
                # derived fields (filled later)
                "mentions_share": 0.0,
                "normalized_engagement": 0.0,
            }

            total_engagement_all_platforms += total_engagement
            platform_avg_scores[platform] = avg_score

        # ---- 2) Sentiment counts from post_enrichment join ----
        sent_sql = """
            SELECT
                r.platform AS platform,
                SUM(CASE WHEN p.sentiment_compound >  0.05 THEN 1 ELSE 0 END) AS pos_count,
                SUM(CASE WHEN p.sentiment_compound < -0.05 THEN 1 ELSE 0 END) AS neg_count,
                SUM(CASE WHEN p.sentiment_compound BETWEEN -0.05 AND 0.05 THEN 1 ELSE 0 END) AS neu_count,
                COUNT(*) AS total_posts
            FROM post_enrichment p
            JOIN raw_data r
              ON r.platform_post_id = p.platform_post_id
             AND r.keyword          = p.keyword
            WHERE p.keyword = %s
              AND r.platform <> 'Google Trends'
            GROUP BY r.platform
        """
        cursor.execute(sent_sql, (keyword,))
        sent_rows = cursor.fetchall()

        for r in sent_rows:
            platform = r.get('platform') or 'Unknown'
            pos = int(r.get('pos_count') or 0)
            neg = int(r.get('neg_count') or 0)
            neu = int(r.get('neu_count') or 0)
            total = int(r.get('total_posts') or 0)

            if platform not in platforms:
                platforms[platform] = {
                    "platform": platform,
                    "avg_score": 0.0,
                    "mentions": 0,
                    "pos_count": 0,
                    "neg_count": 0,
                    "neu_count": 0,
                    "sent_total": 0,
                    "mentions_share": 0.0,
                    "normalized_engagement": 0.0,
                }

            platforms[platform]["pos_count"] = pos
            platforms[platform]["neg_count"] = neg
            platforms[platform]["neu_count"] = neu
            platforms[platform]["sent_total"] = total

        # ---- 3) Derived fields: mentions_share + normalized_engagement ----
        results = []
        
        # FIX 1: Share of Conversation - Use total engagement volume, not row count
        total_engagement_all_platforms = max(total_engagement_all_platforms, 1.0)  # avoid divide-by-zero
        
        # FIX 2: Engagement Index - Normalize per-platform using log scale to account for different scales
        # YouTube views (millions) vs Instagram likes (thousands) need different treatment
        import math
        
        # Calculate log-scaled scores per platform to compress the range
        log_scores = {}
        for platform, avg_score in platform_avg_scores.items():
            if avg_score > 0:
                # Use log10 to compress large numbers (YouTube views) and small numbers (Instagram likes)
                # Add 1 to avoid log(0), then scale
                log_scores[platform] = math.log10(avg_score + 1)
            else:
                log_scores[platform] = 0.0
        
        # Find min/max of log scores for normalization
        if log_scores:
            min_log = min(log_scores.values())
            max_log = max(log_scores.values())
            log_spread = max_log - min_log if (max_log > min_log) else 1.0
        else:
            log_spread = 1.0
            min_log = 0.0

        for p in platforms.values():
            # FIX 1: Share of conversation based on engagement volume, not count
            p["mentions_share"] = (p["total_engagement"] / total_engagement_all_platforms) * 100.0 if total_engagement_all_platforms > 0 else 0.0

            # FIX 2: Engagement index using log-normalized scores to prevent YouTube from always winning
            platform = p["platform"]
            if platform in log_scores and log_spread > 0:
                # Normalize log score to 0-100 range
                log_score = log_scores[platform]
                p["normalized_engagement"] = ((log_score - min_log) / log_spread) * 100.0
            else:
                # If no valid score, give neutral value
                p["normalized_engagement"] = 50.0

            results.append(p)

        return jsonify({"keyword": keyword, "platforms": results})

    except Exception as e:
        print(f"Error in /api/platforms/comparison: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# --- This is the "waiter" for the Forecast Chart ---
@app.route('/api/trends/forecast', methods=['GET'])
def get_trend_forecast():
    """
    API endpoint to generate and return a 90-day forecast.
    """
    keyword = request.args.get('keyword')
    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400

    print(f"Querying database for /api/trends/forecast with keyword: '{keyword}'")
    connection = None
    try:
        connection = get_db_connection()
        if not connection:
             return jsonify({"error": "Database connection failed"}), 500

        cursor = connection.cursor(dictionary=True)
        
        # We will build a new forecast model later (Day 9)
        # For now, we still use Google Trends data
        query = "SELECT post_time as date, score FROM raw_data WHERE keyword = %s AND platform = 'Google Trends' ORDER BY post_time ASC"
        cursor.execute(query, (keyword,))
        historical_data = cursor.fetchall()

        if not historical_data or len(historical_data) < 30:
            print(f"FORECASTING_WARNING: Not enough historical data for '{keyword}'. Found {len(historical_data)} points.")
            return jsonify({"error": "Not enough historical data to generate a forecast."}), 404

        # Use the imported forecasting function
        forecast_df = generate_forecast(historical_data)
        if forecast_df is None:
            print(f"FORECASTING_WARNING: generate_forecast() returned None for '{keyword}'.")
            return jsonify({"error": "Failed to generate forecast."}), 500

        # `generate_forecast` may return a list-of-dicts (JSON-serializable records)
        # or a pandas DataFrame. Normalize to a DataFrame for merging below.
        if isinstance(forecast_df, list):
            try:
                forecast_df = pd.DataFrame(forecast_df)
            except Exception as e:
                print(f"FORECASTING_ERROR: could not convert forecast records to DataFrame: {e}")
                return jsonify({"error": "Failed to process forecast data."}), 500

        # Ensure the forecast DataFrame has a 'ds' column and datetime dtype
        if 'ds' in forecast_df.columns:
            forecast_df['ds'] = pd.to_datetime(forecast_df['ds'])
        elif 'date' in forecast_df.columns:
            forecast_df.rename(columns={'date': 'ds'}, inplace=True)
            forecast_df['ds'] = pd.to_datetime(forecast_df['ds'])

        history_df = pd.DataFrame(historical_data)
        history_df.rename(columns={'date': 'ds', 'score': 'y'}, inplace=True)
        history_df['ds'] = pd.to_datetime(history_df['ds'])
        
        full_data = pd.merge(history_df, forecast_df, on='ds', how='outer')
        full_data['ds'] = full_data['ds'].dt.strftime('%Y-%m-%d')

        # Convert to records and sanitize NaN -> None so JSON is valid
        records = full_data.to_dict('records')

        def _sanitize_record(rec):
            for k, v in rec.items():
                # Replace NaN (float) with None
                if isinstance(v, float) and math.isnan(v):
                    rec[k] = None
            return rec

        response_data = [_sanitize_record(r) for r in records]
        return jsonify(response_data)
    except Exception as e:
        print(f"An error occurred in /api/trends/forecast: {e}")
        return jsonify({"error": "An internal server error occurred"}), 500
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()



# --- This runs the app ---
if __name__ == '__main__':
    print("Starting Flask server...")
    print("Access the application at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000)
