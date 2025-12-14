"""Google Trends connector using SerpAPI (preferred) or pytrends (fallback)."""
from .connector_base import ConnectorBase
import logging
import os
import requests
logger = logging.getLogger(__name__)

class GoogleTrendsConnector(ConnectorBase):
    def __init__(self):
        super().__init__('Google Trends')
        self.serpapi_key = os.environ.get('SERPAPI_KEY')

    def fetch(self, keyword, start_date=None, end_date=None):
        if self.serpapi_key:
            return self._fetch_serpapi(keyword, start_date, end_date)
        else:
            logger.warning('SERPAPI_KEY not set. Please set your SerpAPI key in the environment.')
            return False

    def _fetch_serpapi(self, keyword, start_date=None, end_date=None):
        # See https://serpapi.com/search-api for docs
        url = 'https://serpapi.com/search.json'
        params = {
            'engine': 'google_trends',
            'q': keyword,
            'api_key': self.serpapi_key,
            'data_type': 'TIMESERIES',
        }
        if start_date:
            params['date_start'] = start_date
        if end_date:
            params['date_end'] = end_date

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            # Parse timeseries data
            timeline = data.get('timeline', [])
            if not timeline:
                logger.warning('No timeline data returned from SerpAPI for keyword %s', keyword)
                return False
            for entry in timeline:
                date = entry.get('date')
                value = entry.get('value')
                self.insert_row(platform_post_id=date, keyword=keyword, post_time=date, author=None,
                                title=None, content=None, score=float(value) if value is not None else None,
                                url=None, raw_json=str(entry))
            logger.info('Inserted %d Google Trends rows for %s', len(timeline), keyword)
            return True
        except Exception as e:
            logger.exception(f'Error fetching Google Trends from SerpAPI for {keyword}: {e}')
            return False

def fetch_google_trends(keyword, start_date=None, end_date=None):
    connector = GoogleTrendsConnector()
    return connector.fetch(keyword, start_date=start_date, end_date=end_date)
    return connector.fetch(keyword, start_date=start_date, end_date=end_date)
