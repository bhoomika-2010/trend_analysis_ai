import sys
import os
import praw
import datetime
import json

# This import will work because app.py adds the project root to the sys.path
from database.db import insert_raw_row

def fetch_reddit_data(keyword, limit=50):
    """
    Fetches posts from Reddit for a given keyword and stores them.
    Returns True for success or False for failure.
    """
    try:
        reddit = praw.Reddit(
            client_id="jnmodKN-euK2UTjf1EbhgQ",
            client_secret="_R0VO1r7BBfy4iLrHnFmWQYkDVyuAg",
            user_agent="TrendAnalyzer v1.0"
        )
        print(f"✅ Authenticated with Reddit for '{keyword}'.")
    except Exception as e:
        print(f"❌ Reddit auth failed: {e}")
        return False # Return False on failure

    subreddit = reddit.subreddit("all")
    print(f"Fetching up to {limit} posts for '{keyword}'...")
    posts_inserted = 0
    try:
        for submission in subreddit.search(keyword, limit=limit):
            data_to_insert = {
                "platform": "Reddit",
                "platform_post_id": f"reddit_{submission.id}",
                "keyword": keyword,
                "post_time": datetime.datetime.fromtimestamp(submission.created_utc),
                "author": submission.author.name if submission.author else "[deleted]",
                "title": submission.title,
                "content": submission.selftext,
                "score": float(submission.score),
                "url": submission.url,
                "raw_json": json.dumps({
                    "id": submission.id, "title": submission.title, "score": submission.score,
                    "num_comments": submission.num_comments, "subreddit": submission.subreddit.display_name,
                    "created_utc": submission.created_utc
                })
            }
            try:
                insert_raw_row(**data_to_insert)
                posts_inserted += 1
            except Exception as e:
                if "Duplicate entry" not in str(e):
                     print(f"  ❌ Error inserting post {submission.id}: {e}")
                     
    except Exception as e:
        print(f"❌ An error occurred while fetching from Reddit: {e}")
        return False # Return False on failure

    print(f"✅ Reddit fetch complete. Inserted {posts_inserted} new posts for '{keyword}'.")
    return True # Return True on success
