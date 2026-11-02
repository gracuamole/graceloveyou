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
            self.assertIn('06:00–18:00 — ' + label + ' break', blocks[index])
        self.report['parts'] = blocks
        context = json.loads(revision_input(self.report, 'keep it short change'))
        self.assertIn('06:00–18:00', context['report_format']['qualifying_windows']['intermediate'][0])
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
        self.assertIn('06:00–18:00 — Inside break',text)
        self.day['hourly'][5]['wind']['gust_kts'] = 16.99 / 1.852
        self.day['hourly'][20]['wind']['gust_kts'] = 40
        self.assertNotIn('choppy','\n'.join(render_day(self.day,self.report['name'])))

    def test_rising_wind_caution_does_not_exclude_near_twenty(self):
        for row in self.day['hourly']:
            row['wind']['speed_kts'] = 10 / 1.852
        self.day['hourly'][15]['wind']['speed_kts'] = 19.9 / 1.852
        text = '\n'.join(render_day(self.day,self.report['name']))
        self.assertIn('Conditions may become windy later in the day.', text)
        self.assertIn('06:00–18:00 — Outside break', text)
        self.row['wind']['speed_kts'] = 20.1 / 1.852
        self.assertFalse(self.allowed('advanced'))
