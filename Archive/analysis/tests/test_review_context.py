import copy
import json
from pathlib import Path
import unittest

from phase2 import build_blocks
from recommendations import daylight_intervals
from review_context import build_review_context


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((Path(__file__).resolve().parents[3] / 'tests/fixtures/november_1_2026.json').read_text())
        self.report.update(revision=1, parts=build_blocks(
            self.report['forecast'], self.report['date'], self.report['name']))
        self.day = self.report['forecast']['daily'][0]

    def test_november_first_uses_current_batu_rules(self):
        text = '\n\n'.join(self.report['parts'])
        self.assertIn('06:00–07:00 and 10:00–18:00 — Inside break', text)
        self.assertIn('🟡 INTERMEDIATE\nAll day is surfable - Outside break', text)
        self.assertIn('🔵 ADVANCED\nAll day is surfable - Outside break', text)
        self.assertNotIn('coach recommended', text)

    def test_analysis_explains_current_batu_exclusions(self):
        analysis, source = build_review_context(self.report)
        self.assertIn('no mid-tide restriction', analysis)
        self.assertIn('07:00–08:00: Excluded — Rounded tide is below 0.8 m', analysis)
        self.assertIn('INTERMEDIATE', analysis)
        self.assertIn('All day is surfable - Outside break', analysis)
        self.assertNotIn('coached inside-break exception', analysis)

    def test_source_summary_preserves_actual_values_and_identifies_calculations(self):
        _, source = build_review_context(self.report)
        self.assertIn('Sunrise 05:51; sunset 18:16. Analyzed 06:00–18:00', source)
        self.assertIn('06:00 | 3–4 | 222.7 | 14 | 8.1 E | 0.88 low/falling | Fair', source)
        self.assertIn('08:00 | 3–4 | 221.5 | 14 | 13.1 ESE | 0.56 low/rising | Fair', source)
        self.assertIn('14:00 | 3–4 | 230.4 | 14 | 16.9 SSE | 2.03 high/falling | Poor to fair', source)
        self.assertIn('Low 07:44 (0.56 m); High 13:50 (2.04 m)', source)
        self.assertIn('feed units unconfirmed', source)
        self.assertIn('inside waves are not separately forecast', source)
        self.assertIn('application calculations', source)
        self.assertIn('Displayed values are rounded', source)

    def test_night_forecast_rows_do_not_enter_analysis_or_source_summary(self):
        before = build_review_context(self.report)
        daylight = {i['start'] for i in daylight_intervals(self.day)}
        for row in self.day['hourly']:
            if row['timestamp'] not in daylight:
                row['energy']['nearshore'] = 98765
                row['surf_max_ft'] = 98765
        self.assertEqual(build_review_context(self.report), before)

    def test_corrections_are_labelled_without_overwriting_surfline_values(self):
        before = copy.deepcopy(self.report['forecast'])
        self.report['feedback'] = 'The energy is 987.6, please check change'
        self.report['parts'][1] = '🟢 BEGINNER\nNo qualifying window.'
        analysis, source = build_review_context(self.report)
        self.assertIn('Current draft: No qualifying window.', analysis)
        self.assertIn('current draft differs from the source-rule windows', analysis)
        self.assertIn('Reviewer feedback for this draft (not original Surfline data)', analysis)
        self.assertIn('987.6', analysis)
        self.assertNotIn('987.6', source)
        self.assertEqual(self.report['forecast'], before)

    def test_missing_secondary_data_is_explained_and_never_invented(self):
        for row in self.day['hourly']:
            row['wind'] = {}
        self.report['parts'] = build_blocks(self.report['forecast'], self.report['date'], self.report['name'])
        analysis, source = build_review_context(self.report)
        self.assertIn('Excluded — Missing wind', analysis)
        self.assertIn('N/A', source)
        self.assertNotIn(': Included', analysis)

    def test_invalid_daily_sunlight_stops_context_building(self):
        self.day['sunlight'] = {}
        with self.assertRaises(ValueError):
            build_review_context(self.report)

    def test_legacy_snapshot_absence_is_explicit(self):
        self.report['forecast'] = {}
        analysis, source = build_review_context(self.report)
        self.assertIn('Saved forecast data is unavailable', analysis)
        self.assertIn('No measurements have been invented', source)


if __name__ == '__main__':
    unittest.main()
