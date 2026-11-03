import copy
import json
from pathlib import Path
import unittest
from recommendations import batu_recommend, rounded_tide, daylight_intervals, render_day, qualifies
from review_bot import revision_input


class BatuRules(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((Path(__file__).parent / 'fixtures/november_2_2026.json').read_text())
        self.day = self.report['forecast']['daily'][0]
        self.row = copy.deepcopy(self.day['hourly'][6])
        self.tide = {'height_m': 0.8, 'band': 'low'}

    def allowed(self, tier):
        return batu_recommend(self.row, self.tide, tier)['status'] == 'suitable to consider'

    def test_november_two_all_day_and_revision_share_policy(self):
        blocks = render_day(self.day, self.report['name'])
        for index, label in ((1, 'Inside'), (2, 'Outside'), (3, 'Outside')):
            self.assertIn('All day is surfable - ' + label + ' break', blocks[index])
        self.report['parts'] = blocks
        context = json.loads(revision_input(self.report, 'keep it short change'))
        self.assertIn('All day is surfable', context['report_format']['qualifying_windows']['intermediate'][0])
        self.assertEqual(context['report_format']['cautions'], blocks[-1].split('\n- ')[1:] if blocks[-1].startswith('⚠️') else [])

    def test_half_up_tide_boundary_only_excludes_inside(self):
        for tide, expected in ((.749, False), (.75, True), (.79, True), (.8, True)):
            self.tide['height_m'] = tide
            self.assertEqual(self.allowed('beginner'), expected)
            self.assertTrue(self.allowed('intermediate'))
            self.assertTrue(self.allowed('advanced'))
        self.assertEqual(rounded_tide(.75), .8)

    def test_energy_boundaries_and_field_selection(self):
        for energy, expected in ((79.9, (False, False, False)), (80, (True, True, True)),
                                 (999.9, (True, True, True)), (1000, (False, False, True))):
            self.row['energy']['nearshore'] = energy
            self.row['swell_power_total'] = 1
            self.assertEqual(tuple(self.allowed(t) for t in ('beginner','intermediate','advanced')), expected)

    def test_rating_and_height(self):
        self.row['rating']['key'] = 'POOR'
        self.assertTrue(self.allowed('beginner'))
        self.assertFalse(self.allowed('intermediate'))
        self.assertFalse(self.allowed('advanced'))
        self.row['rating']['key'] = 'POOR_TO_FAIR'
        for metres, expected in ((2.49, True), (2.5, False)):
            self.row['surf_max_ft'] = metres / .3048
            self.assertEqual(self.allowed('beginner'), expected)
        self.row['rating']['key'] = 'VERY_POOR'
        self.assertFalse(self.allowed('advanced'))

    def test_missing_data_is_not_recommended(self):
        self.row['energy']['nearshore'] = None
        for tier in ('beginner','intermediate','advanced'):
            self.assertEqual(batu_recommend(self.row,self.tide,tier)['status'],'unknown')

    def test_gusts_before_actual_sunrise_and_no_evening_leak(self):
        for row in self.day['hourly']:
            row['wind']['gust_kts'] = 0
            row['wind']['speed_kts'] = 5
        self.day['hourly'][5]['wind']['gust_kts'] = 17 / 1.852
        text = '\n'.join(render_day(self.day,self.report['name']))
        self.assertIn('Waves may be choppy from sunrise',text)
        self.assertIn('All day is surfable - Inside break',text)
        self.day['hourly'][5]['wind']['gust_kts'] = 16 / 1.852
        self.day['hourly'][20]['wind']['gust_kts'] = 40
        self.assertNotIn('choppy','\n'.join(render_day(self.day,self.report['name'])))

    def test_rising_wind_caution_does_not_exclude_near_twenty(self):
        for row in self.day['hourly']:
            row['wind']['speed_kts'] = 10 / 1.852
        self.day['hourly'][15]['wind']['speed_kts'] = 19.9 / 1.852
        text = '\n'.join(render_day(self.day,self.report['name']))
        self.assertIn('Conditions may become windy later in the day.', text)
        self.assertIn('All day is surfable - Outside break', text)
        self.row['wind']['speed_kts'] = 20.1 / 1.852
        self.assertTrue(self.allowed('advanced'))


    def test_exact_twenty_and_above_keep_all_day_with_tier_warnings(self):
        for speed in (20, 25):
            for row in self.day['hourly']:
                row['wind']['speed_kts'] = 10 / 1.852
            self.day['hourly'][15]['wind']['speed_kts'] = speed / 1.852
            blocks = render_day(self.day, self.report['name'])
            self.assertEqual(blocks[1], '🟢 BEGINNER\nAll day is surfable - Inside break\n'
                '15:00 - 16:00 - forecasted to be windy, coach recommended')
            for index, heading in ((2, '🟡 INTERMEDIATE'), (3, '🔵 ADVANCED')):
                self.assertEqual(blocks[index], heading + '\nAll day is surfable - Outside break\n'
                    '15:00 - 16:00 - forecasted to be windy, but up to your personal preference if you want to surf')

    def test_windy_periods_merge_but_never_bridge_exclusions(self):
        for row in self.day['hourly']:
            row['wind']['speed_kts'] = 25 / 1.852
        self.day['hourly'][12]['energy']['nearshore'] = None
        blocks = render_day(self.day, self.report['name'])
        for block in blocks[1:4]:
            self.assertNotIn('All day', block)
            self.assertIn('06:00 - 12:00 - forecasted', block)
            self.assertIn('13:00 - 18:00 - forecasted', block)
            self.assertNotIn('06:00 - 18:00', block)


    def test_explicit_feedback_can_remove_wind_warnings_without_code_restoration(self):
        from unittest.mock import patch
        from review_bot import revise, REVISION_INSTRUCTIONS
        self.day['hourly'][15]['wind']['speed_kts'] = 20.2 / 1.852
        self.report['parts'] = render_day(self.day, self.report['name'])
        original = '\n\n'.join(self.report['parts'])
        revised = '\n'.join(line for line in original.splitlines() if 'forecasted to be windy' not in line)
        with patch.dict('os.environ', {'LLM_PROVIDER': 'gemini'}), patch('review_bot.gemini_text', return_value=revised):
            result = '\n\n'.join(revise(self.report, 'remove the per-level windy warnings change'))
        self.assertNotIn('forecasted to be windy', result)
        self.assertIn('All day is surfable', result)
        self.assertIn('Explicit reviewer corrections take priority', REVISION_INSTRUCTIONS)
        self.assertIn('adding a caution must not remove windy-period lines', REVISION_INSTRUCTIONS)

    def test_unrelated_edit_can_preserve_warnings_without_rewriting_model_result(self):
        from unittest.mock import patch
        from review_bot import revise
        self.day['hourly'][15]['wind']['speed_kts'] = 20.2 / 1.852
        self.report['parts'] = render_day(self.day, self.report['name'])
        revised = '\n\n'.join(self.report['parts']) + '\n- Reviewer custom note.'
        with patch.dict('os.environ', {'LLM_PROVIDER': 'gemini'}), patch('review_bot.gemini_text', return_value=revised):
            result = '\n\n'.join(revise(self.report, 'add Reviewer custom note change'))
        self.assertEqual(result.count('forecasted to be windy'), 3)
        self.assertIn('Reviewer custom note.', result)


    def test_upward_wind_rounding_and_warning_boundary(self):
        from recommendations import wind_kmh
        self.assertEqual(wind_kmh(10.6), 20)
        self.assertEqual(wind_kmh(19.01 / 1.852), 20)
        self.assertEqual(wind_kmh(19 / 1.852), 19)
        self.assertEqual(wind_kmh(16.01 / 1.852), 17)
        self.assertIsNone(wind_kmh(None))
        self.day['hourly'][13]['wind']['speed_kts'] = 10.6
        text = '\n'.join(render_day(self.day, self.report['name']))
        self.assertIn('13:00 - 14:00 - forecasted to be windy', text)
