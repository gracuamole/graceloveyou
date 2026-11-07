"""Release 2 transport policy layered over the existing Surfline parser."""
from urllib.parse import urlencode

from fetch_attempt import request_key, request_spec, FetchDeferred
from run_log import log_event

BASE = 'https://services.surfline.com/kbyg/spots/forecasts/'


def empty(endpoint, target):
    # Conditions supplies the parser's calendar, not observed wave measurements.
    # A target date is safe to supply; no missing forecast values are manufactured.
    if endpoint == 'conditions':
        return {'data': {'conditions': [{'forecastDay': target}]}}
    return {'data': {endpoint: []}}


def fetch(source, attempt, url):
    from forecast_sources import SourceUnavailable
    spec = request_spec(url)
    endpoint = spec['endpoint']
    minimal = {'endpoint': endpoint, 'params': {'spotId': spec['params']['spotId'], 'days': '2'}}
    # The fallback is cached under its actual request, never under days=3.
    # It is considered only for the same next-day target; final target coverage is validated.
    aliases = attempt.cycle.setdefault('alternates', {})
    primary_key = request_key(spec)
    candidates = (spec, minimal) if aliases.get(primary_key) == request_key(minimal) else (spec,)
    for candidate in candidates:
        data = attempt.cached(candidate)
        if data is not None:
            source.cache[endpoint] = data
            return data
    log_event('surfline_endpoint', endpoint=endpoint, cache='miss')
    if not attempt.may_request(spec):
        attempt.missing.add(endpoint)
        log_event('surfline_endpoint', endpoint=endpoint, cache='not_applicable', outcome='failure')
        return empty(endpoint, attempt.target)
    selected = spec
    for transport in ('firefox', 'requests'):
        if not attempt.begin(selected):
            break
        query = urlencode(selected['params'])
        source.last_status.pop(endpoint, None)
        source.retry_headers.pop(endpoint, None)
        data = source.request_json(BASE + endpoint + '?' + query, endpoint,
                                   'package' if transport == 'firefox' else 'minimal requests',
                                   attempts=1, transport=transport)
        status = source.last_status.get(endpoint, 0)
        try:
            data = source.normalized_units(data, endpoint) if data is not None else None
            if not isinstance(data, dict) or not isinstance(data.get('data'), dict):
                data = None
            # Empty lists are not cached as successful observations.
            if data is not None and not any(isinstance(v, list) and v for v in data['data'].values()):
                data = None
        except (ValueError, TypeError, KeyError, SourceUnavailable):
            data = None
        if data is not None:
            attempt.success(selected, data)
            source.cache[endpoint] = data
            return data
        alternate = transport == 'firefox' and status == 403
        attempt.failure(selected, status, source.retry_headers.get(endpoint), allow_minimal=alternate)
        if not alternate:
            break
        aliases[primary_key] = request_key(minimal)
        selected = minimal
    attempt.missing.add(endpoint)
    return empty(endpoint, attempt.target)


def preflight(source, attempt):
    """Probe previously blocked feeds before invoking the parser's fixed endpoint order."""
    for spec in list(attempt.cycle['failed'].values()):
        if attempt.may_request(spec):
            fetch(source, attempt, BASE + spec['endpoint'] + '?' + urlencode(spec['params']))
        family = attempt.family(spec)
        if (family in attempt.cycle['failed'] and attempt.cycle['counts'].get(family, 0) < 2
                and max(attempt.clock(), attempt.data.get('rate_limit_until', 0),
                        attempt.data['cooldowns'].get(family, {}).get('until', 0))
                    < attempt.cycle['started'] + 1800):
            raise FetchDeferred('Forecast retry is waiting for its cooldown; no other requests made.')
