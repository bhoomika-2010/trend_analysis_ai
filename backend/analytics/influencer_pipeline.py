"""
Influencer identification pipeline.

Aggregates authors/users across `raw_data` for a given keyword and computes
an influence score using:
  - engagements (using the `score` column as a proxy for views/likes/etc.)
  - mention count (frequency of posting about the keyword)

Results are upserted into the `influencers` table.
Note: Removed follower counts to avoid platform bias since they're not consistently
available across all platforms (YouTube, Instagram, Twitter, Reddit).
"""

import sys
import os
import json
import logging

# Ensure project root is on sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from database import db  # type: ignore

logger = logging.getLogger(__name__)


def _find_follower_count(obj):
    """
    Recursively search a JSON-like object for likely follower/subscriber counts.
    Looks for keys such as 'followers', 'subscribers', 'follower_count', etc.
    Returns the largest value it finds.
    """
    if obj is None:
        return None

    candidates = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower()
            if key in (
                "subscribercount",
                "subscriber_count",
                "subscribers",
                "followers",
                "followers_count",
                "follower_count",
            ):
                # Try to coerce to int
                try:
                    return int(v)
                except Exception:
                    try:
                        return int(float(v))
                    except Exception:
                        pass
            else:
                val = _find_follower_count(v)
                if val:
                    candidates.append(val)

    elif isinstance(obj, list):
        for item in obj:
            val = _find_follower_count(item)
            if val:
                candidates.append(val)

    return max(candidates) if candidates else None


def _safe_parse_raw_json(raw):
    """
    Best-effort parse of raw_json.
    - If it's already a dict/list, return as-is.
    - If it's a string, try json.loads; if that fails, return None.
    - Otherwise return None.
    """
    if raw is None:
        return None

    if isinstance(raw, (dict, list)):
        return raw

    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, (dict, list)):
                return parsed
            return None
        except Exception:
            return None

    return None


def run_pipeline(keyword, limit=10000):
    """
    Main entry point.
    - Scans raw_data for rows with the given keyword.
    - Aggregates per (platform, author).
    - Extracts follower counts from raw_json when possible.
    - Uses score as a proxy for engagement.
    - Computes a simple influence score and upserts all reasonable authors.
    """
    conn = db.get_db_connection()
    if conn is None:
        return {"success": False, "reason": "db_connect_failed"}

    cursor = conn.cursor(dictionary=True)
    try:
        query = (
            "SELECT platform, author, platform_post_id, score, raw_json "
            "FROM raw_data WHERE keyword = %s LIMIT %s"
        )
        cursor.execute(query, (keyword, int(limit)))
        rows = cursor.fetchall()

        authors = {}  # (platform, author) -> stats dict

        for r in rows:
            platform = (r.get("platform") or "unknown").strip()
            author = (r.get("author") or "unknown").strip()

            # Ignore non-social platforms like Google Trends entirely
            if platform.lower().startswith("google"):
                continue

            # Skip totally useless authors
            if not author or author.lower() in ("unknown", "n/a", "na"):
                continue

            key = (platform, author)
            entry = authors.setdefault(
                key,
                {
                    "mentions": 0,
                    "engagements": 0.0,
                    "followers": 0,
                },
            )

            # Count mentions (number of posts by this author for this keyword)
            entry["mentions"] += 1

            # Use the `score` field as a rough engagement proxy
            score_val = r.get("score")
            if score_val is not None:
                try:
                    entry["engagements"] += max(float(score_val), 0.0)
                except Exception:
                    pass

            # Try to get follower/subscriber counts from raw_json
            raw = r.get("raw_json")
            parsed = _safe_parse_raw_json(raw)
            if parsed is not None:
                f = _find_follower_count(parsed)
                if f is not None and f > entry["followers"]:
                    entry["followers"] = int(f)

        # --- Compute influence score for EVERY remaining author ---
        upsert_count = 0

        for (platform, author), stats in authors.items():
            mentions = int(stats["mentions"])
            engagements = float(stats["engagements"])
            followers = int(stats["followers"]) if stats["followers"] else 0

            # Platform-normalized influence score (no follower bias)
            # Weight: 70% engagement, 30% mentions (consistent across platforms)
            influence_score = engagements * 0.7 + mentions * 30.0

            ins = (
                "INSERT INTO influencers "
                "(keyword, platform, user_id, username, followers, engagements, influence_score) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE "
                "followers = VALUES(followers), "
                "engagements = VALUES(engagements), "
                "influence_score = VALUES(influence_score), "
                "created_at = CURRENT_TIMESTAMP"
            )

            cursor.execute(
                ins,
                (
                    keyword,
                    platform,
                    author,      # user_id
                    author,      # username
                    followers,
                    int(engagements),
                    float(influence_score),
                ),
            )
            upsert_count += 1

        conn.commit()
        logger.info(
            "Influencer pipeline for '%s': authors=%d, upserted=%d",
            keyword,
            len(authors),
            upsert_count,
        )
        return {
            "success": True,
            "authors_processed": len(authors),
            "upserted": upsert_count,
        }

    except Exception as e:
        logger.exception("Influencer pipeline failed: %s", e)
        conn.rollback()
        return {
            "success": False,
            "reason": "db_write_failed",
            "error": str(e),
        }
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--limit", type=int, default=10000)
    args = p.parse_args()
    print(run_pipeline(args.keyword, limit=args.limit))
