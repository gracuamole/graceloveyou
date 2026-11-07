"""Offline request accounting, restart recovery and partial forecast regressions."""
import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fetch_attempt import Attempts, FetchDeferred, CheckpointFailed, request_spec, request_key, retry_after
from protected_fetch import fetch, preflight
from forecast_quality import inspect, render
from state_retention import trim_completed
from recommendations import BALI

BASE = 'https://services.surfline.com/kbyg/spots/forecasts/'
URL = BASE + 'wind?spotId=spot&days=3&units%5BwindSpeed%5D=KTS'
SPEC = request_spec(URL)
PAYLOAD = {'data': {'wind': [{'timestamp': 123, 'speed': 5, 'gust': 10}]}}


class AttemptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fetch-attempt.json'
        self.now = 100000
        self.source = SimpleNamespace(cache={}, last_status={}, retry_headers={}, normalized_units=lambda d, e: d)
        self.source.request_json = Mock(side_effect=self.reply)
        self.status = 200
        self.header = None

    def reply(self, url, endpoint, label, **kwargs):
        self.source.last_status[endpoint] = self.status
        self.source.retry_headers[endpoint] = self.header
        return copy.deepcopy(PAYLOAD) if self.status == 200 else None

    def sleep(self, seconds):
        self.now += seconds

    def attempt(self, target='2026-11-07', **kwargs):
        return Attempts(self.path, target, clock=lambda: self.now, sleep=self.sleep, **kwargs)

    def test_exact_cache_and_restart_make_zero_requests(self):
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
        self.source.request_json.reset_mock()
        with self.attempt().locked() as a:
            self.assertEqual(fetch(self.source, a, URL), PAYLOAD)
        self.source.request_json.assert_not_called()

    def test_403_has_only_one_minimal_fallback_and_no_repeat_cycle(self):
        self.status = 403
        with self.attempt().locked() as a:
            self.assertEqual(fetch(self.source, a, URL), {'data': {'wind': []}})
        self.assertEqual(self.source.request_json.call_count, 2)
        self.assertIn('days=2', self.source.request_json.call_args.args[0])
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
            self.assertFalse(a.pending())
        self.assertEqual(self.source.request_json.call_count, 2)

    def test_minimal_success_is_saved_under_actual_request_not_days_three(self):
        def respond(url, endpoint, label, **kwargs):
            self.status = 403 if 'days=3' in url else 200
            return self.reply(url, endpoint, label, **kwargs)
        self.source.request_json.side_effect = respond
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
            self.assertNotIn(request_key(SPEC), a.cycle['responses'])
            self.assertEqual(next(iter(a.cycle['responses'].values()))['spec']['params']['days'], '2')
        self.source.request_json.reset_mock()
        with self.attempt().locked() as a:
            self.assertEqual(fetch(self.source, a, URL), PAYLOAD)
        self.source.request_json.assert_not_called()

    def test_429_stops_and_honours_long_retry_after_across_restart(self):
        self.status, self.header = 429, '3600'
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
            self.assertFalse(a.pending())
        self.assertEqual(self.source.request_json.call_count, 1)
        self.now += 1800
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
        self.assertEqual(self.source.request_json.call_count, 1)

    def test_rate_limit_blocks_other_endpoints_too(self):
        self.status, self.header = 429, '3600'
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
            fetch(self.source, a, BASE + 'energy?spotId=spot&days=3')
        self.assertEqual(self.source.request_json.call_count, 1)

    def test_second_failure_exhausts_budget_and_blocked_endpoint_first(self):
        self.status = 500
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
            self.assertTrue(a.pending())
        self.source.request_json.reset_mock()
        with self.attempt().locked() as a:
            with self.assertRaises(FetchDeferred):
                preflight(self.source, a)
        self.source.request_json.assert_not_called()
        self.now += 300
        with self.attempt().locked() as a:
            preflight(self.source, a)
            fetch(self.source, a, URL)
            self.assertFalse(a.pending())
        self.assertEqual(self.source.request_json.call_count, 1)

    def test_inflight_attempt_survives_cancellation(self):
        with self.attempt().locked() as a:
            self.assertTrue(a.begin(SPEC))
        with self.attempt().locked() as a:
            self.assertFalse(a.begin(SPEC))
        self.now += 300
        with self.attempt().locked() as a:
            self.assertTrue(a.begin(SPEC))
        self.now += 300
        with self.attempt().locked() as a:
            self.assertFalse(a.begin(SPEC))

    def test_checkpoint_failure_prevents_http(self):
        with self.attempt(persist=True).locked() as a, patch('fetch_attempt.subprocess.run', side_effect=OSError):
            with self.assertRaises(CheckpointFailed):
                fetch(self.source, a, URL)
        self.source.request_json.assert_not_called()

    def test_expired_and_different_target_responses_not_used(self):
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
        self.now += 1801
        with self.attempt().locked() as a:
            self.assertIsNone(a.cached(SPEC))
            self.assertFalse(a.may_request(SPEC))
        with self.attempt('2026-11-08').locked() as a:
            self.assertIsNone(a.cached(SPEC))
            self.assertTrue(a.may_request(SPEC))

    def test_empty_200_not_cached_and_only_retried_once(self):
        self.source.request_json.side_effect = None
        self.source.request_json.return_value = {'data': {'wind': []}}
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
            self.assertEqual(a.cycle['responses'], {})
            self.assertTrue(a.pending())
        self.now += 300
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
            self.assertFalse(a.pending())
        self.assertEqual(self.source.request_json.call_count, 2)

    def test_success_clears_cooldown_and_records_capture(self):
        self.status = 500
        with self.attempt().locked() as a:
            fetch(self.source, a, URL)
        self.now += 300
        self.status = 200
        with self.attempt().locked() as a:
            preflight(self.source, a)
            self.assertFalse(a.cycle['failed'])
            self.assertFalse(a.data['cooldowns'])
            self.assertIn('wind', a.capture_metadata()['endpoint_captures'])

    def test_invalid_checkpoint_is_not_reset(self):
        self.path.write_text('{broken')
        with self.assertRaises(ValueError), self.attempt().locked():
            pass
        self.assertEqual(self.path.read_text(), '{broken')

    def test_http_date_retry_after(self):
        self.assertEqual(retry_after('Thu, 01 Jan 1970 01:00:00 GMT', 0), 3600)
        self.assertEqual(retry_after('bad', 0), 0)


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((Path(__file__).parent / 'fixtures/november_2_2026.json').read_text())
        if 'forecast' in self.data:
            self.data = self.data['forecast']
        self.target = '2026-11-02'

    def test_missing_tide_disclosed_without_good_conditions_claim(self):
        day = next(d for d in self.data['daily'] if d['date'] == self.target)
        day['tide_hourly'] = []
        day['tide_extrema'] = []
        missing, intervals = inspect(self.data, self.target)
        self.assertIn('tides', missing)
        parts, notes = render(self.data, self.target, "Old Man's / Batu Bolong", missing, intervals)
        self.assertIn('inside break is suitable for beginners', notes)
        self.assertNotIn('All day is surfable', '\n'.join(parts))
        self.assertIn('Could not confirm', '\n'.join(parts))

    def test_missing_sunrise_does_not_invent_hours(self):
        day = next(d for d in self.data['daily'] if d['date'] == self.target)
        day['sunlight'] = None
        missing, intervals = inspect(self.data, self.target)
        self.assertIn('weather', missing)
        self.assertNotIn('surf', missing)
        parts, notes = render(self.data, self.target, 'Batu Bolong', missing, intervals)
        self.assertIn('Could not assess surf times', '\n'.join(parts))
        self.assertIn('daylight', notes)

    def test_missing_breaking_surf_is_required(self):
        day = next(d for d in self.data['daily'] if d['date'] == self.target)
        for row in day['hourly']:
            row['surf_max_ft'] = None
        self.assertIn('surf', inspect(self.data, self.target)[0])

    def test_retention_preserves_memory_active_work_and_publication_ids(self):
        data = {'reports': {}, 'memory': {'entries': [{'text': 'keep'}]}}
        for index, status in enumerate(('published', 'expired', 'review', 'revision_pending')):
            date = f'2026-10-0{index+1}'
            data['reports'][date] = {'date': date, 'status': status, 'parts': ['private details'],
                                     'forecast': {'daily': []}, 'publish_ids': [99]}
        uncertain = copy.deepcopy(data['reports']['2026-10-01'])
        uncertain['intent'] = {'kind': 'publish'}
        data['reports']['2026-10-05'] = uncertain
        self.assertEqual(trim_completed(data, '2026-11-06'), 2)
        self.assertEqual(data['reports']['2026-10-01']['publish_ids'], [99])
        self.assertNotIn('forecast', data['reports']['2026-10-01'])
        self.assertIn('forecast', data['reports']['2026-10-03'])
        self.assertIn('forecast', data['reports']['2026-10-05'])
        self.assertEqual(data['memory']['entries'], [{'text': 'keep'}])
        self.assertEqual(trim_completed(data, '2026-11-06'), 0)
