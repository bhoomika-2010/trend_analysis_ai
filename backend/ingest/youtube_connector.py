"""YouTube connector using simple REST API calls with requests."""
from .connector_base import ConnectorBase
import logging
import os
import requests
import time

logger = logging.getLogger(__name__)


class YouTubeConnector(ConnectorBase):
    def __init__(self):
        super().__init__('YouTube')
        self.api_key = os.environ.get('YOUTUBE_API_KEY')
        if self.api_key:
            print("[YouTubeConnector] YOUTUBE_API_KEY present?: True")
        else:
            print("[YouTubeConnector] YOUTUBE_API_KEY present?: False")

    def fetch(self, keyword, max_results=25):
        """
        Fetch YouTube videos for a keyword and store them into raw_data.
        Uses ONLY requests (no googleapiclient). Includes verbose debug logs.
        """
        if not self.api_key:
            logger.warning('YOUTUBE_API_KEY not configured. Set YOUTUBE_API_KEY in environment or .env')
            return False

        try:
            # --- 1) SEARCH: get video IDs ---
            search_url = 'https://www.googleapis.com/youtube/v3/search'
            max_results = min(25, max_results)

            search_params = {
                'part': 'snippet',
                'q': keyword,
                'type': 'video',
                'maxResults': max_results,
                'key': self.api_key
            }

            print(f"[YouTubeConnector] Starting REST search for keyword='{keyword}'")
            search_resp = requests.get(search_url, params=search_params, timeout=30)
            print(f"[YouTubeConnector] search.status_code: {search_resp.status_code}")

            search_resp.raise_for_status()
            search_data = search_resp.json()

            # Debug: tiny snippet
            print("[YouTubeConnector] search.raw_response snippet:",
                  str(search_data)[:400])

            items = search_data.get('items', [])
            if not items:
                print("[YouTubeConnector] No YouTube search results.")
                return False

            video_ids = [
                it['id']['videoId']
                for it in items
                if it.get('id') and it['id'].get('videoId')
            ]
            print(f"[YouTubeConnector] Found {len(video_ids)} video IDs")

            if not video_ids:
                return False

            # --- 2) VIDEOS: get stats for those IDs ---
            vids_url = 'https://www.googleapis.com/youtube/v3/videos'
            vids_params = {
                'part': 'snippet,statistics',
                'id': ','.join(video_ids),
                'key': self.api_key
            }

            print(f"[YouTubeConnector] Requesting videos.list for {len(video_ids)} IDs...")
            vids_resp = requests.get(vids_url, params=vids_params, timeout=30)
            print(f"[YouTubeConnector] videos.status_code: {vids_resp.status_code}")

            vids_resp.raise_for_status()
            vdata = vids_resp.json()
            print("[YouTubeConnector] videos.raw_response snippet:",
                  str(vdata)[:400])

            items = vdata.get('items', [])
            if not items:
                print("[YouTubeConnector] No video items returned in videos.list.")
                return False

            inserted = 0
            for v in items:
                vid = v.get('id')
                snippet = v.get('snippet', {})
                stats = v.get('statistics', {})

                post_time = snippet.get('publishedAt')  # ISO string
                title = snippet.get('title')
                description = snippet.get('description')
                author = snippet.get('channelTitle')

                score = None
                if stats and stats.get('viewCount'):
                    try:
                        score = float(stats.get('viewCount'))
                    except Exception:
                        score = None

                # small sleep to be nice to DB
                time.sleep(0.05)

                self.insert_row(
                    platform_post_id=vid,
                    keyword=keyword,
                    post_time=post_time,
                    author=author,
                    title=title,
                    content=description,
                    score=score,
                    url=f"https://www.youtube.com/watch?v={vid}",
                    raw_json=str(v)
                )
                inserted += 1

            print(f"[YouTubeConnector] Inserted {inserted} YouTube rows for '{keyword}'")
            return True

        except Exception as e:
            logger.exception(f'Error fetching YouTube data: {e}')
            print(f"[YouTubeConnector] Exception in fetch(): {e}")
            return False


def fetch_youtube_data(keyword, max_results=25):
    conn = YouTubeConnector()
    return conn.fetch(keyword, max_results=max_results)
