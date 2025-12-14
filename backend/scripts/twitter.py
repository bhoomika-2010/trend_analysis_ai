# backend/scripts/twitter.py

import sys
import os
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time

# Adjust path to import the database function from the project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from database.db import insert_raw_row

# We will use a public Nitter instance. This is the official one.
NITTER_INSTANCE_URL = "https://nitter.net"

def fetch_and_store_twitter_trends(keyword, limit=20):
    """
    Fetches tweets for a given keyword by scraping a Nitter public instance
    and stores them in the 'raw_data' table.
    """
    print(f"Fetching up to {limit} tweets for '{keyword}' from Nitter...")
    
    # URL-encode the keyword to handle spaces and special characters
    from urllib.parse import quote
    search_url = f"{NITTER_INSTANCE_URL}/search?f=tweets&q={quote(keyword)}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.5'
    }

    tweets_inserted = 0
    try:
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()

        # --- DEBUG: Save HTML to a file to see what the script sees ---
        # with open("debug_nitter.html", "w", encoding="utf-8") as f:
        #     f.write(response.text)

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # --- UPDATED SELECTOR ---
        # Nitter's layout changed. The main container for a tweet is now 'timeline-item'.
        tweet_containers = soup.find_all('div', class_='timeline-item')

        if not tweet_containers:
            print("   -> No tweet containers found. The page layout may have changed again or there are no results.")
            return

        for tweet in tweet_containers:
            if tweets_inserted >= limit:
                break

            author_tag = tweet.find('a', class_='username')
            content_tag = tweet.find('div', class_='tweet-content')
            link_tag = tweet.find('a', class_='tweet-link') # This gives the link to the original tweet time
            date_tag = tweet.find('span', class_='tweet-date')

            if not all([author_tag, content_tag, link_tag, date_tag]):
                continue # Skip if essential elements are missing

            author = author_tag.text.strip() if author_tag else 'N/A'
            content = content_tag.text.strip() if content_tag else ''
            
            post_time = datetime.now() # Default value
            if date_tag and date_tag.find('a'):
                post_time_str = date_tag.find('a')['title']
                # Format: 'Oct 8, 2023 · 5:30 PM UTC' -> parse this
                try:
                    post_time = datetime.strptime(post_time_str, '%b %d, %Y · %I:%M %p %Z')
                except ValueError:
                    # Handle other potential date formats if necessary
                    pass

            # Construct URL and unique ID
            tweet_path = link_tag['href']
            url = f"{NITTER_INSTANCE_URL}{tweet_path}"
            platform_post_id = f"twitter_{tweet_path.split('/')[-1].split('#')[0]}"

            # Score is hard to get reliably, let's use 0 for now or find reply count
            score_tag = tweet.find('div', class_='icon-comment')
            score = 0
            if score_tag and score_tag.text.strip().isdigit():
                score = int(score_tag.text.strip())

            data_to_insert = {
                "platform": "Twitter",
                "platform_post_id": platform_post_id,
                "keyword": keyword,
                "post_time": post_time,
                "author": author,
                "title": None,
                "content": content,
                "score": float(score), # Using reply count as score
                "url": url,
                "raw_json": json.dumps({"author": author, "content": content, "replies": score})
            }

            try:
                insert_raw_row(**data_to_insert)
                print(f"   -> Successfully inserted tweet {platform_post_id}")
                tweets_inserted += 1
            except Exception as e:
                if "Duplicate entry" in str(e):
                    pass
                else:
                    print(f"   ❌ Error inserting tweet {platform_post_id}: {e}")
            
            # Be polite to the server
            time.sleep(0.1)

    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to fetch data from Nitter: {e}")
    except Exception as e:
        print(f"❌ An error occurred while parsing Nitter data: {e}")

    print(f"✅ Twitter fetch complete. Inserted {tweets_inserted} new tweets for '{keyword}'.")


if __name__ == "__main__":
    print("--- Fetching Twitter data for 'smartwatch' ---")
    fetch_and_store_twitter_trends("smartwatch")

    print("\n--- Fetching Twitter data for 'AI' ---")
    fetch_and_store_twitter_trends("AI")