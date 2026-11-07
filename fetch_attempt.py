"""Durable request budgets and exact-request response cache. No credentials stored."""
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse, parse_qsl

from run_log import log_event

WINDOW = 30 * 60
RETRY_DELAY = 5 * 60
ENDPOINTS = {'conditions', 'rating', 'surf', 'swells', 'wind', 'tides', 'energy', 'weather'}
PARAMS = {'spotId', 'days', 'intervalHours', 'cacheEnabled', 'units', 'units[waveHeight]', 'units[swellHeight]', 'units[windSpeed]', 'units[tideHeight]', 'units[temperature]'}


class FetchDeferred(RuntimeError):
    """A bounded retry is pending; the worker will wake another run."""


class CheckpointFailed(RuntimeError):
    """Stop all requests when durable persistence is unavailable."""


def request_spec(url, params=None):
    parsed = urlparse(url)
    endpoint = parsed.path.rsplit('/', 1)[-1]
    query = dict(parse_qsl(parsed.query))
    if params:
        query.update({k: str(v) for k, v in params.items()})
    if endpoint not in ENDPOINTS or set(query) - PARAMS:
        raise ValueError('Unrecognised forecast request shape')
    return {'endpoint': endpoint, 'params': dict(sorted(query.items()))}


def request_key(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def retry_after(value, now):
    try:
        return max(0, float(value))
    except (ValueError, TypeError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return 0


class Attempts:
    def __init__(self, path, target, persist=False, clock=time.time, sleep=time.sleep):
        self.path, self.target, self.persist = Path(path), target, persist
        self.clock, self.sleep = clock, sleep
        self.data = None
        self.used = {}
        self.missing = set()

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            now = self.clock()
            if self.path.exists():
                self.data = json.loads(self.path.read_text())
                if self.data.get('version') != 1 or not isinstance(self.data.get('cycles'), dict):
                    raise CheckpointFailed('Invalid fetch state; refusing to reset request budgets')
            else:
                self.data = {'version': 1, 'cycles': {}, 'cooldowns': {}, 'last_request': 0}
            self.data['cycles'] = {k: v for k, v in self.data['cycles'].items()
                                   if v['started'] >= now - 7 * 86400 or k == self.target}
            for k, cycle in self.data['cycles'].items():
                if k != self.target:
                    cycle['responses'] = {}  # Only the active daily cycle can reuse payloads.
            self.data['cooldowns'] = {k: v for k, v in self.data['cooldowns'].items()
                                      if v['until'] > now}
            self.cycle = self.data['cycles'].setdefault(self.target, {
                'started': now, 'counts': {}, 'responses': {}, 'requests': {}, 'failed': {}, 'closed': False})
            try:
                yield self
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def save(self):
        # Reuse the fsync/atomic-write primitive without an import cycle at module load.
        from review_bot import atomic_state_write
        try:
            atomic_state_write(self.path, self.data)
            if self.persist:
                root = str(self.path.parent)
                subprocess.run(['git', '-C', root, 'add', self.path.name], check=True, capture_output=True)
                diff = subprocess.run(['git', '-C', root, 'diff', '--cached', '--quiet', '--', self.path.name],
                                      capture_output=True)
                if diff.returncode not in (0, 1):
                    raise RuntimeError('Unable to inspect checkpoint')
                if diff.returncode:
                    subprocess.run(['git', '-C', root, 'commit', '-m', 'Checkpoint forecast requests',
                                    '--', self.path.name], check=True, capture_output=True)
                # Also confirms a previous local commit was pushed before another request.
                subprocess.run(['git', '-C', root, 'push', 'origin', 'HEAD:review-state'],
                               check=True, capture_output=True)
        except Exception:
            raise CheckpointFailed('Forecast checkpoint failed; no further requests allowed') from None

    def family(self, spec):
        return spec['params'].get('spotId', '') + ':' + spec['endpoint']

    def cached(self, spec):
        entry = self.cycle['responses'].get(request_key(spec))
        if entry and 0 <= self.clock() - entry['captured'] <= WINDOW:
            self.used[request_key(spec)] = entry
            log_event('surfline_endpoint', endpoint=spec['endpoint'], cache='hit',
                      snapshot_age_minutes=(self.clock() - entry['captured']) / 60)
            return entry['data']
        return None

    def may_request(self, spec):
        family = self.family(spec)
        return (not self.cycle['closed'] and self.clock() - self.cycle['started'] < WINDOW
                and self.cycle['counts'].get(family, 0) < 2
                and self.clock() >= self.data.get('rate_limit_until', 0)
                and self.clock() >= self.data['cooldowns'].get(family, {}).get('until', 0))

    def begin(self, spec):
        if not self.may_request(spec):
            return False
        delay = 3 - (self.clock() - self.data['last_request'])
        if delay > 0:
            self.sleep(delay)
        if not self.may_request(spec):
            return False
        family = self.family(spec)
        self.cycle['counts'][family] = self.cycle['counts'].get(family, 0) + 1
        self.cycle['requests'][family] = spec
        # A cancelled/in-flight request consumes its attempt and waits before retry.
        self.data['last_request'] = self.clock()
        self.data['cooldowns'][family] = {'until': self.clock() + RETRY_DELAY}
        self.cycle['failed'][family] = spec
        self.save()  # MUST reach remote storage before HTTP.
        return True

    def success(self, spec, data):
        family = self.family(spec)
        entry = {'spec': spec, 'captured': self.clock(), 'data': data}
        self.cycle['responses'][request_key(spec)] = entry
        self.used[request_key(spec)] = entry
        self.cycle['failed'].pop(family, None)
        self.data['cooldowns'].pop(family, None)
        self.save()

    def failure(self, spec, status, header=None, allow_minimal=False):
        family = self.family(spec)
        delay = max(RETRY_DELAY, retry_after(header, self.clock()))
        if status == 429:
            self.data['rate_limit_until'] = self.clock() + delay
        if status in (401, 403):
            delay = WINDOW
        if allow_minimal and status == 403 and self.cycle['counts'].get(family, 0) == 1:
            delay = 0  # The one tested alternate request consumes the second attempt.
        self.data['cooldowns'][family] = {'until': self.clock() + delay}
        self.cycle['failed'][family] = spec
        self.save()

    def invalidate(self, endpoints):
        """HTTP 200 with absent/partial target data is not a usable success."""
        changed = False
        for key, entry in list(self.cycle['responses'].items()):
            spec = entry['spec']
            if spec['endpoint'] in endpoints:
                family = self.family(spec)
                del self.cycle['responses'][key]
                self.cycle['failed'][family] = spec
                self.data['cooldowns'].setdefault(family, {'until': self.clock() + RETRY_DELAY})
                changed = True
        if changed:
            self.save()

    def pending(self):
        deadline = self.cycle['started'] + WINDOW
        return any(self.cycle['counts'].get(family, 0) < 2
                   and max(self.clock(), self.data.get('rate_limit_until', 0), self.data['cooldowns'].get(family, {}).get('until', 0)) < deadline
                   for family in self.cycle['failed']) and not self.cycle['closed']

    def capture_metadata(self):
        entries = list(self.used.values())
        now = self.clock()
        if not entries or any(not 0 <= now - e['captured'] <= WINDOW for e in entries):
            raise ValueError('Forecast capture expired')
        timestamps = [e['captured'] for e in entries]
        if max(timestamps) - min(timestamps) > WINDOW:
            raise ValueError('Forecast capture spread exceeded')
        iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).isoformat()
        return {'captured_at_utc': iso(min(timestamps)),
                'endpoint_captures': {e['spec']['endpoint']: {'captured_at_utc': iso(e['captured']),
                     'request': e['spec'], 'source': 'Surfline'} for e in entries}}
