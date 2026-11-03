"""Forecast boundary: keep provider data separate from Telegram and approval state."""
from dataclasses import dataclass

from phase2 import build_blocks, chunks
from recommendations import daylight_intervals, positive


class SourceUnavailable(RuntimeError):
    """A fixed, credential-free error safe to show to the reviewer."""


class SurflineAccessDenied(SourceUnavailable):
    """A denied request is not a transient network failure to retry immediately."""
    def __init__(self, status):
        if status not in (401, 403):
            raise ValueError('Unexpected access-denial status')
        self.status = status
        super().__init__(f'Surfline denied forecast access (HTTP {status}) after the configured request methods. '
                         'No new draft was created. Run the Surfline forecast check workflow to diagnose '
                         'access from the GitHub runner. Changing LLM settings does not fix forecast access.')


@dataclass
class Forecast:
    date: str
    name: str
    data: dict
    parts: list


def prepare_forecast(data, target, name):
    """Require real breaking-surf coverage; unknown secondary inputs stay explicit."""
    day = next(d for d in data['daily'] if d['date'] == target)
    intervals = daylight_intervals(day)
    for interval in intervals:
        row = interval['row']
        lo, hi = row.get('surf_min_ft'), row.get('surf_max_ft')
        if not (positive(lo) and positive(hi) and lo <= hi):
            raise ValueError('Breaking-surf daylight coverage is incomplete')
    return Forecast(target, name, data, chunks(build_blocks(data, target, name), limit=3000))


def fetch_surfline(target):
    """Reuse the working curl_cffi adapter, with no silent substitute data source."""
    try:
        import main4_pkge_indi as source
        source.cache.clear()
        data = source.fetch_full_forecast(source.SPOT_ID, days=3)
        return prepare_forecast(data, target, source.SPOT_NAME)
    except SourceUnavailable:
        raise
    except Exception:
        # Unofficial endpoints and parsers can fail in many ways. No raw URL/body.
        raise SourceUnavailable('Surfline forecast unavailable or missing required daylight/breaking-surf data. '
                                'No new draft was created; check the next workflow run.') from None
