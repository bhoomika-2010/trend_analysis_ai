"""Twitter/X connector scaffold using `tweepy` if available."""
from .connector_base import ConnectorBase
import logging
import os

logger = logging.getLogger(__name__)

try:
    import tweepy
    TWEEPY_AVAILABLE = True
except Exception:
    TWEEPY_AVAILABLE = False


class TwitterConnector(ConnectorBase):
    def __init__(self):
        super().__init__('X')
        self.client = None
        if TWEEPY_AVAILABLE:
            bearer = __import__('os').environ.get('TWITTER_BEARER_TOKEN')
            if bearer:
                try:
                    self.client = tweepy.Client(bearer_token=bearer, wait_on_rate_limit=False)
                except Exception:
                    logger.exception('Failed to initialize tweepy client')

    def fetch(self, keyword, max_results=100):
        if not TWEEPY_AVAILABLE or not self.client:
            logger.warning('tweepy not available or not configured. Set TWITTER_BEARER_TOKEN env var.')
            return False

        try:
            query = f"{keyword} -is:retweet lang:en"
            resp = self.client.search_recent_tweets(
                query=query,
                max_results=min(100, max_results),
                tweet_fields=['created_at', 'author_id', 'public_metrics']
            )
            if not resp or not resp.data:
                logger.info("No tweets returned for keyword %s", keyword)
                return True  # no error, just no data

            for t in resp.data:
                post_time = t.created_at
                content = t.text
                score = None
                metrics = getattr(t, 'public_metrics', None)
                if metrics:
                    score = float(metrics.get('like_count', 0))

                self.insert_row(
                    platform_post_id=str(t.id),
                    keyword=keyword,
                    post_time=post_time,
                    author=str(t.author_id),
                    title=None,
                    content=content,
                    score=score,
                    url=None,
                    raw_json=str(t.data)
                )
            return True

        except tweepy.TooManyRequests as e:
            # This is the rate-limit error
            logger.warning("Twitter rate limit hit for keyword %s: %s", keyword, e)
            # DO NOT sleep – just skip Twitter for now
            return False

        except Exception as e:
            logger.exception(f'Error fetching Twitter/X data: {e}')
            return False


def fetch_twitter_data(keyword, max_results=10):
    conn = TwitterConnector()
    return conn.fetch(keyword, max_results=max_results)
