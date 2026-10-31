"""Offline regressions for the original request path and minimal-response units."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from forecast_sources import SourceUnavailable, SurflineAccessDenied


class TransportTests(unittest.TestCase):
    def setUp(self):
        curl = ModuleType('curl_cffi')
        curl.requests = Mock()
        self.curl = curl.requests
        self.plain = Mock()
        package, client = ModuleType('surf_mcp'), ModuleType('surf_mcp.surfline_client')
        package.fetch_full_forecast = Mock()
        package.surfline_client = client
        self.client = client
        self.modules = patch.dict('sys.modules', {'curl_cffi': curl, 'requests': self.plain,
                                  'surf_mcp': package, 'surf_mcp.surfline_client': client})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        path = Path(__file__).resolve().parents[1] / 'main4_pkge_indi.py'
        spec = importlib.util.spec_from_file_location('tested_surfline_transport', path)
        self.transport = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.transport)
        self.sleep = patch.object(self.transport.time, 'sleep').start()
        self.addCleanup(self.sleep.stop)
        self.base = 'https://services.surfline.com/kbyg/spots/forecasts/'
        self.query = '?spotId=verified-spot&days=3&cacheEnabled=true&intervalHours=1'

    def response(self, status, data=None):
        response = Mock(status_code=status)
        response.json.return_value = data
        return response

    def test_library_parser_uses_the_existing_curl_transport(self):
        self.assertIs(self.client._get_json, self.transport.curl_get_json)

    def test_rejected_package_request_uses_original_minimal_plain_request(self):
        payload = {'data': {'conditions': [{'forecastDay': '2026-11-01'}]}}
        self.curl.get.return_value = self.response(403)
        self.plain.get.return_value = self.response(200, payload)
        result = self.transport.curl_get_json(self.base + 'conditions' + self.query)
        self.assertEqual(result, payload)
        self.curl.get.assert_called_once_with(self.base + 'conditions' + self.query,
                                              impersonate='firefox', timeout=25)
        self.plain.get.assert_called_once_with(self.base + 'conditions',
                                               params={'spotId': 'verified-spot', 'days': 2}, timeout=25)
        self.sleep.assert_not_called()  # Do not repeat the identical denied request.

    def test_minimal_firefox_remains_available_as_in_the_original_test(self):
        payload = {'data': {'rating': [{'timestamp': 123, 'rating': {'key': 'FAIR'}}]}}
        self.curl.get.side_effect = [self.response(403), self.response(200, payload)]
        self.plain.get.return_value = self.response(403)
        self.assertEqual(self.transport.curl_get_json(self.base + 'rating' + self.query), payload)
        self.assertEqual(self.curl.get.call_count, 2)
        self.assertEqual(self.curl.get.call_args.kwargs,
                         {'params': {'spotId': 'verified-spot', 'days': 2}, 'impersonate': 'firefox', 'timeout': 25})

    def test_denied_required_rating_is_not_replaced_with_a_fake_rating(self):
        self.curl.get.return_value = self.response(403)
        self.plain.get.return_value = self.response(403)
        with self.assertRaisesRegex(SurflineAccessDenied, 'HTTP 403'):
            self.transport.curl_get_json(self.base + 'rating' + self.query)
        self.assertNotIn('rating', self.transport.cache)
        self.assertEqual(self.curl.get.call_count, 2)
        self.plain.get.assert_called_once()

    def test_unavailable_optional_energy_remains_unknown(self):
        self.curl.get.return_value = self.response(403)
        self.plain.get.return_value = self.response(403)
        self.assertEqual(self.transport.curl_get_json(self.base + 'energy' + self.query), {'data': {'energy': []}})

    def test_minimal_metric_measurements_reach_parser_in_its_expected_units(self):
        examples = [
            ('surf', 'waveHeight', 'M', {'surf': {'min': .3048, 'max': .6096}}, 'FT'),
            ('swells', 'swellHeight', 'M', {'swells': [{'height': .9144, 'period': 10}]}, 'FT'),
            ('tides', 'tideHeight', 'M', {'height': -.3048}, 'FT'),
            ('wind', 'windSpeed', 'KPH', {'speed': 18.52, 'gust': 37.04, 'direction': 90}, 'KTS'),
            ('weather', 'temperature', 'C', {'temperature': 25}, 'F'),
        ]
        for endpoint, key, unit, row, target in examples:
            original = {'associated': {'units': {key: unit}}, 'data': {endpoint: [row]}}
            before = deepcopy(original)
            result = self.transport.normalized_units(original, endpoint)
            self.assertEqual(original, before)
            self.assertEqual(result['associated']['units'][key], target)
            measurements = result['data'][endpoint][0]
            if endpoint == 'surf':
                self.assertAlmostEqual(measurements['surf']['min'], 1)
                self.assertAlmostEqual(measurements['surf']['max'], 2)
            elif endpoint == 'swells':
                self.assertAlmostEqual(measurements['swells'][0]['height'], 3)
                self.assertEqual(measurements['swells'][0]['period'], 10)
            elif endpoint == 'tides':
                self.assertAlmostEqual(measurements['height'], -1)
            elif endpoint == 'wind':
                self.assertAlmostEqual(measurements['speed'], 10)
                self.assertAlmostEqual(measurements['gust'], 20)
                self.assertEqual(measurements['direction'], 90)
            else:
                self.assertEqual(measurements['temperature'], 77)
            self.assertEqual(self.transport.normalized_units(result, endpoint), result)

    def test_units_are_checked_even_when_the_primary_request_succeeds(self):
        payload = {'associated': {'units': {'waveHeight': 'M'}},
                   'data': {'surf': [{'surf': {'min': .3048, 'max': .6096}}]}}
        self.curl.get.return_value = self.response(200, payload)
        result = self.transport.curl_get_json(self.base + 'surf' + self.query)
        self.assertAlmostEqual(result['data']['surf'][0]['surf']['max'], 2)
        self.plain.get.assert_not_called()

    def test_unknown_units_do_not_become_feet_or_safe_measurements(self):
        for unit in ('', 'UNKNOWN'):
            payload = {'associated': {'units': {'waveHeight': unit}},
                       'data': {'surf': [{'surf': {'min': 1, 'max': 2}}]}}
            with self.assertRaisesRegex(SourceUnavailable, 'guessing units'):
                self.transport.normalized_units(payload, 'surf')

    def test_sunlight_only_response_needs_no_temperature_unit_guess(self):
        payload = {'data': {'weather': [], 'sunlightTimes': [{'sunrise': 123}]}}
        self.assertEqual(self.transport.normalized_units(payload, 'weather'), payload)


if __name__ == '__main__':
    unittest.main()
