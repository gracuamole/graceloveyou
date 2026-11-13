import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from report_reasoning import explanation
from review_bot import Review, SafeError, Store, scoped_revision


class ReleaseEight(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'state.json'
        path.write_text(json.dumps(dict(version=1, started=True, offset=0, reports={})))
        self.store = Store(path)
        self.tg = Mock()
        self.tg.call.side_effect = lambda *args, **kwargs: {'message_id': self.tg.call.call_count}
        self.bot = Review(self.store, self.tg, 11, -200, -300, owner=12, bot_username='ReviewBot')
        fixture = Path(__file__).parent / 'fixtures/november_1_2026.json'
        sample = json.loads(fixture.read_text())
        self.date = sample['date']
        self.bot.generate(self.date, sample['forecast'], sample['name'])
        self.report = self.bot.s['reports'][self.date]
        timer = patch('review_bot.time.sleep')
        timer.start()
        self.addCleanup(timer.stop)

    def message(self, text, reply=None, chat=-200):
        return {'update_id': 88, 'message': {'text': text, 'from': {'id': 12},
                'chat': {'type': 'supergroup', 'id': chat}, 'reply_to_message': {'message_id': reply}}}

    def test_saved_reasoning_is_read_only_and_survives_restart(self):
        snapshot = self.report['generation_reasoning']
        for evidence in ('400 kJ', '0.8 m', 'half up', 'rounded up', 'Wave height:', 'BEGINNER',
                         'INTERMEDIATE', 'ADVANCED', 'Cautions', 'Borderline calls:', '07:00–10:00'):
            self.assertIn(evidence, snapshot)
        del self.report['forecast']
        self.store.save()
        bot = Review(Store(self.store.path), self.tg, 11, -200, -300, owner=12, bot_username='ReviewBot')
        with patch('review_bot.capture', side_effect=AssertionError('reconstruction')):
            before = deepcopy(bot.s['reports'])
            self.assertEqual(bot.process(self.message('/why@ReviewBot ' + self.date), '2026-10-31'), 'why_requested')
            bot.drain_outbox(why_only=True)
            self.assertTrue(self.tg.call.called)
            self.assertTrue(all(c.kwargs['chat_id'] == -200 for c in self.tg.call.call_args_list))
            self.assertEqual(bot.s['reports'], before)
            self.assertEqual(bot.process(self.message('/why', chat=-222), '2026-10-31'), 'ignored_unauthorized')

    def test_missing_legacy_and_latest_lookup(self):
        reports = {'2026-10-31': {}, self.date: self.report}
        self.assertIn(self.report['generation_reasoning'], explanation(reports))
        self.assertIn('not saved', explanation(reports, '2026-10-31'))
        self.assertIn('No saved report', explanation(reports, '2020-01-01'))
        self.assertIn('no saved reports', explanation({}))

    def test_mixed_case_requires_current_prompt_and_whole_message(self):
        self.bot.advance('2026-10-31')
        prompt = self.report['prompt_ids'][-1]
        for text in (' Correct', 'Correct.', 'correct now', 'CORRECT\n'):
            self.assertEqual(self.bot.process(self.message(text, prompt), '2026-10-31'), 'ignored_text')
        self.assertEqual(self.bot.process(self.message('CORRECT', prompt+10), '2026-10-31'), 'ignored_stale_prompt')
        self.assertEqual(self.bot.process(self.message('cOrReCt', prompt), '2026-10-31'), 'approved')
        self.assertEqual(self.bot.process(self.message('Correct', prompt), '2026-10-31'), 'ignored_not_reviewing')

    def test_exact_line_edit_preserves_all_other_words_and_spacing(self):
        feedback = 'Replace BATU BOLONG with Batu Bolong change'
        old = self.report['parts'][0]
        line = old.split('\n').index('🟢 BATU BOLONG')
        edit = dict(part=0, line=line, old='🟢 BATU BOLONG', new=['🟢 Batu Bolong'], request=feedback)
        with patch('review_bot.gemini_request', side_effect=[json.dumps([edit]), 'OK']):
            revised = scoped_revision(self.report, feedback)
        self.assertEqual(revised, [old.replace(edit['old'], edit['new'][0])] + self.report['parts'][1:])
        for invalid in ([dict(edit, old='wrong anchor')], [edit, edit], [dict(edit, request='invented request')]):
            with patch('review_bot.gemini_request', return_value=json.dumps(invalid)), self.assertRaises(SafeError):
                scoped_revision(self.report, feedback)
        rejected = dict(edit, new=['🟢 Batu Bolong surf report'])
        with patch('review_bot.gemini_request', side_effect=[
                json.dumps([rejected]), 'REJECT', json.dumps([edit]), 'OK']) as model:
            self.assertEqual(scoped_revision(self.report, feedback), revised)
            retry = json.loads(model.call_args_list[2].args[1])
            self.assertEqual(retry['draft'][0], old.split('\n'))
            self.assertIn('unrelated', retry['validation_feedback'])
            self.assertIn(rejected['new'][0], retry['rejected_edit'][0])
        with patch('review_bot.gemini_request', side_effect=[json.dumps([edit]), 'REJECT'] * 2) as model:
            with self.assertRaisesRegex(SafeError, 'exceeded or missed'):
                scoped_revision(self.report, feedback)
            self.assertEqual(model.call_count, 4)
        self.assertEqual(self.report['parts'][0], old)

    def test_reasoning_distinguishes_saved_reviewer_edit_from_forecast(self):
        before = self.report['generation_reasoning']
        self.bot.advance('2026-10-31')
        prompt = self.report['prompt_ids'][-1]
        outcome = self.bot.process(self.message('note: Bring a longboard change', prompt), '2026-10-31')
        self.assertEqual(outcome, 'note_pending')
        self.bot.advance('2026-10-31')
        self.assertEqual(self.report['generation_reasoning'], before)
        text = explanation(Store(self.store.path).data['reports'])
        self.assertIn('Reviewer changes since generation', text)
        self.assertIn('Bring a longboard', text)
        self.assertNotIn('Bring a longboard', before)

    def test_pending_change_blocks_uppercase_approval(self):
        self.bot.advance('2026-10-31')
        prompt = self.report['prompt_ids'][-1]
        self.bot.process(self.message('shorten location change', prompt), '2026-10-31')
        self.assertEqual(self.bot.process(self.message('CORRECT', prompt), '2026-10-31'), 'revision_approval_blocked')
        self.assertNotIn('approval', self.report)

    def test_invalid_edits_save_capped_proposals_and_specific_retry_feedback(self):
        feedback = 'shorten location change'
        for bad, category in [
                ('x' * 2500, 'unparseable JSON'),
                (json.dumps([dict(part=0,line=0,old='wrong',new=[],request='location')]), 'old-line mismatch'),
                (json.dumps([dict(part=0,line=0,old=self.report['parts'][0].splitlines()[0],
                                  new=[],request='not supplied')]), 'request not in feedback'),
                ('{}', 'other')]:
            with self.subTest(category=category), patch('review_bot.gemini_request',
                    side_effect=[bad, '[]', 'ok!']) as model:
                self.assertEqual(scoped_revision(self.report, feedback), self.report['parts'])
                self.assertEqual(model.call_count, 3)
                failure = self.report['edit_failures'][-1]
                self.assertEqual(failure['reason'], category)
                self.assertEqual(failure['proposed_edit'], bad[:2000])
                self.assertEqual(failure['truncated'], len(bad) > 2000)
                self.assertIn(category, json.loads(model.call_args_list[1].args[1])['validation_feedback'])

    def test_checker_budget_survives_restart_and_cancel_is_whole_message(self):
        today = '2026-10-31'
        self.bot.advance(today)
        target = self.report['draft_ids'][0]
        self.bot.process(self.message('keep it short change', target), today)
        with patch('review_bot.gemini_request', side_effect=['[]','OK eventually','[]','unknown']) as model:
            with self.assertRaisesRegex(SafeError, 'checker REJECT'):
                self.bot.advance(today)
            self.assertEqual(model.call_count, 4)
        store = Store(self.store.path)
        bot = Review(store, self.tg, 11, -200, -300, owner=12, bot_username='ReviewBot')
        report = bot.s['reports'][self.date]
        self.assertEqual(report['feedback_log'][-1]['reply_to_message_id'], target)
        self.assertEqual(report['pending_feedback'][0]['ai_calls'], 4)
        self.assertEqual([f['reason'] for f in report['edit_failures']], ['checker REJECT']*2)
        self.assertEqual(report['status'], 'revision_pending')
        self.assertEqual(bot.process(self.message('Retry', report['failure_ids'][-1]), today), 'revision_retry')
        with patch('review_bot.gemini_request') as model:
            with self.assertRaisesRegex(SafeError, 'Four AI calls'):
                bot.advance(today)
            model.assert_not_called()
        failure = report['failure_ids'][-1]
        for command in (' Cancel Change', 'CANCEL CHANGE!', 'CANCEL CHANGE\n'):
            self.assertEqual(bot.process(self.message(command, failure), today), 'ignored_stale_prompt')
        self.assertEqual(bot.process(self.message('CaNcEl ChAnGe', failure), today), 'revision_cancelled')
        self.assertNotIn('pending_feedback', report)

    def test_checker_verdict_allows_only_ok_with_trailing_punctuation(self):
        from review_bot import checker_ok
        for verdict in ('ok', 'oK.', ' OK! ', 'Ok…'):
            self.assertTrue(checker_ok(verdict))
        for verdict in ('OK, except', 'not OK', 'OK2', '!OK', '', 'reject.'):
            self.assertFalse(checker_ok(verdict))

    def test_checker_transport_failure_saves_edit_without_validation_retry(self):
        with patch('review_bot.gemini_request', side_effect=['[]', SafeError('Gemini revision HTTP 429')]) as model:
            with self.assertRaisesRegex(SafeError, '429'):
                scoped_revision(self.report, 'shorten location change')
            self.assertEqual(model.call_count, 2)
            failure = self.report['edit_failures'][-1]
            self.assertEqual(failure['proposed_edit'], '[]')
            self.assertEqual(failure['reason'], 'other')
            self.assertIn('429', failure['detail'])
