import copy
from contextlib import redirect_stdout
from datetime import datetime
import io
import sys
import unittest
from unittest.mock import Mock, patch

from forecast_sources import SourceUnavailable, SurflineAccessDenied, fetch_surfline, prepare_forecast
from recommendations import BALI
from test_recommendations import row
import surfline_check


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.target = '2026-10-30'
        start = datetime(2026, 10, 30, tzinfo=BALI).timestamp()
        self.day = {'date': self.target,
                    'sunlight': {'sunrise_ts': start + 6 * 3600 + 300,
                                 'sunset_ts': start + 18 * 3600 + 600},
                    'hourly': [dict(row(), timestamp=start + h * 3600) for h in range(24)],
                    'tide_hourly': [{'timestamp': start + h * 3600, 'height_ft': h / 10}
                                    for h in range(24)]}
        self.forecast = {'daily': [self.day]}
        self.source = Mock(SPOT_ID='existing-spot', SPOT_NAME='Old Mans', cache={})
        self.source.fetch_full_forecast.return_value = self.forecast

    def test_reuses_spot_transport_and_normalized_data_without_llm(self):
        with patch.dict('sys.modules', {'main4_pkge_indi': self.source}):
            result = fetch_surfline(self.target)
        self.assertEqual(result.date, self.target)
        self.assertEqual(result.name, 'Old Mans')
        self.assertEqual(result.data, self.forecast)
        self.source.fetch_full_forecast.assert_called_once_with('existing-spot', days=3)
        self.assertEqual(result.parts[0].splitlines()[0], 'Forecast date: 30 October 2026')
        self.assertIn('📍OLD MANS', result.parts[0])
        for removed in ('WITA', 'Source: Surfline', 'recommendations are not safety guarantees'):
            self.assertNotIn(removed, '\n'.join(result.parts))
        self.assertIn('Breaking waves 2 ft', '\n'.join(result.parts))

    def test_missing_required_feeds_fail_closed_with_safe_error(self):
        for failure in ('network', 'missing-day', 'missing-sun', 'missing-hour', 'missing-height'):
            forecast = copy.deepcopy(self.forecast)
            if failure == 'network':
                self.source.fetch_full_forecast.side_effect = RuntimeError('PRIVATE_URL_AND_TOKEN')
            else:
                self.source.fetch_full_forecast.side_effect = None
                if failure == 'missing-day':
                    forecast['daily'] = []
                elif failure == 'missing-sun':
                    forecast['daily'][0]['sunlight'] = None
                elif failure == 'missing-hour':
                    forecast['daily'][0]['hourly'] = forecast['daily'][0]['hourly'][::2]
                else:
                    forecast['daily'][0]['hourly'][10]['surf_max_ft'] = None
                self.source.fetch_full_forecast.return_value = forecast
            with patch.dict('sys.modules', {'main4_pkge_indi': self.source}):
                with self.assertRaises(SourceUnavailable) as error:
                    fetch_surfline(self.target)
            self.assertNotIn('PRIVATE', str(error.exception))
            self.assertIn('No new draft was created', str(error.exception))

    def test_unknown_secondary_data_is_explicit_and_never_a_safe_recommendation(self):
        for data in self.day['hourly']:
            data['energy'] = None
        result = prepare_forecast(self.forecast, self.target, 'Test')
        rendered = '\n'.join(result.parts)
        self.assertEqual(rendered.count('Not assessed (missing energy)'), 3)
        self.assertNotIn('Inside break', rendered)
        self.assertNotIn('Breaking waves', rendered)
        self.assertNotIn('suitable to consider', rendered)

    def test_access_denial_remains_specific_instead_of_becoming_missing_data(self):
        self.source.fetch_full_forecast.side_effect = SurflineAccessDenied(403)
        with patch.dict('sys.modules', {'main4_pkge_indi': self.source}):
            with self.assertRaisesRegex(SourceUnavailable, 'Surfline denied forecast access \\(HTTP 403\\)'):
                fetch_surfline(self.target)
        self.source.fetch_full_forecast.assert_called_once()

    def test_live_check_reports_coverage_without_report_delivery_or_credentials(self):
        snapshot = prepare_forecast(self.forecast, self.target, 'Test')
        output = io.StringIO()
        with patch.object(sys, 'argv', ['surfline_check.py', '--date', self.target]), \
                patch('surfline_check.fetch_surfline', return_value=snapshot) as fetch, \
                patch('surfline_check.version', return_value='tested'), redirect_stdout(output):
            result = surfline_check.main()
        self.assertEqual(result, 0)
        fetch.assert_called_once_with(self.target)
        self.assertIn('Wind coverage: 13/13.', output.getvalue())
        self.assertIn('PREVIEW ONLY; nothing sent', output.getvalue())
        self.assertNotIn('Beginner:', output.getvalue())  # Summary, not a published report.

    def test_live_check_exits_nonzero_on_denied_forecast(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['surfline_check.py', '--date', self.target]), \
                patch('surfline_check.fetch_surfline', side_effect=SurflineAccessDenied(403)), \
                patch('surfline_check.version', return_value='tested'), redirect_stdout(output):
            self.assertEqual(surfline_check.main(), 1)
        self.assertIn('HTTP 403', output.getvalue())
        self.assertNotIn('Deterministic report prepared:', output.getvalue())


if __name__ == '__main__':
    unittest.main()
