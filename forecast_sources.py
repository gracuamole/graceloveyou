"""Forecast boundary: keep provider data separate from Telegram and approval state."""
from dataclasses import dataclass
import os
from run_log import measured

from phase2 import build_blocks, chunks
from recommendations import daylight_intervals, positive


class SourceUnavailable(RuntimeError):
    """A fixed, credential-free error safe to show to the reviewer."""


class ForecastPending(SourceUnavailable):
    """Retry pending; do not send a final failure notice yet."""


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


@measured("forecast_fetch")
def fetch_surfline(target):
    """Reuse the working curl_cffi adapter, with no silent substitute data source."""
    try:
        import main4_pkge_indi as source
        source.cache.clear()
        if os.environ.get('SURF_ATTEMPT_FILE'):
            return protected_forecast(source, target)
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            raise SourceUnavailable('Durable forecast request protection is not configured. No request was made.')
        data = source.fetch_full_forecast(source.SPOT_ID, days=3)
        return prepare_forecast(data, target, source.SPOT_NAME)
    except SourceUnavailable:
        raise
    except Exception:
        # Unofficial endpoints and parsers can fail in many ways. No raw URL/body.
        raise SourceUnavailable('Surfline forecast unavailable or missing required daylight/breaking-surf data. '
                                'No new draft was created; check the next workflow run.') from None


def protected_forecast(source, target):
    from datetime import datetime, timedelta
    from recommendations import BALI
    from fetch_attempt import Attempts, FetchDeferred, CheckpointFailed
    from protected_fetch import preflight
    from forecast_quality import inspect, render
    now = datetime.now(BALI)
    if target != (now + timedelta(days=1)).date().isoformat() or (now.hour, now.minute) < (3, 7):
        raise SourceUnavailable("Protected live fetch requires tomorrow's target after 03:07 Bali time.")
    if os.environ.get('SURF_REQUEST_PROTECTION', 'true').lower() != 'true':
        raise SourceUnavailable('Live forecast fetching is paused; request protection cannot be bypassed.')
    attempt = Attempts(os.environ['SURF_ATTEMPT_FILE'], target,
                       persist=os.environ.get('SURF_ATTEMPT_PERSIST_GIT') == 'true')
    try:
        with attempt.locked():
            source.attempt_context = attempt
            try:
                preflight(source, attempt)
                data = source.fetch_full_forecast(source.SPOT_ID, days=3)
                missing, intervals = inspect(data, target)
                attempt.invalidate(missing)
                if attempt.pending():
                    raise FetchDeferred('Missing forecast data will be retried after its cooldown within the 30-minute window.')
                if 'surf' in missing:
                    attempt.cycle['closed'] = True
                    attempt.save()
                    raise SourceUnavailable('Breaking-surf data is unavailable or incomplete. No new draft was created.')
                if missing and os.environ.get('SURF_INCOMPLETE_DRAFTS', 'true').lower() != 'true':
                    raise SourceUnavailable('Incomplete drafts are disabled; no new draft was created.')
                data.update(attempt.capture_metadata())
                parts, notes = render(data, target, source.SPOT_NAME, missing, intervals)
                data['data_notes'] = notes
                data['missing_inputs'] = sorted(missing)
                attempt.cycle['closed'] = True
                attempt.save()
                return Forecast(target, source.SPOT_NAME, data, parts)
            finally:
                source.attempt_context = None
    except FetchDeferred as error:
        raise ForecastPending(str(error)) from None
    except CheckpointFailed:
        raise SourceUnavailable('Forecast checkpoint failed; requests stopped to preserve request limits.') from None
