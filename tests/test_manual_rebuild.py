import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
import test_review_bot as existing
from review_bot import Store


class ManualRebuild(unittest.TestCase):
    def setUp(self):
        existing.ReviewTests.setUp(self)
        fixture = json.loads((Path(__file__).parent / 'fixtures/november_2_2026.json').read_text())
        self.bot.s['reports'].clear()
        self.bot.s['started'] = True
        self.bot.generate(fixture['date'], fixture['forecast'], fixture['name'])
        self.report = self.bot.s['reports'][fixture['date']]
        self.bot.advance('2026-11-01')
        self.report['feedback'] = 'remove windy hours change'
        self.report['feedback_log'] = [dict(user_id=42, text='keep cautions short change'), dict(user_id=42, text='remove windy hours change')]
        self.report['parts'] = ['Forecast date: 2 November 2026\n📍OLD MAN\'S / BATU BOLONG\nOLD CORRECTED REPORT']
        self.original = copy.deepcopy(self.report)
        self.bot.forecast = Mock(side_effect=AssertionError('Must use saved forecast'))
        self.tg.reset_mock()

    def reopen(self):
        self.assertTrue(self.bot.reopen_published('2026-11-02', '2026-11-01', '909090'))
        return self.bot.s['reports']['2026-11-02']

    def test_rebuild_archives_feedback_and_reapplies_before_fresh_review(self):
        report = self.reopen()
        self.assertIn('All day is surfable', '\n'.join(report['parts']))
        self.assertEqual(report['review_history'][-1], self.original)
        self.assertEqual(report['rebuild_feedback'], ['keep cautions short change', 'remove windy hours change'])
        self.assertTrue(Store(self.path).data['reports']['2026-11-02']['memory_pending'])
        self.tg.assert_not_called()
        self.llm.return_value = report['parts'][:]
        self.bot.advance('2026-11-01')
        self.assertIn('take priority over ALL', self.llm.call_args.args[1])
        self.assertEqual(report['status'], 'review')
        self.assertNotIn('approval', report)
        self.assertFalse(report['memory_pending'])
        self.assertEqual(report['forecast'], self.original['forecast'])
        self.bot.forecast.assert_not_called()
        self.llm.reset_mock()
        self.bot.advance('2026-11-01')
        self.llm.assert_not_called()

    def test_failed_reapplication_keeps_rebuild_retryable_without_draft_delivery(self):
        report = self.reopen()
        self.llm.side_effect = RuntimeError('model unavailable')
        with self.assertRaises(RuntimeError):
            self.bot.advance('2026-11-01')
        self.assertTrue(report['memory_pending'])
        self.assertEqual(report['draft_ids'], [])
        self.assertEqual(report['prompt_ids'], [])
        self.assertEqual(report['review_history'][-1], self.original)
        self.assertNotIn('approval', report)

    def test_published_report_also_rebuilds_saved_source_and_archives(self):
        self.report['status'] = 'published'
        original = copy.deepcopy(self.report)
        report = self.reopen()
        self.assertEqual(report['publication_history'][-1], original)
        self.assertTrue(report['memory_pending'])
        self.assertIn('All day is surfable', '\n'.join(report['parts']))
        self.bot.forecast.assert_not_called()
