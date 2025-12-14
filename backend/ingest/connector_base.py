
# --- .env loader ---
import os
import time
import logging
from typing import Optional
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database.db import insert_raw_row

logger = logging.getLogger(__name__)


class ConnectorBase:
    """Base class for ingestion connectors.

    Implementations should provide a `fetch` method that yields or returns
    normalized rows compatible with `insert_raw_row`.
    """

    def __init__(self, platform_name: str):
        self.platform = platform_name
        # simple per-platform rate limiting (min seconds between requests)
        # default values can be overridden by environment variables RATE_LIMIT_<PLATFORM>
        self._last_request_time = 0
        self.min_interval = self._load_min_interval()

    def throttle(self, seconds: float = 1.0):
        time.sleep(seconds)

    def _load_min_interval(self):
        # platform env var name, e.g., RATE_LIMIT_YOUTUBE
        key = f"RATE_LIMIT_{self.platform.upper().replace(' ', '_')}"
        try:
            val = os.environ.get(key)
            if val:
                return float(val)
        except Exception:
            pass

        # default intervals (seconds) per platform
        defaults = {
            'Google Trends': 86400.0,  # daily by default
            'YouTube': 86400.0,        # default to daily search to protect quota (override for testing)
            'X': 600.0,                # 10 minutes
            'Reddit': 3600.0,          # 1 hour
            'Instagram': 86400.0,      # 1 day
        }
        return defaults.get(self.platform, 60.0)

    def ensure_rate_limit(self):
        """Block until min_interval since last request has passed."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.min_interval:
            to_wait = self.min_interval - elapsed
            logger.info(f"Rate limit: waiting {to_wait:.1f}s for platform {self.platform}")
            time.sleep(to_wait)
        self._last_request_time = time.time()

    def insert_row(self, platform_post_id: str, keyword: str, post_time, author: Optional[str],
                   title: Optional[str], content: Optional[str], score: Optional[float], url: Optional[str], raw_json: Optional[str]):
        # Normalize post_time for MySQL DATETIME compatibility
        try:
            from datetime import datetime
            import re
            if isinstance(post_time, str):
                s = post_time.strip()
                # Convert ISO 'T' to space and strip trailing Z or timezone offsets
                if 'T' in s:
                    s = s.replace('T', ' ')
                # Remove trailing Z
                if s.endswith('Z'):
                    s = s[:-1]
                # Remove timezone offsets like +00:00 or -05:00
                s = re.sub(r'([+-]\d{2}:?\d{2})$', '', s).strip()
                # Optionally ensure it's parseable; if so, format to 'YYYY-MM-DD HH:MM:SS'
                try:
                    dt = datetime.fromisoformat(s)
                    post_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    # fallback to cleaned string
                    post_time = s

            # Ensure raw_json is valid JSON text for MySQL JSON columns
            try:
                import json as _json
                if raw_json is None:
                    raw_json_val = None
                elif isinstance(raw_json, (dict, list)):
                    raw_json_val = _json.dumps(raw_json)
                elif isinstance(raw_json, str):
                    try:
                        # validate if it's already JSON
                        _json.loads(raw_json)
                        raw_json_val = raw_json
                    except Exception:
                        # store as JSON string
                        raw_json_val = _json.dumps(raw_json)
                else:
                    raw_json_val = _json.dumps(raw_json)
            except Exception:
                raw_json_val = None

            insert_raw_row(self.platform, platform_post_id, keyword, post_time, author, title, content, score, url, raw_json_val)
        except Exception as e:
            logger.exception(f"Failed to insert row for {self.platform}: {e}")
