import copy
import json
from pathlib import Path
import unittest

from phase2 import build_blocks
from recommendations import daylight_intervals
from review_context import build_review_context


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((Path(__file__).parent / 'fixtures/november_1_2026.json').read_text())
        self.report.update(revision=1, parts=build_blocks(
            self.report['forecast'], self.report['date'], self.report['name']))
        self.day = self.report['forecast']['daily'][0]

    def test_november_first_reproduces_the_agreed_report_from_actual_saved_data(self):
        text = '\n\n'.join(self.report['parts'])
        self.assertIn('🟢 BEGINNER\n06:00–09:00 — Inside break only, coach recommended', text)
        self.assertIn('🟡 INTERMEDIATE\nNo qualifying window.', text)
        self.assertIn('🔵 ADVANCED\n06:00–09:00', text)
        self.assertIn('A coach should assess the currents and confirm that the inside waves are no higher '
                      'than 2 ft before beginners enter.', text)
        for excluded in ('Low quality', 'Mid tide preferred', '09:00–18:00', 'Source:', 'WITA'):
            self.assertNotIn(excluded, text)

    def test_analysis_explains_each_skill_level_included_and_excluded_times(self):
        analysis, source = build_review_context(self.report)
        self.assertIn('coached inside-break exception', analysis)
        self.assertIn('INTERMEDIATE', analysis)
        self.assertIn('06:00–09:00: Excluded — the tide is low', analysis)
        self.assertIn('09:00–18:00: Excluded — Surfline rates the conditions Poor to fair.', analysis)
        self.assertIn('ADVANCED', analysis)
        self.assertIn('Breaking surf 3–4 ft; longest swell period 14 s; wind 8.1–13.1 km/h', analysis)
        self.assertIn('Energy units are unconfirmed', analysis)
        self.assertNotIn('Low quality', analysis + source)
        self.assertLessEqual(len(analysis.encode('utf-16-le')) // 2, 3000)
        self.assertLessEqual(len(source.encode('utf-16-le')) // 2, 3000)

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
        self.assertIn('Excluded — missing wind', analysis)
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
