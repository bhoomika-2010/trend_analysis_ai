import sys
import os
import re
import spacy
from collections import Counter
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Add the project root to the sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(PROJECT_ROOT)

from database.db import get_db_connection, insert_cleaned_trend

# --- 1. Load spaCy (for Entities) ---
try:
    nlp = spacy.load("en_core_web_sm")
except IOError:
    print("❌ spaCy model 'en_core_web_sm' not found.")
    print("Please run: python -m spacy download en_core_web_sm")
    sys.exit(1)

# --- 2. Load VADER (for Sentiment) ---
vader_analyzer = SentimentIntensityAnalyzer()


def clean_text(text):
    """
    Simple text cleaning.
    """
    if not text:
        return ""
    text = re.sub(r"http\S+|www\S+|https\S+", '', text, flags=re.MULTILINE)
    text = re.sub(r'\@\w+|\#','', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def analyze_and_store_sentiment_and_entities(keyword):
    """
    Analyze sentiment and entities across ALL social platforms
    and store per post sentiment + aggregated platform sentiment.
    Also stores a combined 'Social Media' row for the UI pie chart.
    """
    print(f"--- Starting NLP analysis for keyword: '{keyword}' ---")

    connection = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Fetch all platforms (not just Reddit)
        query = """
            SELECT platform, platform_post_id, content, score
            FROM raw_data
            WHERE keyword = %s
        """
        cursor.execute(query, (keyword,))
        posts = cursor.fetchall()

        if not posts:
            print(f"No posts found for '{keyword}'. Skipping analysis.")
            return True

        print(f"Found {len(posts)} posts to analyze...")

        platform_stats = {}
        entity_counter = Counter()

        # 👉 NEW: overall social media stats
        overall_social = {"pos": 0, "neg": 0, "neu": 0, "total": 0}

        for post in posts:
            raw_text = post["content"] or ""
            platform = post["platform"]
            post_id = post["platform_post_id"]

            clean = clean_text(raw_text)
            if not clean:
                sentiment_score = 0  # neutral
            else:
                vader_result = vader_analyzer.polarity_scores(clean)
                sentiment_score = vader_result["compound"]

            # Store per-post sentiment in post_enrichment
            cursor.execute("""
                INSERT INTO post_enrichment (platform_post_id, keyword, platform, sentiment_compound)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE sentiment_compound = VALUES(sentiment_compound);
            """, (post_id, keyword, platform, sentiment_score))

            # Track stats per platform
            if platform not in platform_stats:
                platform_stats[platform] = {"pos": 0, "neg": 0, "neu": 0, "total": 0}

            platform_stats[platform]["total"] += 1
            if sentiment_score >= 0.05:
                platform_stats[platform]["pos"] += 1
            elif sentiment_score <= -0.05:
                platform_stats[platform]["neg"] += 1
            else:
                platform_stats[platform]["neu"] += 1

            # 👉 NEW: update overall social stats (skip Google Trends)
            if platform != "Google Trends":
                overall_social["total"] += 1
                if sentiment_score >= 0.05:
                    overall_social["pos"] += 1
                elif sentiment_score <= -0.05:
                    overall_social["neg"] += 1
                else:
                    overall_social["neu"] += 1

            # Entity extraction
            doc = nlp(clean)
            for ent in doc.ents:
                if ent.label_ in ["PERSON", "ORG", "GPE", "PRODUCT"]:
                    entity_counter[(ent.text.strip().lower(), ent.label_)] += 1

        # Insert aggregated sentiment per platform
        for platform, stats in platform_stats.items():
            total = stats["total"]
            pos = (stats["pos"] / total) * 100 if total > 0 else 0
            neg = (stats["neg"] / total) * 100 if total > 0 else 0
            neu = (stats["neu"] / total) * 100 if total > 0 else 0

            cursor.execute("""
                INSERT INTO trends_cleaned (keyword, platform, sentiment_positive_pct, sentiment_negative_pct, sentiment_neutral_pct)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    sentiment_positive_pct = VALUES(sentiment_positive_pct),
                    sentiment_negative_pct = VALUES(sentiment_negative_pct),
                    sentiment_neutral_pct = VALUES(sentiment_neutral_pct),
                    created_at = CURRENT_TIMESTAMP;
            """, (keyword, platform, pos, neg, neu))

        # 👉 NEW: insert combined 'Social Media' row for the pie chart
        if overall_social["total"] > 0:
            total = overall_social["total"]
            pos = (overall_social["pos"] / total) * 100
            neg = (overall_social["neg"] / total) * 100
            neu = (overall_social["neu"] / total) * 100

            cursor.execute("""
                INSERT INTO trends_cleaned (keyword, platform, sentiment_positive_pct, sentiment_negative_pct, sentiment_neutral_pct)
                VALUES (%s, 'Social Media', %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    sentiment_positive_pct = VALUES(sentiment_positive_pct),
                    sentiment_negative_pct = VALUES(sentiment_negative_pct),
                    sentiment_neutral_pct = VALUES(sentiment_neutral_pct),
                    created_at = CURRENT_TIMESTAMP;
            """, (keyword, pos, neg, neu))

        connection.commit()

        print("\n📊 Sentiment Aggregation per Platform:")
        for platform, stats in platform_stats.items():
            total = stats["total"]
            print(f"  - {platform}: {stats['pos']}⬆  {stats['neg']}⬇  {stats['neu']}😐 out of {total} posts")

        # 👉 Optional: print combined social
        if overall_social["total"] > 0:
            print(f"\n🌐 Combined Social Media: "
                  f"{overall_social['pos']}⬆  {overall_social['neg']}⬇  {overall_social['neu']}😐 "
                  f"out of {overall_social['total']} posts")

        # Store entities
        if entity_counter:
            print("\n🏷 Top Entities Found:")
            for (text, label), count in entity_counter.most_common(5):
                print(f"  {text} ({label}): {count}")

                cursor.execute("""
                    INSERT INTO entities (keyword, platform, entity, entity_type, support)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE support = support + VALUES(support)
                """, (keyword, 'All Platforms', text, label, count))

        connection.commit()
        return True

    except Exception as e:
        print(f"❌ NLP analysis error for '{keyword}': {e}")
        return False

    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


if __name__ == "__main__":
    test_keyword = "webscraping"   # Replace with any keyword you've already ingested
    print("🚀 Running sentiment analysis NLP pipeline...")
    result = analyze_and_store_sentiment_and_entities(test_keyword)
    print("✔ Done:", result)
