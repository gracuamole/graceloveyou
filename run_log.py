"""Small, fail-open operational metrics. Never accept free-text payloads."""
from collections import Counter
from contextlib import contextmanager
from functools import wraps
import json
import math
import os
from pathlib import Path
import time

EVENTS = {'stage', 'surfline_request', 'surfline_endpoint'}
ENUMS = {
    'stage': {'forecast_fetch', 'gemini_revision', 'openai_revision', 'telegram_call',
              'state_save', 'git_push'},
    'endpoint': {'conditions', 'rating', 'surf', 'swells', 'wind', 'tides',
                 'consistency', 'energy', 'weather'},
    'request_kind': {'package', 'minimal requests', 'minimal Firefox'},
    'transport': {'requests', 'firefox'},
    'outcome': {'success', 'failure'},
    'cache': {'miss', 'hit', 'not_applicable'},
}
NUMBERS = {'status', 'attempt', 'duration_ms', 'snapshot_age_minutes'}
COUNTS = Counter()
DURATIONS = Counter()
ENDPOINT_DURATIONS = Counter()


def log_event(name, **fields):
    """Allowlisted labels and numeric measurements only; unknown data is dropped."""
    if name not in EVENTS:
        return
    record = {'event': name}
    for key, value in fields.items():
        if key in ENUMS and isinstance(value, str) and value in ENUMS[key]:
            record[key] = value
        elif key in NUMBERS and type(value) in (int, float) and math.isfinite(value):
            record[key] = value
    COUNTS[name] += 1
    if name == 'stage' and 'stage' in record:
        DURATIONS[record['stage']] += record.get('duration_ms', 0)
    if name == 'surfline_request':
        COUNTS['http_' + str(record.get('status', 'unavailable'))] += 1
        if 'endpoint' in record:
            ENDPOINT_DURATIONS[record['endpoint']] += record.get('duration_ms', 0)
    if name == 'surfline_endpoint':
        COUNTS['cache_' + record.get('cache', 'not_applicable')] += 1
    try:
        print(json.dumps(record, sort_keys=True), flush=True)
    except OSError:
        pass  # Observability must not change delivery or state behavior.


@contextmanager
def timed(stage):
    start = time.monotonic()
    outcome = 'failure'
    try:
        yield
        outcome = 'success'
    finally:
        log_event('stage', stage=stage, outcome=outcome,
                  duration_ms=round((time.monotonic() - start) * 1000, 2))


def measured(stage):
    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            with timed(stage):
                return function(*args, **kwargs)
        return wrapper
    return decorate


def write_summary():
    """Only executable entry points call this, including after handled failures."""
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if not path:
        return
    lines = ['## Surf bot run measurements', '',
             f"Surfline HTTP attempts: {COUNTS['surfline_request']}",
             f"Endpoint cache misses: {COUNTS['cache_miss']}",
             'Persistent cache, cooldowns and snapshot-age metrics: not implemented until Release 2.',
             '', '| Stage | Total seconds |', '| --- | ---: |']
    for stage, milliseconds in sorted(DURATIONS.items()):
        lines.append(f'| {stage} | {milliseconds / 1000:.3f} |')
    lines.extend(['', '| Endpoint | HTTP seconds (excluding retry waits) |', '| --- | ---: |'])
    lines.extend(f'| {endpoint} | {ms / 1000:.3f} |'
                 for endpoint, ms in sorted(ENDPOINT_DURATIONS.items()))
    lines.extend(['', 'HTTP results (0 means no response):'])
    lines.extend(f'- {key[5:]}: {count}' for key, count in sorted(COUNTS.items())
                 if key.startswith('http_'))
    lines.extend(['', 'Stage totals can overlap: state_save includes git_push. '
                  'Installation and setup durations are shown in the Actions steps.', ''])
    try:
        with Path(path).open('a', encoding='utf-8') as stream:
            stream.write('\n'.join(lines))
    except OSError:
        pass
