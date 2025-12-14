"""Reddit connector scaffold using `praw` if available."""
from .connector_base import ConnectorBase
import logging
logger = logging.getLogger(__name__)

try:
    import praw
    PRAW_AVAILABLE = True
except Exception:
    PRAW_AVAILABLE = False


class RedditConnector(ConnectorBase):
    def __init__(self):
        super().__init__('Reddit')
        self.reddit = None
        if PRAW_AVAILABLE:
            # Expect credentials in env vars
            client_id = __import__('os').environ.get('REDDIT_CLIENT_ID')
            client_secret = __import__('os').environ.get('REDDIT_CLIENT_SECRET')
            user_agent = __import__('os').environ.get('REDDIT_USER_AGENT', 'trend-analysis-bot')
            if client_id and client_secret:
                try:
                    self.reddit = praw.Reddit(client_id=client_id, client_secret=client_secret, user_agent=user_agent)
                except Exception:
                    logger.exception('Failed to initialize PRAW')

    def fetch(self, keyword, limit=100):
        if not PRAW_AVAILABLE or not self.reddit:
            logger.warning('praw not available or not configured. Install PRAW and set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET.')
            return False

        try:
            for submission in self.reddit.subreddit('all').search(keyword, limit=limit):
                post_time = __import__('datetime').datetime.fromtimestamp(submission.created_utc)
                content = submission.title + '\n' + (submission.selftext or '')
                self.insert_row(platform_post_id=submission.id, keyword=keyword, post_time=post_time,
                                author=str(submission.author), title=submission.title, content=content,
                                score=float(submission.score) if submission.score is not None else None,
                                url=submission.url, raw_json=str({'id': submission.id}))
            return True
        except Exception as e:
            logger.exception(f'Error fetching Reddit data: {e}')
            return False


def fetch_reddit_data(keyword, limit=100):
    conn = RedditConnector()
    return conn.fetch(keyword, limit=limit)
