"""Instagram connector using Apify Instagram Hashtag Scraper."""

from .connector_base import ConnectorBase
import logging
import os
import requests

logger = logging.getLogger(__name__)


class InstagramConnector(ConnectorBase):
    def __init__(self):
        super().__init__("Instagram")
        self.apify_token = (os.getenv("APIFY_TOKEN") or "").strip()
        # IMPORTANT: actor id is just "apify~instagram-hashtag-scraper", not a full URL
        self.actor_id = (os.getenv("APIFY_INSTAGRAM_ACTOR_ID") or "apify~instagram-hashtag-scraper").strip()

        if not self.apify_token:
            logger.warning("APIFY_TOKEN is not set. Instagram connector will not work.")

    def _keyword_to_hashtags(self, keyword: str):
        """
        Very simple mapping from a free-text keyword to hashtags.
        Example: 'Maybelline New York' -> ['maybellinenewyork', 'maybelline', 'newyork']
        You can improve this later.
        """
        if not keyword:
            return []

        base = keyword.strip().lower()
        no_space = "".join(base.split())

        tags = set()
        if no_space:
            tags.add(no_space)

        # split into words and add them if they are not tiny
        parts = [p for p in base.split() if len(p) > 2]
        for p in parts:
            tags.add(p)

        return list(tags)

    def fetch(self, keyword, max_results=50):
        """
        Fetch Instagram posts for hashtags derived from `keyword` using Apify.

        Returns True if any rows were inserted, False otherwise.
        """
        if not self.apify_token:
            logger.error("APIFY_TOKEN not configured; cannot fetch Instagram data.")
            return False

        hashtags = self._keyword_to_hashtags(keyword)
        if not hashtags:
            logger.warning("No hashtags derived from keyword '%s'", keyword)
            return False

        # respect per-platform throttling
        self.ensure_rate_limit()

        url = f"https://api.apify.com/v2/acts/{self.actor_id}/run-sync-get-dataset-items"
        params = {"token": self.apify_token}
        payload = {
            "hashtags": hashtags,
            "resultsLimit": int(max_results),
        }

        logger.info("Calling Apify Instagram actor %s for hashtags=%s (limit=%s)",
                    self.actor_id, hashtags, max_results)

        try:
            resp = requests.post(url, params=params, json=payload, timeout=60)
            resp.raise_for_status()
            items = resp.json()

            if not isinstance(items, list):
                logger.warning("Unexpected Instagram response format: %s", type(items))
                return False

            inserted_any = False
            for item in items:
                try:
                    self._process_item(keyword, item)
                    inserted_any = True
                except Exception:
                    logger.exception("Failed to process Instagram item")

            return inserted_any

        except requests.RequestException as e:
            logger.error("Error calling Apify Instagram actor: %s", e)
            return False

    def _process_item(self, keyword: str, item: dict):
        """
        Map a single Apify Instagram item into our raw_data schema and insert it.
        """
        # Unique post ID
        platform_post_id = (
            str(item.get("id"))
            or str(item.get("shortCode"))
            or item.get("url")
            or "unknown"
        )

        # Basic fields
        author = item.get("ownerUsername") or item.get("username")
        caption = item.get("caption") or ""
        url = item.get("url") or (
            f"https://www.instagram.com/p/{item.get('shortCode')}/" if item.get("shortCode") else None
        )

        likes = item.get("likesCount") or 0
        comments = item.get("commentsCount") or 0
        # simple engagement score
        score = float(likes + comments)

        post_time = item.get("timestamp") or ""

        if caption:
            title = caption[:80]
        elif author:
            title = f"Instagram post by {author}"
        else:
            title = "Instagram post"

        # This calls ConnectorBase.insert_row → database.insert_raw_row
        self.insert_row(
            platform_post_id=platform_post_id,
            keyword=keyword,
            post_time=post_time,
            author=author,
            title=title,
            content=caption,
            score=score,
            url=url,
            raw_json=item,
        )


def fetch_instagram_data(keyword, max_results=50):
    conn = InstagramConnector()
    return conn.fetch(keyword, max_results=max_results)
