import copy
import unittest
from unittest.mock import patch
from datetime import datetime
from recommendations import BALI, recommend, tide_at, daylight_intervals, render_day, report_bold_entities
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

    def test_all_complete_daylight_hours(self):
        intervals = daylight_intervals(self.day)
        self.assertEqual(len(intervals), 11)
        self.assertEqual(intervals[0]['start'], self.base + 7 * 3600)
        self.assertEqual(intervals[-1]['end'], self.base + 18 * 3600)
        self.assertTrue(all(a['end'] == b['start'] for a, b in zip(intervals, intervals[1:])))

    def test_gap_is_visible(self):
        self.day['hourly'] = []
        intervals = daylight_intervals(self.day)
        self.assertEqual(len(intervals), 11)
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
        limit = max(len(block) for block in blocks)
        messages = chunks(blocks, limit=limit)
        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(m) <= limit for m in messages))
        self.assertEqual('\n\n'.join(messages), '\n\n'.join(blocks))
        self.assertIn('🔵 ADVANCED\n07:00–18:00', '\n'.join(blocks))
        self.assertNotIn('Breaking waves', '\n'.join(blocks))
        with self.assertRaises(ValueError):
            build_blocks({'daily': []}, self.day['date'], 'Test')

    def test_windows_keep_essential_restrictions_and_gaps_with_minimal_commentary(self):
        self.day['sunlight'] = {'sunrise_ts': self.base + 6 * 3600,
                                'sunset_ts': self.base + 18 * 3600}
        self.day['hourly'][8].update(row(2, 700, 13))
        self.day['hourly'][12].update(row(energy=None))
        for hour in (13, 14, 16, 17):
            self.day['hourly'][hour].update(row(5, 1200, 15))
        self.day['hourly'][15].update(row(3, 800))
        with patch('recommendations.tide_at', return_value=TIDE):
            blocks = render_day(self.day, "Old Man's / Batu Bolong")
        self.assertEqual(blocks[0], "Forecast date: 30 October 2026\n\n📍OLD MAN'S / BATU BOLONG")
        self.assertIn('🟢 BEGINNER\n06:00–08:00 and 09:00–12:00\n', blocks[1])
        self.assertIn('08:00–09:00 and 13:00–18:00 — Inside break only, coach recommended', blocks[1])
        self.assertIn('12:00–13:00 — Data unavailable', blocks[1])
        self.assertIn('13:00–15:00 and 16:00–18:00 — Inside break only', blocks[2])
        self.assertEqual(blocks[3], '🔵 ADVANCED\n06:00–12:00 and 13:00–18:00\n12:00–13:00 — Data unavailable')
        self.assertIn('beginners max 2 ft; intermediate inside-only max 4 ft', blocks[4])
        self.assertNotIn('Wind above', blocks[4])
        self.assertNotIn('Below 100', blocks[4])
        for removed in ('WITA', 'Source:', 'Energy:', 'Period:', 'Tide:', 'safety guarantees'):
            self.assertNotIn(removed, '\n'.join(blocks))

    def test_flat_windows_are_not_good_and_good_windows_omit_wave_commentary(self):
        self.day['sunlight'] = {'sunrise_ts': self.base + 6 * 3600,
                                'sunset_ts': self.base + 8 * 3600}
        self.day['hourly'][6].update(row(2, 99))
        self.day['hourly'][7].update(row(3, 99))
        with patch('recommendations.tide_at', return_value=TIDE):
            blocks = render_day(self.day, 'Test')
        self.assertEqual('\n'.join(blocks).count('06:00–08:00 — Not recommended (too flat)'), 3)
        self.assertNotIn('Inside break', '\n'.join(blocks))
        self.day['hourly'][6].update(row(3))
        self.day['hourly'][6]['surf_min_ft'] = 2
        self.day['hourly'][7].update(row(4))
        self.day['hourly'][7]['surf_min_ft'] = 3
        with patch('recommendations.tide_at', return_value=TIDE):
            advanced = render_day(self.day, 'Test')[3]
        self.assertEqual(advanced, '🔵 ADVANCED\n06:00–08:00')

    def test_sunrise_up_and_sunset_down_use_only_complete_hours(self):
        for rise, setting, first, last in (
                ((5, 48), (18, 12), 6, 18),
                ((6, 0), (18, 0), 6, 18),
                ((5, 1), (18, 59), 6, 18),
                ((6, 1), (18, 59), 7, 18)):
            with self.subTest(sunrise=rise, sunset=setting):
                self.day['sunlight'] = {'sunrise_ts': self.base + rise[0] * 3600 + rise[1] * 60,
                                        'sunset_ts': self.base + setting[0] * 3600 + setting[1] * 60}
                intervals = daylight_intervals(self.day)
                self.assertEqual(intervals[0]['start'], self.base + first * 3600)
                self.assertEqual(intervals[-1]['end'], self.base + last * 3600)
                self.assertTrue(all(i['end'] - i['start'] == 3600 for i in intervals))

    def test_no_complete_daylight_hour_withholds_report(self):
        self.day['sunlight'] = {'sunrise_ts': self.base + 6 * 3600 + 60,
                                'sunset_ts': self.base + 6 * 3600 + 59 * 60}
        with self.assertRaisesRegex(ValueError, 'No complete daylight hour'):
            render_day(self.day, 'Test')

    def test_good_conditions_show_only_times_and_night_conditions_add_no_cautions(self):
        self.day['sunlight'] = {'sunrise_ts': self.base + 5 * 3600 + 48 * 60,
                                'sunset_ts': self.base + 18 * 3600 + 12 * 60}
        for hour in list(range(6)) + list(range(18, 24)):
            self.day['hourly'][hour].update(row(10, 5000, 25, 50))
        with patch('recommendations.tide_at', return_value=TIDE):
            blocks = render_day(self.day, 'Test')
        self.assertEqual(blocks, ['Forecast date: 30 October 2026\n\n📍TEST',
                                 '🟢 BEGINNER\n06:00–18:00',
                                 '🟡 INTERMEDIATE\n06:00–18:00',
                                 '🔵 ADVANCED\n06:00–18:00'])

    def test_bold_entities_use_utf16_offsets_after_draft_prefix_and_emoji(self):
        text = 'DRAFT 2026-10-30 v2 (1/1)\n\n🌊\nForecast date: 30 October 2026\n\n📍TEST\n\n🟢 BEGINNER\n06:00–09:00 — Inside break'
        encoded = text.encode('utf-16-le')
        highlighted = [encoded[e['offset'] * 2:(e['offset'] + e['length']) * 2].decode('utf-16-le')
                       for e in report_bold_entities(text)]
        self.assertEqual(highlighted, ['Forecast date: 30 October 2026', '📍TEST', '🟢 BEGINNER'])


if __name__ == '__main__':
    unittest.main()
