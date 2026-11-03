import unittest
from review_bot import display_12_hour


class TimeDisplay(unittest.TestCase):
    def test_midnight_noon_and_windy_range(self):
        self.assertEqual(display_12_hour('00:00 06:07 12:00 13:00 - 15:00 23:59'),
                         '12:00 AM 6:07 AM 12:00 PM 1:00 PM - 3:00 PM 11:59 PM')

    def test_idempotent_and_dates_unchanged(self):
        text = 'Forecast date: 4 November 2026\n13:00–15:00 — windy'
        rendered = display_12_hour(text)
        self.assertEqual(display_12_hour(rendered), rendered)
        self.assertIn('4 November 2026', rendered)
        self.assertEqual(display_12_hour('1:00 PM - 3:00 PM'), '1:00 PM - 3:00 PM')
