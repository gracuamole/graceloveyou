import copy
import unittest
from datetime import datetime
from recommendations import BALI, recommend, tide_at, daylight_intervals, render_day
from phase2 import chunks, build_blocks


def row(height=2, energy=400, period=10, wind=5):
    return dict(surf_min_ft=height, surf_max_ft=height,
                energy={'nearshore': energy}, swells=[{'period_s': period}],
                wind={'speed_kts': wind, 'cardinal': 'E'}, rating={'key': 'FAIR'})


TIDE = {'band': 'mid'}


class Rules(unittest.TestCase):
    def test_height_boundaries(self):
        for h, tier, area in [(2, 'beginner', 'inside whitewater'),
                              (2.01, 'beginner', 'inside whitewater'),
                              (4, 'intermediate', 'inside/outside'),
                              (4.01, 'intermediate', 'inside only')]:
            advice = recommend(row(h), TIDE, tier)
            self.assertEqual(advice['break'], area)
            self.assertEqual(advice['coach'], tier == 'beginner' and h > 2)
        self.assertIn('3–3 ft', ' '.join(recommend(row(3), TIDE, 'beginner')['notes']))

    def test_small_powerful_beginner_exception(self):
        advice = recommend(row(1.5, 700), TIDE, 'beginner')
        self.assertTrue(advice['coach'])
        self.assertEqual(advice['status'], 'conditional')
        self.assertIn('inside', advice['break'])

    def test_intermediate_energy_boundary(self):
        self.assertEqual(recommend(row(3, 1000), TIDE, 'intermediate')['break'], 'inside/outside')
        self.assertEqual(recommend(row(3, 1001), TIDE, 'intermediate')['break'], 'inside only')

    def test_flat_boundary(self):
        for tier in ('beginner', 'intermediate', 'advanced'):
            self.assertEqual(recommend(row(1, 99), TIDE, tier)['status'], 'not recommended')
            self.assertNotEqual(recommend(row(1, 100), TIDE, tier)['status'], 'not recommended')

    def test_wind_boundary_and_no_ban(self):
        self.assertFalse(recommend(row(wind=20 / 1.852), TIDE, 'beginner')['coach'])
        self.assertTrue(recommend(row(wind=20.01 / 1.852), TIDE, 'beginner')['coach'])
        self.assertEqual(recommend(row(wind=25), TIDE, 'advanced')['status'], 'conditional')

    def test_period_and_low_tide(self):
        self.assertTrue(recommend(row(period=13), TIDE, 'beginner')['coach'])
        self.assertEqual(recommend(row(period=15), TIDE, 'intermediate')['break'], 'inside only')
        self.assertTrue(recommend(row(), {'band': 'low'}, 'beginner')['coach'])

    def test_missing_and_invalid_do_not_become_safe(self):
        for value in (None, -1, float('nan'), float('inf'), True):
            for key in ('surf_min_ft', 'surf_max_ft'):
                data = row()
                data[key] = value
                self.assertEqual(recommend(data, TIDE, 'beginner')['status'], 'unknown')
            data = row(energy=value)
            self.assertEqual(recommend(data, TIDE, 'advanced')['status'], 'unknown')
        self.assertEqual(recommend(row(), None, 'advanced')['status'], 'unknown')
        self.assertEqual(recommend(row(energy=0), TIDE, 'advanced')['status'], 'not recommended')

    def test_rating_quality_cannot_override_limits(self):
        data = row(5, 1200)
        data['rating']['key'] = 'EPIC'
        self.assertEqual(recommend(data, TIDE, 'intermediate')['break'], 'inside only')
        data = row()
        data['rating']['key'] = 'POOR'
        self.assertEqual(recommend(data, TIDE, 'advanced')['status'], 'conditional')


class Coverage(unittest.TestCase):
    def setUp(self):
        self.base = datetime(2026, 10, 30, tzinfo=BALI).timestamp()
        self.day = {'date': '2026-10-30',
                    'sunlight': {'sunrise_ts': self.base + 6 * 3600 + 300,
                                 'sunset_ts': self.base + 18 * 3600 + 600},
                    'hourly': [dict(row(), timestamp=self.base + h * 3600) for h in range(24)],
                    'tide_hourly': [{'timestamp': self.base + h * 3600, 'height_ft': h / 10} for h in range(24)]}

    def test_all_daylight_and_partial_hours(self):
        intervals = daylight_intervals(self.day)
        self.assertEqual(len(intervals), 13)
        self.assertEqual(intervals[0]['start'], self.day['sunlight']['sunrise_ts'])
        self.assertEqual(intervals[-1]['end'], self.day['sunlight']['sunset_ts'])
        self.assertTrue(all(a['end'] == b['start'] for a, b in zip(intervals, intervals[1:])))

    def test_gap_is_visible(self):
        self.day['hourly'] = []
        intervals = daylight_intervals(self.day)
        self.assertEqual(len(intervals), 13)
        self.assertTrue(all(i['tiers']['beginner']['status'] == 'unknown' for i in intervals))

    def test_no_invented_daylight(self):
        self.day['sunlight'] = None
        with self.assertRaises(ValueError):
            daylight_intervals(self.day)

    def test_tide_interpolation_mid_and_gap(self):
        tide = tide_at(self.day, self.base + 11.5 * 3600)
        self.assertAlmostEqual(tide['mid_m'], 1.15 * .3048)
        self.assertAlmostEqual(tide['height_m'], tide['mid_m'])
        self.assertEqual(tide['band'], 'mid')
        self.assertEqual(tide['trend'], 'rising')
        self.day['tide_hourly'] = self.day['tide_hourly'][::4]
        self.assertIsNone(tide_at(self.day, self.base + 3600))

    def test_negative_tides_allowed(self):
        for tide in self.day['tide_hourly']:
            tide['height_ft'] -= 1
        self.assertIsNotNone(tide_at(self.day, self.base + 3600))

    def test_report_and_message_limits(self):
        blocks = build_blocks({'daily': [self.day]}, self.day['date'], 'Test')
        messages = chunks(blocks)
        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(m) <= 3900 for m in messages))
        self.assertEqual('\n\n'.join(messages), '\n\n'.join(blocks))
        self.assertIn('2–2 ft', '\n'.join(blocks))
        with self.assertRaises(ValueError):
            build_blocks({'daily': []}, self.day['date'], 'Test')


if __name__ == '__main__':
    unittest.main()
