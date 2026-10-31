import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from review_bot import (Review, Store, Telegram, SafeError, failure_detail, http_failure,
                        setting, digest, revise, validate_parts, validate_revision_text, main)
from forecast_sources import Forecast, SourceUnavailable
from datetime import datetime
from recommendations import BALI, clean_report_text

TODAY, TARGET = '2026-10-29', '2026-10-30'


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.path.write_text(json.dumps(dict(version=1, reports={}, offset=0, started=False)))
        self.store = Store(self.path)
        self.tg = Mock()
        self.counter = 100
        def call(method, **kwargs):
            if method == 'sendMessage':
                self.counter += 1
                return {'message_id': self.counter}
            return []
        self.tg.call.side_effect = call
        self.llm = Mock(return_value=[TARGET + ' revised report'])
        self.bot = Review(self.store, self.tg, 42, 42, -100, self.llm)
        self.report = dict(date=TARGET, forecast={}, parts=[TARGET + ' surf report', 'part two'],
                           revision=1, status='draft', draft_ids=[], prompt_ids=[])
        self.bot.s['reports'][TARGET] = self.report
        self.sleep = patch('review_bot.time.sleep').start()
        self.addCleanup(patch.stopall)

    def draft(self):
        self.bot.advance(TODAY)
        self.assertEqual(self.report['status'], 'review')

    def update(self, text='correct', **overrides):
        message = dict(text=text, chat={'id': 42, 'type': 'private'},
                       **{'from': {'id': 42}},
                       reply_to_message={'message_id': self.report['prompt_ids'][-1]})
        message.update(overrides)
        return {'update_id': 5, 'message': message}

    def published(self):
        return [c for c in self.tg.call.call_args_list if c.args[0] == 'sendMessage'
                and c.kwargs['chat_id'] == -100]

    def test_reply_outcomes_explain_silence_without_changing_rules(self):
        self.draft()
        self.assertEqual(self.bot.process(self.update('fix wind change', reply_to_message={}), TODAY),
                         'ignored_unthreaded')
        self.assertEqual(self.bot.process(self.update(reply_to_message={'message_id': 0}), TODAY),
                         'ignored_stale_prompt')
        self.assertEqual(self.bot.process(self.update('Correct'), TODAY), 'ignored_text')
        self.assertEqual(self.bot.process(self.update(), TARGET), 'ignored_expired')
        self.assertEqual(self.report['status'], 'review')
        self.assertFalse(self.published())
        self.assertEqual(self.bot.process(self.update('fix wind change'), TODAY), 'revision_pending')
        self.assertEqual(self.bot.process(self.update(), TODAY), 'ignored_not_reviewing')

    def test_status_cli_is_read_only_and_excludes_private_content(self):
        self.report['feedback'] = 'PRIVATE_FEEDBACK_SECRET'
        self.store.save()
        before = self.path.read_bytes()
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'review_bot.py'),
                                 '--status', '--state', str(self.path)],
                                capture_output=True, text=True, env={})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Bali date:', result.stdout)
        self.assertNotIn('PRIVATE_FEEDBACK_SECRET', result.stdout)
        self.assertEqual(self.path.read_bytes(), before)
        self.tg.call.assert_not_called()

    def test_approved_content_once_after_restart(self):
        self.draft()
        self.assertFalse(self.published())
        self.bot.process(self.update(), TODAY)
        self.store.save()
        restarted = Review(Store(self.path), self.tg, 42, 42, -100, self.llm)
        restarted.advance(TODAY)
        restarted.advance(TODAY)
        self.assertEqual([c.kwargs['text'] for c in self.published()], self.report['parts'])

    def test_exact_authorization_and_latest_prompt(self):
        self.draft()
        for text in ('Correct', ' correct', 'correct\n', 'yes correct', 'correct change'):
            update = self.update(text)
            if text.endswith('change'):
                update['message']['reply_to_message']['message_id'] = 0
            self.bot.process(update, TODAY)
            self.assertEqual(self.report['status'], 'review')
        for override in ({'from': {'id': 99}}, {'chat': {'id': 99, 'type': 'private'}},
                         {'chat': {'id': 42, 'type': 'group'}},
                         {'reply_to_message': {'message_id': 0}},
                         {'forward_origin': {'type': 'user'}}):
            self.bot.process(self.update(**override), TODAY)
            self.assertEqual(self.report['status'], 'review')
        self.assertFalse(self.published())

    def test_feedback_loop_stale_and_duplicate_approval(self):
        self.draft()
        old = self.update()
        self.bot.process(self.update('Wind is 15 km/h change'), TODAY)
        self.store.save()
        self.bot.advance(TODAY)
        self.llm.assert_called_once()
        self.assertEqual(self.report['revision'], 2)
        self.assertEqual(self.report['status'], 'review')
        self.bot.process(old, TODAY)
        self.assertEqual(self.report['status'], 'review')
        self.bot.process(self.update(), TODAY)
        self.bot.advance(TODAY)
        self.bot.process(self.update(), TODAY)
        self.bot.advance(TODAY)
        self.assertEqual(len(self.published()), 1)
        self.assertEqual(self.published()[0].kwargs['text'], TARGET + ' revised report')

    def test_llm_failure_keeps_feedback_retryable(self):
        self.draft()
        self.bot.process(self.update('Change tide to high change'), TODAY)
        self.store.save()
        self.llm.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            self.bot.advance(TODAY)
        self.assertEqual(Store(self.path).data['reports'][TARGET]['status'], 'revision_pending')
        self.assertFalse(self.published())

    def test_timeout_never_automatically_resends(self):
        self.draft()
        self.bot.process(self.update(), TODAY)
        self.store.save()
        self.tg.call.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.bot.advance(TODAY)
        restarted = Review(Store(self.path), self.tg, 42, 42, -100)
        self.tg.reset_mock()
        with self.assertRaises(RuntimeError):
            restarted.advance(TODAY)
        self.tg.call.assert_not_called()

    def test_checkpoint_failure_prevents_send(self):
        self.store.save = Mock(side_effect=RuntimeError('push failed'))
        with self.assertRaises(RuntimeError):
            self.bot.advance(TODAY)
        self.tg.call.assert_not_called()

    def test_approval_hash_tampering_blocks_publication(self):
        self.draft()
        self.bot.process(self.update(), TODAY)
        self.report['parts'][0] = 'tampered'
        with self.assertRaises(ValueError):
            self.bot.advance(TODAY)
        self.assertFalse(self.published())

    def test_expired_draft_cannot_publish(self):
        self.draft()
        self.bot.process(self.update(), TARGET)
        self.bot.advance(TARGET)
        self.assertEqual(self.report['status'], 'expired')
        self.assertFalse(self.published())

    def test_poll_offset_persists_unauthorized_and_start(self):
        self.tg.call.side_effect = None
        self.tg.call.return_value = [dict(update_id=2, message={}), dict(update_id=3, message={
            'from': {'id': 42}, 'chat': {'id': 42, 'type': 'private'}, 'text': '/start'})]
        self.bot.poll(TODAY)
        data = Store(self.path).data
        self.assertEqual(data['offset'], 4)
        self.assertTrue(data['started'])
        self.tg.call.reset_mock()
        self.bot.poll(TODAY)
        self.tg.call.assert_called_once_with('getUpdates', offset=4, timeout=0,
                                            allowed_updates=['message'], limit=100)

    def test_configuration_and_missing_state_fail_closed(self):
        with self.assertRaises(ValueError):
            Review(self.store, self.tg, 43, 43, -100)
        with self.assertRaises(ValueError):
            Review(self.store, self.tg, 42, -42, -100)
        with self.assertRaises(FileNotFoundError):
            Store(self.path.parent / 'missing.json')

    def test_llm_response_contract_and_no_secrets_in_input(self):
        response = Mock()
        response.json.return_value = {'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': TARGET + ' fixed'}]}]}
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openai', 'OPENAI_API_KEY': 'secret', 'OPENAI_MODEL': 'test-model'}), \
                patch.dict('sys.modules', {'requests': Mock(post=Mock(return_value=response))}) as modules:
            post = modules['requests'].post
            self.assertEqual(revise(self.report, 'fix wind change'), [TARGET + ' fixed'])
            payload = post.call_args.kwargs['json']
            self.assertNotIn('secret', payload['input'])
            self.assertFalse(payload['store'])
            response.json.return_value['status'] = 'incomplete'
            with self.assertRaises(RuntimeError):
                revise(self.report, 'fix wind change')

    def test_prompt_checkpoint_is_already_reviewable(self):
        self.draft()
        persisted = Store(self.path).data['reports'][TARGET]
        self.assertEqual(persisted['status'], 'review')
        self.assertEqual(persisted['prompt_ids'], self.report['prompt_ids'])
        self.assertNotIn('intent', persisted)

    def test_only_report_and_final_prompt_are_delivered_in_order(self):
        r = json.loads((Path(__file__).parent / 'fixtures/november_1_2026.json').read_text())
        self.bot.s['reports'].clear()
        self.bot.generate(r['date'], r['forecast'], r['name'])
        self.report = self.bot.s['reports'][r['date']]
        self.bot.advance('2026-10-31')
        calls = [c for c in self.tg.call.call_args_list if c.args[0] == 'sendMessage']
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].kwargs['text'].startswith('DRAFT'))
        self.assertTrue(calls[1].kwargs['text'].startswith('Review'))
        self.assertTrue(all(c.kwargs['chat_id'] == 42 for c in calls))
        for heading in ('DETAILED SURF ANALYSIS', 'SURFLINE DATA SUMMARY', 'PRIVATE REVIEW'):
            self.assertFalse(any(heading in c.kwargs['text'] for c in calls))
        self.assertNotIn('analysis_parts', self.report)
        self.assertNotIn('source_parts', self.report)
        self.bot.process(self.update(), '2026-10-31')
        self.assertNotIn('review_sha256', self.report['approval'])
        self.store.save()
        restarted = Review(Store(self.path), self.tg, 42, 42, -100)
        restarted.advance('2026-10-31')
        restarted.advance('2026-10-31')
        self.assertEqual([c.kwargs['text'] for c in self.published()], self.report['parts'])

    def legacy_context(self):
        from review_bot import context_input_hash, review_hash
        self.report.update(analysis_parts=['Old private analysis'], source_parts=['Old private data'],
                           analysis_ids=[201], source_ids=[202])
        self.report['context_input_sha256'] = context_input_hash(self.report)
        self.report['context_content_sha256'] = digest([self.report['analysis_parts'], self.report['source_parts']])
        return review_hash(self.report)

    def test_sender_loads_without_the_retired_evidence_generator(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-c',
            'import sys; sys.modules["review_context"] = None; import review_bot; review_bot.main()'],
            cwd=root, env={}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Preview: no network or messages', result.stdout)

    def test_legacy_pending_review_needs_no_optional_context_or_replacement_prompt(self):
        self.report.update(status='review', draft_ids=[71, 72], prompt_ids=[73],
                           analysis_parts=['Old analysis'], source_parts=['Old data'],
                           analysis_ids=[], source_ids=[])
        before = json.dumps(self.report, sort_keys=True)
        self.bot.advance(TODAY)
        self.tg.call.assert_not_called()
        self.assertEqual(json.dumps(self.report, sort_keys=True), before)
        self.assertEqual(self.bot.process(self.update(), TODAY), 'approved')
        self.assertNotIn('review_sha256', self.report['approval'])
        self.bot.advance(TODAY)
        self.assertEqual([c.kwargs['text'] for c in self.published()], self.report['parts'])

    def test_partial_legacy_optional_delivery_is_skipped_and_only_prompt_is_sent(self):
        self.report.update(draft_ids=[71, 72])
        self.legacy_context()
        self.report['source_ids'] = []
        self.bot.advance(TODAY)
        self.assertEqual(self.tg.call.call_count, 1)
        self.assertTrue(self.tg.call.call_args.kwargs['text'].startswith('Review'))
        self.assertEqual(self.report['analysis_ids'], [201])
        self.assertFalse(self.report['source_ids'])
        self.assertEqual(self.bot.process(self.update(), TODAY), 'approved')
        self.assertFalse(self.published())

    def test_old_optional_send_intent_still_requires_reconciliation(self):
        self.report['intent'] = {'kind': 'analysis', 'text_sha256': 'unknown'}
        self.store.save()
        with self.assertRaisesRegex(RuntimeError, 'Uncertain send'):
            self.bot.advance(TODAY)
        with self.assertRaisesRegex(RuntimeError, 'Uncertain send'):
            self.bot.reopen_published(TARGET, TODAY, '12345')
        self.tg.call.assert_not_called()
        self.assertEqual(Store(self.path).data['reports'][TARGET]['intent']['kind'], 'analysis')

    def test_retired_message_types_cannot_be_sent(self):
        for kind in ('analysis', 'source'):
            with self.assertRaisesRegex(SafeError, 'Only report'):
                self.bot.send(self.report, kind, 'No longer sent')
        self.tg.call.assert_not_called()
        self.assertNotIn('intent', self.report)

    def test_feedback_can_reply_to_report_but_old_notes_cannot_approve_or_revise(self):
        self.draft()
        self.legacy_context()
        for kind in ('analysis', 'source'):
            for feedback in ('correct', 'fix wind change'):
                self.assertEqual(self.bot.process(self.update(feedback, reply_to_message={
                    'message_id': self.report[kind + '_ids'][0]}), TODAY), 'ignored_stale_prompt')
        self.assertEqual(self.bot.process(self.update(reply_to_message={
            'message_id': self.report['draft_ids'][0]}), TODAY), 'ignored_approval_not_prompt')
        self.assertEqual(self.bot.process(self.update('fix the conditions change', reply_to_message={
            'message_id': self.report['draft_ids'][0]}), TODAY), 'revision_pending')
        self.tg.reset_mock()
        self.bot.advance(TODAY)
        self.assertEqual(self.tg.call.call_count, 2)
        self.assertNotIn('analysis_parts', self.report)
        self.assertNotIn('source_parts', self.report)
        self.assertFalse(self.published())

    def test_old_recorded_bundle_approval_resumes_with_only_report_publication(self):
        self.draft()
        old_hash = self.legacy_context()
        self.bot.process(self.update(), TODAY)
        self.report['approval']['review_sha256'] = old_hash
        self.store.save()
        self.tg.reset_mock()
        restarted = Review(Store(self.path), self.tg, 42, 42, -100)
        restarted.advance(TODAY)
        self.assertEqual([c.kwargs['text'] for c in self.published()], self.report['parts'])
        self.assertEqual(self.tg.call.call_count, 2)

    def test_old_recorded_bundle_hash_is_still_checked_before_publication(self):
        self.draft()
        old_hash = self.legacy_context()
        self.bot.process(self.update(), TODAY)
        self.report['approval']['review_sha256'] = old_hash
        self.report['source_parts'][0] += ' altered after approval'
        with self.assertRaisesRegex(ValueError, 'Approval does not match'):
            self.bot.advance(TODAY)
        self.assertFalse(self.published())

    def test_new_approvals_are_not_blocked_by_retired_optional_metadata(self):
        self.draft()
        self.legacy_context()
        self.report['analysis_parts'][0] += ' old notes are no longer required'
        self.report['source_ids'] = []
        self.assertEqual(self.bot.process(self.update(), TODAY), 'approved')
        self.assertNotIn('review_sha256', self.report['approval'])
        self.bot.advance(TODAY)
        self.assertEqual([c.kwargs['text'] for c in self.published()], self.report['parts'])

    def test_incomplete_report_must_finish_before_approval(self):
        self.report.update(status='review', draft_ids=[71], prompt_ids=[73])
        self.assertEqual(self.bot.process(self.update(), TODAY), 'ignored_draft_pending')
        self.assertNotIn('approval', self.report)
        self.bot.advance(TODAY)
        self.assertEqual(self.tg.call.call_count, 2)
        self.assertIn('part two', self.tg.call.call_args_list[0].kwargs['text'])
        self.assertTrue(self.tg.call.call_args_list[1].kwargs['text'].startswith('Review'))
        self.assertFalse(self.published())
        self.assertEqual(self.bot.process(self.update(), TODAY), 'approved')

    def test_private_review_headings_cannot_enter_an_llm_report(self):
        for heading in ('DETAILED SURF ANALYSIS', 'SURFLINE DATA SUMMARY', 'PRIVATE REVIEW'):
            with self.assertRaisesRegex(SafeError, 'mixed private review material'):
                validate_revision_text(self.report, 'tidy wording change', TARGET + '\n' + heading)

    def test_real_forecast_revision_sends_only_updated_report_and_prompt(self):
        r = json.loads((Path(__file__).parent / 'fixtures/november_1_2026.json').read_text())
        self.bot.s['reports'].clear()
        self.bot.generate(r['date'], r['forecast'], r['name'])
        self.report = self.bot.s['reports'][r['date']]
        self.bot.advance('2026-10-31')
        original_source = json.dumps(self.report['forecast'], sort_keys=True)
        old_prompt = self.report['prompt_ids'][0]
        self.llm.return_value = [self.report['parts'][0].replace('06:00–09:00', '06:00–08:00')]
        self.bot.process(self.update('remove 08:00–09:00 change', reply_to_message={
            'message_id': self.report['draft_ids'][0]}), '2026-10-31')
        self.tg.reset_mock()
        self.bot.advance('2026-10-31')
        self.assertEqual(self.tg.call.call_count, 2)
        self.assertIn('06:00–08:00', self.tg.call.call_args_list[0].kwargs['text'])
        self.assertTrue(self.tg.call.call_args_list[1].kwargs['text'].startswith('Review'))
        self.assertNotIn('analysis_parts', self.report)
        self.assertNotIn('source_parts', self.report)
        self.assertEqual(json.dumps(self.report['forecast'], sort_keys=True), original_source)
        self.assertEqual(self.bot.process(self.update(reply_to_message={'message_id': old_prompt}), '2026-10-31'),
                         'ignored_stale_prompt')
        self.assertFalse(self.published())
        self.bot.process(self.update(), '2026-10-31')
        self.bot.advance('2026-10-31')
        self.assertEqual([c.kwargs['text'] for c in self.published()], self.report['parts'])

    def test_multipart_report_finishes_before_the_final_approval_prompt(self):
        self.report['parts'] = ['🌊' * 1400] * 3
        self.draft()
        calls = self.tg.call.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(self.report['draft_ids']), 3)
        self.assertTrue(calls[-1].kwargs['text'].startswith('Review'))
        self.assertTrue(all(len(c.kwargs['text'].encode('utf-16-le')) // 2 <= 3400 for c in calls))
        self.assertEqual(self.bot.process(self.update(), TODAY), 'approved')
        self.assertFalse(self.published())

    def test_generate_target_is_never_replaced(self):
        original = self.report['parts'][:]
        self.bot.generate(TARGET, {}, 'ignored')
        self.assertEqual(self.report['parts'], original)

    def prepare_published_test(self):
        self.bot.s['started'] = True
        self.draft()
        self.bot.process(self.update(), TODAY)
        self.bot.advance(TODAY)
        self.bot.forecast = Mock(return_value=Forecast(
            TARGET, 'Test spot', {'fresh': True}, [TARGET + ' fresh short-format report']))
        self.tg.reset_mock()
        return json.loads(json.dumps(self.report))

    def run_workflow(self, flags=(), event='schedule', updates=()):
        def call(method, **kwargs):
            if method == 'getWebhookInfo':
                return {'url': ''}
            if method == 'getUpdates':
                return list(updates)
            self.counter += 1
            return {'message_id': self.counter}
        self.tg.call.side_effect = call
        with patch('sys.argv', ['review_bot.py', '--run', '--persist-git', *flags]), \
                patch('review_bot.Store', return_value=self.store), \
                patch('review_bot.Review', return_value=self.bot), \
                patch('review_bot.datetime', wraps=datetime) as clock, \
                patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'SECRET', 'LEO_TELEGRAM_USER_ID': '42',
                                         'LEO_TELEGRAM_CHAT_ID': '42', 'TELEGRAM_CHANNEL_ID': '-100',
                                         'SURF_REVIEW_TRANSPORT': 'poll', 'GITHUB_EVENT_NAME': event,
                                         'GITHUB_RUN_ID': '12345'}, clear=True):
            clock.now.return_value = datetime(2026, 10, 29, 12, tzinfo=BALI)
            main()

    def test_scheduled_and_webhook_dispatch_runs_leave_published_report_alone(self):
        previous = self.prepare_published_test()
        for event in ('schedule', 'workflow_dispatch'):
            with self.subTest(event=event):
                self.run_workflow(event=event)  # Worker dispatch has no resend flag.
                self.assertEqual(self.report, previous)
                self.assertFalse(self.published())
                self.assertFalse(any(c.args[0] == 'sendMessage' for c in self.tg.call.call_args_list))
                self.bot.forecast.assert_not_called()
                self.tg.reset_mock()

    def test_manual_test_archives_publication_before_sending_and_requires_fresh_approval(self):
        previous = self.prepare_published_test()
        old_prompt = previous['prompt_ids'][-1]
        self.assertTrue(self.bot.reopen_published(TARGET, TODAY, '12345'))
        saved = Store(self.path).data
        self.report = saved['reports'][TARGET]
        self.assertEqual(self.report['publication_history'], [previous])
        self.assertEqual(saved['manual_retest_requests'], {'12345': {'date': TARGET, 'revision': 2}})
        self.assertNotIn('approval', self.report)
        self.assertFalse(self.report.get('publish_ids'))
        self.tg.call.assert_not_called()  # Both the request and history are already durable.
        self.bot = Review(Store(self.path), self.tg, 42, 42, -100, self.llm)
        self.report = self.bot.s['reports'][TARGET]
        self.bot.advance(TODAY)
        self.assertEqual(self.report['status'], 'review')
        self.assertFalse(self.published())
        private = [c.kwargs['text'] for c in self.tg.call.call_args_list if c.args[0] == 'sendMessage']
        self.assertTrue(private[0].startswith('TEST DRAFT'))
        self.assertIn('already published', private[-1])
        self.assertIn('post this report to the channel again', private[-1])
        self.assertEqual(self.bot.process(self.update(reply_to_message={'message_id': old_prompt}), TODAY),
                         'ignored_stale_prompt')
        for text in ('Correct', ' correct', 'correct\n'):
            self.assertEqual(self.bot.process(self.update(text), TODAY), 'ignored_text')
        self.assertEqual(self.bot.process(self.update(), TODAY), 'approved')
        self.store = self.bot.store
        self.store.save()
        restarted = Review(Store(self.path), self.tg, 42, 42, -100, self.llm)
        restarted.advance(TODAY)
        restarted.advance(TODAY)
        self.assertEqual([c.kwargs['text'] for c in self.published()], [TARGET + ' fresh short-format report'])
        self.assertEqual(Store(self.path).data['reports'][TARGET]['publication_history'], [previous])
        self.llm.assert_not_called()

    def test_manual_request_id_prevents_duplicate_cycles_even_after_republication(self):
        self.prepare_published_test()
        self.bot.reopen_published(TARGET, TODAY, '12345')
        self.report = self.bot.s['reports'][TARGET]
        self.bot.advance(TODAY)
        self.bot.process(self.update(), TODAY)
        self.bot.advance(TODAY)
        restarted = Review(Store(self.path), self.tg, 42, 42, -100, self.llm)
        restarted.forecast = self.bot.forecast
        self.tg.reset_mock()
        self.assertFalse(restarted.reopen_published(TARGET, TODAY, '12345'))
        restarted.advance(TODAY)
        self.tg.call.assert_not_called()
        self.bot.forecast.assert_called_once_with(TARGET)
        self.assertTrue(restarted.reopen_published(TARGET, TODAY, '67890'))
        report = Store(self.path).data['reports'][TARGET]
        self.assertEqual(report['revision'], 3)
        self.assertEqual(len(report['publication_history']), 2)
        self.assertTrue(all('publication_history' not in old for old in report['publication_history']))
        self.assertTrue(all(old['publish_ids'] for old in report['publication_history']))

    def test_manual_test_sends_full_active_review_and_requires_a_new_approval(self):
        self.bot.s['started'] = True
        self.draft()
        previous = json.loads(json.dumps(self.report))
        old_prompt = previous['prompt_ids'][0]
        self.bot.forecast = Mock()
        self.tg.reset_mock()
        self.assertTrue(self.bot.reopen_published(TARGET, TODAY, '12345'))
        self.report = self.bot.s['reports'][TARGET]
        self.assertEqual(self.report['review_history'], [previous])
        self.assertFalse(self.report['publication_history'])
        self.assertEqual(self.report['revision'], previous['revision'] + 1)
        self.assertFalse(self.report.get('approval'))
        self.bot.advance(TODAY)
        texts = [c.kwargs['text'] for c in self.tg.call.call_args_list]
        self.assertEqual(len(texts), 3)  # Both report parts and the final prompt.
        self.assertTrue(texts[0].startswith('TEST DRAFT'))
        self.assertTrue(texts[1].startswith('TEST DRAFT'))
        self.assertIn('replaces an earlier pending draft', texts[2])
        self.assertNotIn('already published', texts[2])
        self.assertEqual(self.bot.process(self.update(reply_to_message={'message_id': old_prompt}), TODAY),
                         'ignored_stale_prompt')
        self.assertFalse(self.published())
        self.assertFalse(self.bot.reopen_published(TARGET, TODAY, '12345'))
        self.assertEqual(self.tg.call.call_count, 3)
        self.bot.process(self.update(), TODAY)
        self.bot.advance(TODAY)
        self.bot.advance(TODAY)
        self.assertEqual([c.kwargs['text'] for c in self.published()], self.report['parts'])
        self.bot.forecast.assert_not_called()

    def test_manual_repeat_refreshes_an_unedited_older_format_from_saved_forecast(self):
        r = json.loads((Path(__file__).parent / 'fixtures/november_1_2026.json').read_text())
        self.bot.s['reports'].clear()
        self.bot.s['started'] = True
        self.bot.generate(r['date'], r['forecast'], r['name'])
        self.report = self.bot.s['reports'][r['date']]
        self.report.update(status='review', parts=["Forecast date: 1 November 2026\n\n"
                           "📍OLD MAN'S / BATU BOLONG\n\n🟢 BEGINNER\n06:00–18:00 — Inside break only"],
                           draft_ids=[70], prompt_ids=[71])
        self.bot.forecast = Mock()
        self.assertTrue(self.bot.reopen_published(r['date'], '2026-10-31', '12345'))
        report = self.bot.s['reports'][r['date']]
        self.assertIn('06:00–09:00 — Inside break only, coach recommended', '\n'.join(report['parts']))
        self.assertIn('🟡 INTERMEDIATE\nNo qualifying window.', '\n'.join(report['parts']))
        self.assertIn('06:00–18:00', report['review_history'][0]['parts'][0])
        self.bot.advance('2026-10-31')
        self.assertEqual(self.tg.call.call_count, 2)
        self.assertFalse(self.published())
        self.bot.forecast.assert_not_called()

    def test_manual_repeat_preserves_reviewer_corrections_and_all_publication_history(self):
        original = self.prepare_published_test()
        self.bot.reopen_published(TARGET, TODAY, '12345')
        self.report = self.bot.s['reports'][TARGET]
        self.bot.advance(TODAY)
        self.bot.process(self.update('fix wind change'), TODAY)
        self.bot.advance(TODAY)
        corrected = self.report['parts'][:]
        self.bot.forecast.reset_mock()
        self.assertTrue(self.bot.reopen_published(TARGET, TODAY, '67890'))
        self.report = self.bot.s['reports'][TARGET]
        self.assertEqual(self.report['parts'], corrected)
        self.assertEqual(self.report['feedback'], 'fix wind change')
        self.assertEqual(self.report['publication_history'], [original])
        self.assertEqual(self.report['review_history'][0]['feedback'], 'fix wind change')
        self.assertEqual(self.report['status'], 'draft')
        self.bot.forecast.assert_not_called()

    def test_manual_repeat_defers_saved_feedback_without_discarding_it(self):
        self.draft()
        self.bot.process(self.update('correct the wind change'), TODAY)
        before = json.loads(json.dumps(self.report))
        self.bot.forecast = Mock()
        self.assertFalse(self.bot.reopen_published(TARGET, TODAY, '12345'))
        self.assertEqual(self.report, before)
        self.assertNotIn('manual_retest_requests', self.bot.s)
        self.bot.forecast.assert_not_called()

    def test_automated_runs_do_not_resend_a_complete_pending_review(self):
        self.bot.s['started'] = True
        self.draft()
        self.tg.reset_mock()
        for event in ('schedule', 'workflow_dispatch'):
            self.run_workflow(event=event)
            self.assertFalse(any(c.args[0] == 'sendMessage' for c in self.tg.call.call_args_list))
            self.assertEqual(self.report['status'], 'review')
            self.tg.reset_mock()

    def test_new_manual_cli_run_resends_a_review_from_an_earlier_manual_test(self):
        self.prepare_published_test()
        self.bot.reopen_published(TARGET, TODAY, '11111')
        self.report = self.bot.s['reports'][TARGET]
        self.bot.advance(TODAY)
        old_approval = self.update()
        self.tg.reset_mock()
        self.bot.forecast.reset_mock()
        self.run_workflow(('--resend-published',), 'workflow_dispatch', [old_approval])
        self.report = self.bot.s['reports'][TARGET]
        self.assertEqual(self.report['revision'], 3)
        self.assertEqual(self.report['manual_request_id'], '12345')
        self.assertEqual(self.report['status'], 'review')
        self.assertEqual(self.bot.s['last_update_outcome'], 'ignored_stale_prompt')
        sent = [c for c in self.tg.call.call_args_list if c.args[0] == 'sendMessage']
        self.assertEqual(len(sent), 2)
        self.assertTrue(sent[0].kwargs['text'].startswith('TEST DRAFT'))
        self.assertTrue(sent[1].kwargs['text'].startswith('Review'))
        self.assertTrue(all(c.kwargs['chat_id'] == 42 for c in sent))
        self.assertFalse(self.published())
        self.bot.forecast.assert_not_called()

    def test_manual_test_feedback_needs_another_fresh_prompt_and_approval(self):
        self.prepare_published_test()
        self.bot.reopen_published(TARGET, TODAY, '12345')
        self.report = self.bot.s['reports'][TARGET]
        self.bot.advance(TODAY)
        old_prompt = self.report['prompt_ids'][-1]
        self.bot.process(self.update('remove evening change'), TODAY)
        self.bot.advance(TODAY)
        self.assertEqual(self.report['revision'], 3)
        self.assertEqual(self.report['manual_request_id'], '12345')
        self.assertEqual(self.bot.process(self.update(reply_to_message={'message_id': old_prompt}), TODAY),
                         'ignored_stale_prompt')
        self.assertFalse(self.published())
        self.bot.process(self.update(), TODAY)
        self.bot.advance(TODAY)
        self.assertEqual([c.kwargs['text'] for c in self.published()], [TARGET + ' revised report'])

    def test_manual_test_fetch_failure_preserves_original_publication(self):
        previous = self.prepare_published_test()
        self.bot.forecast.side_effect = SourceUnavailable('Required forecast unavailable.')
        with self.assertRaises(SourceUnavailable):
            self.bot.reopen_published(TARGET, TODAY, '12345')
        self.assertEqual(Store(self.path).data['reports'][TARGET], previous)
        self.assertNotIn('manual_retest_requests', self.bot.s)
        self.assertFalse(self.published())

    def test_manual_test_refuses_uncertain_delivery_without_fetching(self):
        self.prepare_published_test()
        self.report['intent'] = {'kind': 'publish', 'text_sha256': 'unknown'}
        with self.assertRaisesRegex(RuntimeError, 'Uncertain send'):
            self.bot.reopen_published(TARGET, TODAY, '12345')
        self.bot.forecast.assert_not_called()
        self.tg.call.assert_not_called()

    def test_manual_test_checkpoint_failure_prevents_delivery(self):
        self.prepare_published_test()
        self.store.save = Mock(side_effect=RuntimeError('push failed'))
        with self.assertRaisesRegex(RuntimeError, 'push failed'):
            self.bot.reopen_published(TARGET, TODAY, '12345')
        self.tg.call.assert_not_called()
        self.assertEqual(Store(self.path).data['reports'][TARGET]['status'], 'published')

    def test_manual_test_timeout_keeps_history_and_stops_all_automatic_retries(self):
        previous = self.prepare_published_test()
        self.bot.reopen_published(TARGET, TODAY, '12345')
        self.tg.call.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.bot.advance(TODAY)
        restarted = Review(Store(self.path), self.tg, 42, 42, -100)
        self.tg.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'Uncertain send'):
            restarted.advance(TODAY)
        with self.assertRaisesRegex(RuntimeError, 'Uncertain send'):
            restarted.reopen_published(TARGET, TODAY, '67890')
        self.tg.call.assert_not_called()
        self.assertEqual(restarted.s['reports'][TARGET]['publication_history'], [previous])

    def test_manual_test_invalid_forecast_never_replaces_publication(self):
        previous = self.prepare_published_test()
        for snapshot in (Forecast(TODAY, 'Test', {}, ['wrong date']), Forecast(TARGET, 'Test', {}, [])):
            with self.subTest(date=snapshot.date, parts=snapshot.parts):
                self.bot.forecast.return_value = snapshot
                with self.assertRaises((SafeError, ValueError)):
                    self.bot.reopen_published(TARGET, TODAY, '12345')
                self.assertEqual(Store(self.path).data['reports'][TARGET], previous)
                self.assertNotIn('manual_retest_requests', self.bot.s)
                self.tg.call.assert_not_called()

    def test_manual_cli_reopens_before_processing_an_old_approval(self):
        previous = self.prepare_published_test()
        self.run_workflow(('--resend-published',), 'workflow_dispatch', [self.update()])
        report = self.bot.s['reports'][TARGET]
        self.assertEqual(report['status'], 'review')
        self.assertEqual(report['publication_history'], [previous])
        self.assertEqual(self.bot.s['last_update_outcome'], 'ignored_stale_prompt')
        self.assertFalse(self.published())
        self.bot.forecast.assert_called_once_with(TARGET)

    def test_manual_cli_rejects_scheduled_or_missing_run_context_before_network(self):
        for event, run_id in (('schedule', '12345'), ('', '12345'), ('workflow_dispatch', ''),
                              ('workflow_dispatch', 'invalid')):
            with self.subTest(event=event, run_id=run_id), \
                    patch('sys.argv', ['review_bot.py', '--run', '--persist-git', '--resend-published']), \
                    patch.dict('os.environ', {'GITHUB_EVENT_NAME': event, 'GITHUB_RUN_ID': run_id}, clear=True), \
                    patch('review_bot.Store') as store:
                with self.assertRaisesRegex(SafeError, 'explicit GitHub manual workflow run'):
                    main()
                store.assert_not_called()
        self.tg.call.assert_not_called()

    def test_second_active_report_is_rejected_before_fetching(self):
        self.bot.forecast = Mock()
        with self.assertRaisesRegex(SafeError, 'Another report is still active'):
            self.bot.generate_next_day('2026-10-31')
        self.bot.forecast.assert_not_called()
        self.assertEqual(list(self.bot.s['reports']), [TARGET])

    def test_private_status_command_survives_restart_and_duplicate_delivery(self):
        self.report['feedback'] = 'PRIVATE_FEEDBACK_SECRET'
        self.draft()
        before = digest(self.report['parts'])
        command = self.update('/status', reply_to_message={})
        self.tg.call.reset_mock()
        self.bot.consume_updates([command], TODAY)
        self.tg.call.assert_not_called()  # Queue/offset persist before any delivery.
        restarted = Review(Store(self.path), self.tg, 42, 42, -100, self.llm)
        restarted.advance(TODAY)
        restarted.consume_updates([command], TODAY)
        restarted.advance(TODAY)
        notices = [c for c in self.tg.call.call_args_list if c.args[0] == 'sendMessage']
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].kwargs['chat_id'], 42)
        self.assertIn('review', notices[0].kwargs['text'])
        self.assertNotIn('PRIVATE_FEEDBACK_SECRET', notices[0].kwargs['text'])
        self.assertEqual(digest(restarted.s['reports'][TARGET]['parts']), before)
        self.assertEqual(restarted.s['reports'][TARGET]['status'], 'review')

    def test_commands_from_other_users_never_queue_or_fetch(self):
        self.draft()
        self.bot.forecast = Mock()
        for command in ('/status', '/dryrun'):
            outcome = self.bot.process(self.update(command, **{'from': {'id': 9}}), TODAY)
            self.assertEqual(outcome, 'ignored_unauthorized')
        self.assertFalse(self.bot.s.get('outbox'))
        self.bot.forecast.assert_not_called()

    def test_dryrun_has_no_approval_cycle_or_llm_and_cannot_be_approved(self):
        self.draft()
        before = json.dumps(self.report, sort_keys=True)
        self.bot.forecast = Mock(return_value=Forecast(TARGET, 'Test', {}, [TARGET + ' preview']))
        self.bot.consume_updates([self.update('/dryrun', reply_to_message={})], TODAY)
        self.bot.advance(TODAY)
        self.bot.forecast.assert_called_once_with(TARGET)
        self.llm.assert_not_called()
        self.assertEqual(json.dumps(self.report, sort_keys=True), before)
        self.assertEqual(len(self.bot.s['reports']), 1)
        preview = self.bot.s['outbox']['dryrun:5']
        self.assertIn('REVIEW PREVIEW ONLY', preview['parts'][0])
        outcome = self.bot.process(self.update(reply_to_message={'message_id': preview['notice_ids'][0]}), TODAY)
        self.assertEqual(outcome, 'ignored_stale_prompt')
        self.assertFalse(self.published())

    def test_command_only_run_does_not_generate_daily_approval_cycle(self):
        self.bot.s['reports'].clear()
        self.bot.s['started'] = True
        command = {'update_id': 7, 'message': {'text': '/dryrun', 'from': {'id': 42},
                                             'chat': {'id': 42, 'type': 'private'}}}
        self.bot.forecast = Mock(return_value=Forecast(TARGET, 'Test', {}, [TARGET + ' preview']))
        self.bot.generate_next_day = Mock()
        self.tg.call.side_effect = lambda method, **kw: (
            {'url': ''} if method == 'getWebhookInfo' else [command] if method == 'getUpdates'
            else {'message_id': 999})
        with patch('sys.argv', ['review_bot.py', '--run', '--persist-git']), \
                patch('review_bot.Store', return_value=self.store), \
                patch('review_bot.Review', return_value=self.bot), \
                patch('review_bot.datetime', wraps=datetime) as clock, \
                patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'SECRET', 'LEO_TELEGRAM_USER_ID': '42',
                                         'LEO_TELEGRAM_CHAT_ID': '42', 'TELEGRAM_CHANNEL_ID': '-100',
                                         'SURF_REVIEW_TRANSPORT': 'poll'}, clear=True):
            clock.now.return_value = datetime(2026, 10, 29, 12, tzinfo=BALI)
            main()
        self.bot.generate_next_day.assert_not_called()
        self.assertFalse(self.bot.s['reports'])
        self.bot.forecast.assert_called_once_with(TARGET)

    def test_note_command_works_without_api_key_and_needs_fresh_approval(self):
        self.report['parts'][0] += (' | WITA\nSource: Surfline via surf-mcp. '
                                   'Check conditions locally; recommendations are not safety guarantees.')
        self.draft()
        old_prompt = self.report['prompt_ids'][-1]
        previous = self.report['parts'][:]
        outcome = self.bot.process(self.update('note: Ask a coach about the current change'), TODAY)
        self.assertEqual(outcome, 'note_pending')
        self.store.save()
        self.bot.advance(TODAY)
        self.llm.assert_not_called()
        revised = '\n\n'.join(self.report['parts'])
        self.assertTrue(revised.startswith(clean_report_text('\n\n'.join(previous))))
        for removed in ('WITA', 'Source: Surfline', 'recommendations are not safety guarantees'):
            self.assertNotIn(removed, revised)
        self.assertIn('Reviewer note (not Surfline data): Ask a coach about the current', revised)
        self.assertEqual(self.report['revision'], 2)
        self.assertFalse(self.published())
        self.assertEqual(self.bot.process(self.update(reply_to_message={'message_id': old_prompt}), TODAY),
                         'ignored_stale_prompt')
        self.bot.process(self.update(), TODAY)
        self.bot.advance(TODAY)
        self.assertEqual([c.kwargs['text'] for c in self.published()], self.report['parts'])

    def test_revision_failure_notice_once_and_feedback_can_be_replaced(self):
        self.draft()
        self.bot.s['started'] = True
        self.bot.process(self.update('fix wind change'), TODAY)
        self.store.save()
        self.llm.side_effect = SafeError('Gemini revision HTTP 429: Free quota exhausted.')
        self.tg.call.reset_mock()
        with self.assertRaises(SafeError):
            self.bot.advance(TODAY)
        with patch.object(self.store, 'save', wraps=self.store.save) as checkpoint:
            with self.assertRaises(SafeError):
                self.bot.advance(TODAY)
            checkpoint.assert_not_called()  # No empty Git commit on a repeated failure.
        notices = [c for c in self.tg.call.call_args_list if c.args[0] == 'sendMessage']
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].kwargs['chat_id'], 42)
        self.assertIn('429', notices[0].kwargs['text'])
        self.assertEqual(self.report['status'], 'revision_pending')
        self.assertEqual(self.bot.process(self.update(), TODAY), 'ignored_not_reviewing')
        self.bot.process(self.update('note: Coach to confirm wind change'), TODAY)
        self.store.save()
        self.bot.advance(TODAY)
        self.assertEqual(self.report['status'], 'review')
        self.assertEqual(self.report['revision'], 2)
        self.assertFalse(self.published())

    def test_private_notice_timeout_halts_all_later_delivery(self):
        self.draft()
        self.bot.consume_updates([self.update('/status', reply_to_message={})], TODAY)
        self.tg.call.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.bot.advance(TODAY)
        restarted = Review(Store(self.path), self.tg, 42, 42, -100, self.llm)
        self.assertEqual(restarted.s['outbox']['status:5']['intent']['kind'], 'notice')
        restarted.process(self.update(), TODAY)
        restarted.store.save()
        self.assertEqual(restarted.s['reports'][TARGET]['status'], 'approved')
        self.tg.call.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'Uncertain send'):
            restarted.advance(TODAY)
        self.tg.call.assert_not_called()
        self.assertFalse(self.published())

    def test_unknown_source_failure_sends_one_notice_without_creating_report(self):
        self.bot.s['reports'].clear()
        self.bot.s['started'] = True
        self.bot.forecast = Mock(side_effect=SourceUnavailable('Surfline required data unavailable.'))
        for attempt in range(2):
            with self.assertRaises(SourceUnavailable):
                self.bot.generate_next_day(TARGET)
        self.assertFalse(self.bot.s['reports'])
        self.llm.assert_not_called()
        self.assertEqual(self.tg.call.call_count, 1)
        self.assertEqual(self.tg.call.call_args.kwargs['chat_id'], 42)
        self.assertFalse(self.published())

    def test_failed_preview_does_not_mutate_active_report(self):
        self.draft()
        original = json.dumps(self.report, sort_keys=True)
        self.bot.forecast = Mock(side_effect=SourceUnavailable('Surfline unavailable.'))
        self.bot.consume_updates([self.update('/dryrun', reply_to_message={})], TODAY)
        self.bot.advance(TODAY)
        self.assertEqual(self.bot.s['outbox']['dryrun:5']['status'], 'sent')
        self.assertIn('Review preview failed', self.bot.s['outbox']['dryrun:5']['parts'][0])
        self.assertEqual(json.dumps(self.report, sort_keys=True), original)
        self.assertFalse(self.published())

    def test_draft_timeout_also_halts_without_publication(self):
        self.tg.call.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.bot.advance(TODAY)
        self.assertEqual(Store(self.path).data['reports'][TARGET]['intent']['kind'], 'draft')
        self.assertFalse(self.published())

    def test_git_checkpoints_reach_separate_repository(self):
        remote = Path(self.tmp.name) / 'remote.git'
        root = Path(self.tmp.name) / 'checkout'
        def git(*args):
            return subprocess.run(['git', *map(str, args)], check=True,
                                  capture_output=True, text=True).stdout
        git('init', '--bare', remote)
        git('init', '-b', 'review-state', root)
        git('-C', root, 'config', 'user.name', 'Test')
        git('-C', root, 'config', 'user.email', 'test@example.invalid')
        git('-C', root, 'remote', 'add', 'origin', remote)
        path = root / 'state.json'
        path.write_text(json.dumps(dict(version=1, reports={}, offset=0, started=False)))
        git('-C', root, 'add', 'state.json')
        git('-C', root, 'commit', '-m', 'Initialize')
        git('-C', root, 'push', 'origin', 'HEAD:review-state')
        durable = Store(path, git=True)
        durable.data['offset'] = 99
        durable.save()
        saved = json.loads(git('--git-dir', remote, 'show', 'review-state:state.json'))
        self.assertEqual(saved['offset'], 99)

    def test_partial_publication_resumes_only_after_reconciliation(self):
        self.draft()
        self.bot.process(self.update(), TODAY)
        counter = 0
        def send(method, **kwargs):
            nonlocal counter
            counter += 1
            if counter == 2:
                raise TimeoutError()
            return {'message_id': 500}
        self.tg.call.side_effect = send
        with self.assertRaises(TimeoutError):
            self.bot.advance(TODAY)
        state = Store(self.path)
        report = state.data['reports'][TARGET]
        self.assertEqual(report['publish_ids'], [500])
        self.assertIn('intent', report)
        # Operator verified that second part was NOT delivered.
        report.pop('intent')
        state.save()
        self.tg.call.side_effect = None
        self.tg.call.return_value = {'message_id': 501}
        self.tg.call.reset_mock()
        Review(Store(self.path), self.tg, 42, 42, -100).advance(TODAY)
        self.tg.call.assert_called_once_with('sendMessage', chat_id=-100, text='part two')
        self.assertEqual(Store(self.path).data['reports'][TARGET]['status'], 'published')

    def test_utf16_limits(self):
        with self.assertRaises(ValueError):
            validate_parts(['🌊' * 1800])


class SafeDiagnostics(unittest.TestCase):
    def test_openai_404_points_to_model_configuration(self):
        detail = str(http_failure('OpenAI revision', 404))
        self.assertIn('OPENAI_MODEL', detail)
        self.assertNotIn('bot token', detail)

    def test_unknown_error_does_not_expose_secret(self):
        detail = failure_detail(RuntimeError('https://api.telegram.org/botSECRET/sendMessage'))
        self.assertNotIn('SECRET', detail)
        self.assertIn('suppressed', detail)

    def test_git_error_does_not_expose_output(self):
        error = subprocess.CalledProcessError(1, ['git', 'push'], stderr=b'SECRET')
        self.assertIn('write permission', failure_detail(error))
        self.assertNotIn('SECRET', failure_detail(error))

    def test_missing_and_malformed_settings_are_named_safely(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(SafeError, 'Missing setting: OPENAI_MODEL'):
                setting('OPENAI_MODEL')
        with patch.dict('os.environ', {'LEO_TELEGRAM_USER_ID': '@SECRET'}):
            with self.assertRaises(SafeError) as caught:
                setting('LEO_TELEGRAM_USER_ID', numeric=True)
            self.assertNotIn('SECRET', str(caught.exception))

    def test_telegram_http_error_hides_body_and_token(self):
        response = Mock(status_code=403, text='SECRET')
        with patch.dict('sys.modules', {'requests': Mock(post=Mock(return_value=response))}):
            with self.assertRaises(SafeError) as caught:
                Telegram('TOKEN_SECRET').call('sendMessage', chat_id=42, text='test')
        detail = failure_detail(caught.exception)
        self.assertIn('HTTP 403', detail)
        self.assertNotIn('SECRET', detail)

    def test_webhook_400_classifies_rejection_without_echoing_service_text(self):
        cases = [
            ('Bad Request: bad webhook: Failed to resolve host: PRIVATE_SECRET', 'DNS:'),
            ('Bad Request: bad webhook: getaddrinfo: PRIVATE_SECRET', 'DNS:'),
            ('Bad Request: secret token contains unallowed characters PRIVATE_SECRET', 'SECRET:'),
            ('Bad Request: bad webhook: SSL certificate error PRIVATE_SECRET', 'TLS:'),
            ('Bad Request: bad webhook: port is not supported PRIVATE_SECRET', 'PORT:'),
            ('Bad Request: bad webhook: IP address is reserved PRIVATE_SECRET', 'IP:'),
            ('Bad Request: invalid webhook URL PRIVATE_SECRET', 'URL:'),
            ('Bad Request: invalid max_connections PRIVATE_SECRET', 'OPTIONS:'),
            ('Bad Request: unexpected PRIVATE_SECRET https://example.invalid/token', 'raw service text is suppressed'),
        ]
        for description, expected in cases:
            response = Mock(status_code=400)
            response.json.return_value = {'ok': False, 'error_code': 400, 'description': description}
            post = Mock(return_value=response)
            with patch.dict('sys.modules', {'requests': Mock(post=post)}):
                with self.assertRaises(SafeError) as caught:
                    Telegram('BOT_PRIVATE_SECRET').call('setWebhook', url='https://surf.example/telegram')
            detail = str(caught.exception)
            self.assertIn(expected, detail)
            self.assertNotIn('PRIVATE_SECRET', detail)
            self.assertNotIn('example.invalid', detail)
            self.assertNotIn('/start', detail)
            post.assert_called_once()  # Diagnose only; never retry a configuration change.

    def test_webhook_bad_response_retains_http_status_without_exposing_body(self):
        for body in ([], {}, None):
            response = Mock(status_code=400)
            response.json.return_value = body
            with patch.dict('sys.modules', {'requests': Mock(post=Mock(return_value=response))}):
                with self.assertRaisesRegex(SafeError, 'Telegram setWebhook HTTP 400'):
                    Telegram('BOT_SECRET').call('setWebhook', url='https://surf.example/telegram')
        response.json.side_effect = ValueError('PRIVATE_SECRET')
        with patch.dict('sys.modules', {'requests': Mock(post=Mock(return_value=response))}):
            with self.assertRaises(SafeError) as caught:
                Telegram('BOT_SECRET').call('setWebhook', url='https://surf.example/telegram')
        self.assertNotIn('PRIVATE_SECRET', str(caught.exception))
        self.assertIn('HTTP 400', str(caught.exception))

    def test_webhook_api_error_with_http_200_is_also_classified(self):
        response = Mock(status_code=200)
        response.json.return_value = {'ok': False, 'error_code': 400,
                                     'description': 'Bad Request: bad webhook: Failed to resolve host: PRIVATE_SECRET'}
        with patch.dict('sys.modules', {'requests': Mock(post=Mock(return_value=response))}):
            with self.assertRaises(SafeError) as caught:
                Telegram('BOT_SECRET').call('setWebhook', url='https://surf.example/telegram')
        self.assertIn('DNS:', str(caught.exception))
        self.assertNotIn('PRIVATE_SECRET', str(caught.exception))

    def test_openai_quota_error_is_identified_without_raw_body(self):
        response = Mock(status_code=429, text='SECRET')
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openai', 'OPENAI_API_KEY': 'SECRET', 'OPENAI_MODEL': 'model'}), \
                patch.dict('sys.modules', {'requests': Mock(post=Mock(return_value=response))}):
            with self.assertRaises(SafeError) as caught:
                revise({'date': TARGET, 'parts': ['draft'], 'forecast': {}}, 'fix change')
        self.assertIn('HTTP 429', str(caught.exception))
        self.assertNotIn('SECRET', str(caught.exception))


class GeminiRevisionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {
            'GEMINI_API_KEY': 'SECRET_GEMINI', 'GEMINI_MODEL': 'gemini-3.5-flash-lite',
        }, clear=True)
        self.env.start()
        self.response = Mock(status_code=200)
        self.response.json.return_value = {
            'candidates': [{'finishReason': 'STOP', 'content': {'parts': [
                {'text': 'private reasoning', 'thought': True},
                {'text': TARGET + ' corrected wind'},
            ]}}],
        }
        self.post = Mock(return_value=self.response)
        self.modules = patch.dict('sys.modules', {'requests': Mock(post=self.post)})
        self.modules.start()
        self.addCleanup(patch.stopall)
        self.report = {'date': TARGET, 'parts': ['draft'], 'forecast': {}}

    def test_gemini_is_default_and_never_needs_openai_key(self):
        self.assertEqual(revise(self.report, 'fix wind change'), [TARGET + ' corrected wind'])
        self.post.assert_called_once()
        call = self.post.call_args
        self.assertEqual(call.args[0], 'https://generativelanguage.googleapis.com/v1beta/models/'
                         'gemini-3.5-flash-lite:generateContent')
        self.assertEqual(call.kwargs['headers'], {'x-goog-api-key': 'SECRET_GEMINI'})
        self.assertNotIn('SECRET', call.args[0])
        payload = call.kwargs['json']
        self.assertNotIn('SECRET', json.dumps(payload))
        self.assertNotIn('tools', payload)
        self.assertEqual(json.loads(payload['contents'][0]['parts'][0]['text'])['feedback'],
                         'fix wind change')

    def test_blocked_or_truncated_output_cannot_become_draft(self):
        for body in (
                {'promptFeedback': {'blockReason': 'SAFETY'}},
                {'candidates': [{'finishReason': 'MAX_TOKENS', 'content': {
                    'parts': [{'text': TARGET + ' incomplete'}]}}]},
                {'candidates': []}):
            self.response.json.return_value = body
            with self.assertRaisesRegex(SafeError, 'Feedback remains pending'):
                revise(self.report, 'fix change')

    def test_invalid_report_cannot_become_draft(self):
        for content in ('', 'wrong date', TARGET + 'a' * 45001):
            self.response.json.return_value['candidates'][0]['content']['parts'] = [{'text': content}]
            with self.assertRaisesRegex(SafeError, 'report validation'):
                revise(self.report, 'fix change')

    def test_invented_numbers_cannot_become_draft(self):
        self.response.json.return_value['candidates'][0]['content']['parts'] = [
            {'text': TARGET + ' Wind 987.6 km/h'}]
        with self.assertRaisesRegex(SafeError, 'unsupported number'):
            revise(self.report, 'fix wind change')
        self.assertEqual(revise(self.report, 'Wind is 987.6 km/h change'),
                         [TARGET + ' Wind 987.6 km/h'])

    def test_removed_banner_is_not_required_or_reintroduced_from_existing_state(self):
        self.report['parts'] = [TARGET + ' Source: Surfline via surf-mcp. '
                                'Check conditions locally; recommendations are not safety guarantees.']
        validate_revision_text(self.report, 'make this shorter change', TARGET + ' corrected wind')
        result = ''.join(revise(self.report, 'make this shorter change'))
        self.assertEqual(result, TARGET + ' corrected wind')
        context = json.loads(self.post.call_args.kwargs['json']['contents'][0]['parts'][0]['text'])
        self.assertEqual(context['required_verbatim_text'], [])
        self.assertNotIn('Source: Surfline', '\n'.join(context['draft']))
        self.assertNotIn('safety guarantees', '\n'.join(context['draft']))
        self.post.assert_called_once()

    def protected_report(self):
        self.report['name'] = "Old Man's / Batu Bolong"
        self.report['parts'] = [
            self.report['name'] + ' | ' + TARGET + ' | WITA\n'
            'Source: Surfline via surf-mcp. '
            'Check conditions locally; recommendations are not safety guarantees.\n\n'
            '16:00–17:00\nBreaking surf: 2–3 ft\n\n'
            '17:00–18:00\nBreaking surf: 2–3 ft']

    def set_result(self, text):
        self.response.json.return_value['candidates'][0]['content']['parts'] = [{'text': text}]

    def test_time_block_removal_keeps_requested_format_and_retained_conditions(self):
        self.protected_report()
        edited = self.report['name'] + ' | ' + TARGET + ' | WITA\n\n16:00–17:00\nBreaking surf: 2–3 ft'
        self.set_result(edited)
        result = ''.join(revise(self.report, 'remove 17:00-18:00 report change'))
        self.assertIn('16:00–17:00\nBreaking surf: 2–3 ft', result)
        self.assertNotIn('17:00–18:00', result)
        for label in ('WITA', 'Source: Surfline via surf-mcp.',
                      'Check conditions locally; recommendations are not safety guarantees.'):
            self.assertNotIn(label, result)
        context = json.loads(self.post.call_args.kwargs['json']['contents'][0]['parts'][0]['text'])
        self.assertEqual(context['required_verbatim_text'], [self.report['name'].upper()])
        self.post.assert_called_once()

    def test_old_banner_is_removed_even_if_model_copies_it_and_spot_typography_is_canonicalized(self):
        self.protected_report()
        original = self.report['parts'][0]
        self.set_result(original)
        result = ''.join(revise(self.report, 'keep formatting change'))
        self.assertTrue(result.startswith("Forecast date: 30 October 2026\n\n📍OLD MAN'S / BATU BOLONG"))
        self.assertIn('16:00–17:00\nBreaking surf: 2–3 ft', result)
        self.assertIn('17:00–18:00\nBreaking surf: 2–3 ft', result)
        self.set_result(original.replace("Old Man's / Batu Bolong", 'Old Man’s/Batu Bolong'))
        result = ''.join(revise(self.report, 'tidy formatting change'))
        self.assertIn(self.report['name'].upper(), result)
        for removed in ('WITA', 'Source: Surfline', 'recommendations are not safety guarantees'):
            self.assertNotIn(removed, result)

    def test_report_formatting_cannot_rescue_a_changed_spot_or_invalid_numbers_or_date(self):
        self.protected_report()
        for edited, error in (
                ('Kuta | ' + TARGET + ' | WITA\n16:00–17:00\nBreaking surf: 2–3 ft', 'spot'),
                (self.report['name'] + ' | ' + TARGET + '\nWind 987.6 km/h', 'unsupported number'),
                (self.report['name'] + '\n16:00–17:00\nBreaking surf: 2–3 ft', 'report validation')):
            with self.subTest(edited=edited):
                self.set_result(edited)
                with self.assertRaisesRegex(SafeError, error):
                    revise(self.report, 'remove 17:00-18:00 report change')

    def test_repaired_pending_revision_still_needs_fresh_approval(self):
        self.protected_report()
        self.set_result("Forecast date: 30 October 2026\n\n📍OLD MAN'S / BATU BOLONG\n\n"
                        '🟢 BEGINNER\n16:00–17:00 — Inside break, coach recommended (larger sets)\n\n'
                        '🟡 INTERMEDIATE\n16:00–17:00\n\n'
                        '🔵 ADVANCED\n16:00–17:00 — Breaking waves 2–3 ft\n\n'
                        '⚠️ CAUTIONS\n- High energy: strong currents possible.\n'
                        '- Wind above 20 km/h: surf only if comfortable; beginners should go with a coach.\n'
                        '- Below 100 kJ: generally too flat for worthwhile surfing.')
        self.report.update(revision=1, status='revision_pending', draft_ids=[50], prompt_ids=[51],
                           feedback='remove 17:00-18:00 report change')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'state.json'
            path.write_text(json.dumps(dict(version=1, reports={TARGET: self.report}, offset=0, started=True)))
            telegram = Mock()
            telegram.call.side_effect = [{'message_id': value} for value in (101, 102, 103)]
            bot = Review(Store(path), telegram, 42, 42, -100)
            with patch('review_bot.time.sleep'):
                bot.advance(TODAY)
                saved = bot.s['reports'][TARGET]
                self.assertEqual(saved['revision'], 2)
                self.assertEqual(saved['status'], 'review')
                self.assertNotIn('approval', saved)
                for removed in ('WITA', 'Source: Surfline', 'recommendations are not safety guarantees'):
                    self.assertNotIn(removed, ''.join(saved['parts']))
                self.assertNotIn('analysis_ids', saved)
                self.assertNotIn('source_ids', saved)
                self.assertEqual(saved['prompt_ids'], [102])
                self.assertTrue(all(call.kwargs['chat_id'] == 42 for call in telegram.call.call_args_list))
                self.assertTrue(telegram.call.call_args_list[0].kwargs['entities'])
                update = {'update_id': 10, 'message': {'text': 'correct', 'from': {'id': 42},
                    'chat': {'id': 42, 'type': 'private'}, 'reply_to_message': {'message_id': 51}}}
                self.assertEqual(bot.process(update, TODAY), 'ignored_stale_prompt')
                bot.advance(TODAY)
                self.assertEqual(telegram.call.call_count, 2)
                update['message']['reply_to_message']['message_id'] = 102
                self.assertEqual(bot.process(update, TODAY), 'approved')
                bot.advance(TODAY)
                bot.advance(TODAY)
            self.assertEqual(telegram.call.call_count, 3)
            self.assertEqual(telegram.call.call_args.kwargs['chat_id'], -100)
            self.assertEqual(telegram.call.call_args.kwargs['text'], saved['parts'][0])
            self.assertTrue(telegram.call.call_args.kwargs['entities'])
            self.assertEqual(Store(path).data['reports'][TARGET]['status'], 'published')

    def test_numeric_formatting_allowed_but_new_negative_or_value_rejected(self):
        self.report['parts'] = [TARGET + ' 1,200 kJ; wind 15.0 km/h; tide -0.25 m']
        validate_revision_text(self.report, 'tidy up change', TARGET + ' 1200 kJ, wind 15 km/h; -0.250 m')
        for text in (TARGET + ' 1201 kJ', TARGET + ' wind -15 km/h', TARGET + ' tide 0.26 m',
                     TARGET + ' wind 1e10 km/h'):
            with self.assertRaisesRegex(SafeError, 'unsupported number'):
                validate_revision_text(self.report, 'tidy up change', text)

    def test_legacy_report_spot_is_protected_without_state_reset(self):
        self.report['parts'] = ["Old Man's / Batu Bolong | " + TARGET + ' | WITA\nSurf report']
        with self.assertRaisesRegex(SafeError, 'removed the spot'):
            validate_revision_text(self.report, 'shorter change', 'Kuta | ' + TARGET + ' | WITA\nSurf report')
        self.set_result('Old Man’s/Batu Bolong | ' + TARGET + ' | WITA\nSurf report')
        self.assertIn("OLD MAN'S / BATU BOLONG", ''.join(revise(self.report, 'tidy formatting change')))

    def test_simple_format_date_and_caution_thresholds_are_allowed_but_new_measurements_are_not(self):
        self.report['name'] = "Old Man's / Batu Bolong"
        self.report['parts'] = ["Old Man's / Batu Bolong | " + TARGET + '\n06:00–09:00\nBreaking surf: 3 ft']
        simple = ("Forecast date: 30 October 2026\n\n📍OLD MAN'S / BATU BOLONG\n\n"
                  '🟢 BEGINNER\n06:00–09:00 — Inside break\n\n'
                  '🟡 INTERMEDIATE\n06:00–09:00\n\n'
                  '🔵 ADVANCED\n06:00–09:00 — Breaking waves 3 ft\n\n'
                  '⚠️ CAUTIONS\n- Wind above 20 km/h: surf only if comfortable; beginners should go with a coach.\n'
                  '- Below 100 kJ: generally too flat for worthwhile surfing.')
        self.set_result(simple)
        self.assertEqual(''.join(revise(self.report, 'use the simple format change')), simple)
        self.set_result(simple.replace('waves 3 ft', 'waves 987.6 ft'))
        with self.assertRaisesRegex(SafeError, 'unsupported number'):
            revise(self.report, 'use the simple format change')
        self.set_result(simple.replace('30 October 2026', '31 October 2026'))
        with self.assertRaisesRegex(SafeError, 'report validation'):
            revise(self.report, 'use the simple format change')

    def daylight_report(self):
        from test_recommendations import Coverage
        fixture = Coverage()
        fixture.setUp()
        fixture.day['sunlight'] = {'sunrise_ts': fixture.base + 5 * 3600 + 48 * 60,
                                   'sunset_ts': fixture.base + 18 * 3600 + 12 * 60}
        self.protected_report()
        self.report['forecast'] = {'daily': [fixture.day]}
        return fixture

    def test_model_sees_only_the_target_days_rounded_daylight_forecast(self):
        from recommendations import render_day
        fixture = self.daylight_report()
        for hour in list(range(6)) + list(range(18, 24)):
            fixture.day['hourly'][hour]['outside_window_marker'] = 'NIGHT_SOURCE_ONLY'
            fixture.day['hourly'][hour]['energy'] = {'nearshore': 5000}
        self.report['forecast']['daily'].append({'date': '2026-10-31', 'marker': 'OTHER_DAY_ONLY'})
        self.set_result('\n\n'.join(render_day(fixture.day, self.report['name'])))
        revise(self.report, 'keep only useful commentary change')
        context = json.loads(self.post.call_args.kwargs['json']['contents'][0]['parts'][0]['text'])
        self.assertEqual(context['forecast']['analysis_window'], {'start': '06:00', 'end': '18:00'})
        intervals = context['forecast']['intervals']
        self.assertEqual(len(intervals), 12)
        self.assertEqual(intervals[0]['start'], '06:00')
        self.assertEqual(intervals[-1]['end'], '18:00')
        self.assertTrue(all(fixture.base + 6 * 3600 <= item['conditions']['timestamp']
                            < fixture.base + 18 * 3600 for item in intervals))
        self.assertNotIn('NIGHT_SOURCE_ONLY', json.dumps(context))
        self.assertNotIn('OTHER_DAY_ONLY', json.dumps(context))
        self.assertEqual(context['report_format']['cautions'], [])

    def test_revised_windows_cannot_extend_daylight_even_when_feedback_supplies_the_numbers(self):
        self.daylight_report()
        header = "Forecast date: 30 October 2026\n\n📍OLD MAN'S / BATU BOLONG\n\n🟢 BEGINNER\n"
        feedback = 'Consider 05:00, 19:00, 06:15 and 07:00, but use daylight only change'
        for window in ('05:00–06:00', '17:00–19:00', '06:15–07:00', '17:00–06:00', '18:00–18:00'):
            with self.subTest(window=window):
                self.set_result(header + window)
                with self.assertRaisesRegex(SafeError, 'rounded daylight window'):
                    revise(self.report, feedback)
        self.set_result(header + '06:00–18:00')
        self.assertEqual(''.join(revise(self.report, feedback)), header + '06:00–18:00')
        self.report['forecast']['daily'][0]['sunlight'] = None
        self.post.reset_mock()
        with self.assertRaisesRegex(SafeError, 'Saved forecast cannot supply'):
            revise(self.report, feedback)
        self.post.assert_not_called()

    def test_status_diagnostics_and_no_provider_fallback(self):
        for status in (400, 403, 404, 429):
            self.response.status_code = status
            self.post.reset_mock()
            with self.assertRaises(SafeError) as caught:
                revise(self.report, 'fix change')
            self.assertIn('Gemini revision HTTP ' + str(status), str(caught.exception))
            self.assertNotIn('SECRET', str(caught.exception))
            self.assertNotIn('Telegram', str(caught.exception))
            self.post.assert_called_once()

    def test_missing_key_and_invalid_model_fail_before_network(self):
        with patch.dict('os.environ', {'GEMINI_API_KEY': ''}):
            with self.assertRaisesRegex(SafeError, 'Missing setting: GEMINI_API_KEY'):
                revise(self.report, 'fix change')
        for model in ('', 'A Gemini model', '../gemini-invalid', 'gemini-id?key=SECRET'):
            with patch.dict('os.environ', {'GEMINI_MODEL': model}):
                with self.assertRaises(SafeError):
                    revise(self.report, 'fix change')
        self.post.assert_not_called()

    def test_transport_error_cannot_leak_credentials(self):
        self.post.side_effect = RuntimeError('SECRET_GEMINI in request')
        with self.assertRaises(SafeError) as caught:
            revise(self.report, 'fix change')
        self.assertNotIn('SECRET', str(caught.exception))

    def test_unknown_provider_fails_without_network(self):
        with patch.dict('os.environ', {'LLM_PROVIDER': 'unknown'}):
            with self.assertRaisesRegex(SafeError, 'No fallback'):
                revise(self.report, 'fix change')
        self.post.assert_not_called()


class GroupReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.original = dict(date=TARGET, forecast={}, parts=[TARGET + ' report'], revision=3,
                             status='review', draft_ids=[101], prompt_ids=[102],
                             feedback='Earlier saved correction change')
        self.path.write_text(json.dumps(dict(version=1, reports={TARGET: self.original},
                                            offset=90, started=True, binding=[42, 42, -100])))
        self.store = Store(self.path)
        self.tg = Mock()
        self.next_id = 100
        def call(method, **kwargs):
            self.assertEqual(method, 'sendMessage')
            self.next_id += 1
            return {'message_id': self.next_id}
        self.tg.call.side_effect = call
        self.llm = Mock(return_value=[TARGET + ' corrected report'])
        self.sleep = patch('review_bot.time.sleep').start()
        self.addCleanup(patch.stopall)

    def move(self):
        return Review(self.store, self.tg, 42, -200, -100, self.llm,
                      move_chat=True, bot_username='surf_test_bot')

    def message(self, text, reply_id=None, **changes):
        message = {'from': {'id': 42}, 'chat': {'id': -200, 'type': 'supergroup'}, 'text': text}
        if reply_id is not None:
            message['reply_to_message'] = {'message_id': reply_id}
        message.update(changes)
        return {'update_id': 95, 'message': message}

    def start(self, bot):
        self.assertEqual(bot.process(self.message('/start@surf_test_bot'), TODAY), 'started')
        self.store.save()
        bot.advance(TODAY)
        return bot.s['reports'][TARGET]

    def test_move_is_explicit_and_preserves_history_before_any_group_send(self):
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Identity/destination changed'):
            Review(self.store, self.tg, 42, -200, -100)
        self.assertEqual(self.path.read_bytes(), before)
        bot = self.move()
        saved = Store(self.path).data
        report = saved['reports'][TARGET]
        self.assertEqual(saved['binding'], [42, -200, -100])
        self.assertEqual(saved['offset'], 90)
        self.assertFalse(saved['started'])
        self.assertEqual(report['feedback'], self.original['feedback'])
        self.assertEqual(report['revision'], 4)
        self.assertEqual(report['draft_ids'] + report['prompt_ids'], [])
        self.assertEqual(report['review_history'][0]['prompt_ids'], [102])
        self.assertEqual(report['review_history'][0]['review_chat_id'], 42)
        bot.advance(TODAY)
        self.tg.call.assert_not_called()
        self.llm.assert_not_called()

    def test_only_leo_can_start_correct_or_revise_in_the_configured_group(self):
        bot = self.move()
        report = self.start(bot)
        self.assertEqual(report['status'], 'review')
        self.assertEqual([c.kwargs['chat_id'] for c in self.tg.call.call_args_list], [-200, -200])
        prompt = report['prompt_ids'][-1]
        for changes in ({'from': {'id': 99}}, {'from': {'id': 42, 'is_bot': True}},
                        {'chat': {'id': -201, 'type': 'supergroup'}},
                        {'chat': {'id': 42, 'type': 'private'}},
                        {'chat': {'id': -200, 'type': 'channel'}},
                        {'sender_chat': {'id': -200}}, {'forward_origin': {'type': 'user'}}):
            for text in ('correct', 'fix tide change', '/start@surf_test_bot'):
                self.assertEqual(bot.process(self.message(text, prompt, **changes), TODAY),
                                 'ignored_unauthorized')
        self.assertEqual(report['status'], 'review')
        self.llm.assert_not_called()
        self.assertEqual(bot.process(self.message('correct', prompt), TODAY), 'approved')
        self.assertEqual(report['approval']['chat_id'], -200)
        self.store.save()
        bot.advance(TODAY)
        restarted = Review(Store(self.path), self.tg, 42, -200, -100, self.llm)
        restarted.advance(TODAY)
        self.assertEqual([c.kwargs['text'] for c in self.tg.call.call_args_list
                          if c.kwargs['chat_id'] == -100], self.original['parts'])

    def test_group_feedback_loops_and_needs_a_fresh_exact_approval(self):
        bot = self.move()
        report = self.start(bot)
        old_prompt = report['prompt_ids'][-1]
        self.assertEqual(bot.process(self.message('remove late window change', old_prompt), TODAY),
                         'revision_pending')
        bot.advance(TODAY)
        self.llm.assert_called_once()
        self.assertEqual(report['revision'], 5)
        self.assertEqual(report['parts'], [TARGET + ' corrected report'])
        for text, prompt in (('correct', old_prompt), ('Correct', report['prompt_ids'][-1]),
                             (' correct', report['prompt_ids'][-1])):
            bot.process(self.message(text, prompt), TODAY)
            self.assertEqual(report['status'], 'review')
        self.assertTrue(all(c.kwargs['chat_id'] == -200 for c in self.tg.call.call_args_list))
        self.assertEqual(len(self.tg.call.call_args_list), 4)  # Report + prompt, twice.

    def test_old_private_prompt_with_same_numeric_id_cannot_approve_group_report(self):
        bot = self.move()
        report = self.start(bot)
        self.assertEqual(report['prompt_ids'], self.original['prompt_ids'])  # IDs are per chat.
        outcome = bot.process(self.message('correct', 102, chat={'id': 42, 'type': 'private'}), TODAY)
        self.assertEqual(outcome, 'ignored_unauthorized')
        self.assertEqual(report['status'], 'review')

    def test_published_history_is_not_reopened_or_matched_in_the_new_chat(self):
        published = dict(self.original, date=TODAY, status='published', publish_ids=[103])
        self.store.data['reports'][TODAY] = published
        bot = self.move()
        self.assertEqual(bot.s['reports'][TODAY]['publish_ids'], [103])
        self.assertEqual(bot.s['reports'][TODAY]['review_chat_id'], 42)
        self.assertEqual(bot.s['reports'][TODAY]['status'], 'published')
        report = self.start(bot)
        # A historical DM with this ID must not intercept approval of a group prompt.
        self.assertEqual(bot.process(self.message('correct', report['prompt_ids'][-1]), TODAY), 'approved')
        bot.advance(TODAY)
        self.assertEqual(sum(c.kwargs['chat_id'] == -100 for c in self.tg.call.call_args_list), 1)

    def test_retry_of_move_does_not_create_another_revision_or_reset_start(self):
        bot = self.move()
        report = self.start(bot)
        before = self.path.read_bytes()
        restarted = Review(Store(self.path), self.tg, 42, -200, -100, self.llm, move_chat=True)
        restarted.advance(TODAY)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(report['revision'], 4)
        self.assertEqual(len(self.tg.call.call_args_list), 2)

    def test_pending_feedback_survives_move_and_waits_for_group_start(self):
        self.store.data['reports'][TARGET]['status'] = 'revision_pending'
        bot = self.move()
        bot.advance(TODAY)
        self.llm.assert_not_called()
        self.start(bot)
        self.llm.assert_called_once()
        self.assertEqual(self.llm.call_args.args[1], self.original['feedback'])
        self.assertEqual(bot.s['reports'][TARGET]['status'], 'review')
        self.assertTrue(all(c.kwargs['chat_id'] == -200 for c in self.tg.call.call_args_list))

    def test_move_refuses_uncertain_sends_publication_and_pending_notices(self):
        for change in ('uncertain', 'approved', 'partial_publication', 'notice', 'notice_uncertain'):
            with self.subTest(change=change):
                state = json.loads(self.path.read_text())
                if change == 'uncertain':
                    state['reports'][TARGET]['intent'] = {'kind': 'draft'}
                elif change == 'approved':
                    state['reports'][TARGET]['status'] = 'approved'
                elif change == 'partial_publication':
                    state['reports'][TARGET]['publish_ids'] = [103]
                else:
                    state['outbox'] = {'old': dict(kind='notice', status='pending', parts=['notice'])}
                    if change == 'notice_uncertain':
                        state['outbox']['old']['intent'] = {'kind': 'notice'}
                self.store.data = state
                before = json.dumps(state, sort_keys=True)
                with self.assertRaises(RuntimeError):
                    self.move()
                self.assertEqual(json.dumps(self.store.data, sort_keys=True), before)
        self.tg.call.assert_not_called()

    def test_move_cannot_change_reviewer_or_public_channel(self):
        for user, group, channel in ((43, -200, -100), (42, -200, -101)):
            with self.assertRaisesRegex(SafeError, 'cannot change Leo'):
                Review(self.store, self.tg, user, group, channel, move_chat=True)
        for user, group, channel in ((42, -100, -100), (42, 99, -100), (42, 0, -100)):
            with self.assertRaises(ValueError):
                Review(self.store, self.tg, user, group, channel, move_chat=True)
        self.tg.call.assert_not_called()

    def test_groups_supergroups_and_addressed_commands_need_no_privacy_change(self):
        bot = self.move()
        for chat_type in ('group', 'supergroup'):
            bot.s['started'] = False
            self.assertEqual(bot.process(self.message('/start@other_bot', chat={'id': -200, 'type': chat_type}),
                                         TODAY), 'ignored_unthreaded')
            self.assertFalse(bot.s['started'])
            self.assertEqual(bot.process(self.message('/start@SuRf_TeSt_BoT', chat={'id': -200, 'type': chat_type}),
                                         TODAY), 'started')
            self.assertEqual(bot.process(self.message('/status@surf_test_bot', chat={'id': -200, 'type': chat_type}),
                                         TODAY), 'status_requested')

    def test_group_approval_chat_binding_cannot_be_tampered(self):
        bot = self.move()
        report = self.start(bot)
        bot.process(self.message('correct', report['prompt_ids'][-1]), TODAY)
        report['approval']['chat_id'] = 42
        with self.assertRaisesRegex(ValueError, 'Approval does not match draft'):
            bot.advance(TODAY)
        self.assertFalse(any(c.kwargs['chat_id'] == -100 for c in self.tg.call.call_args_list))

    def test_move_cli_requires_a_manual_run_before_accessing_state(self):
        for event, run_id in (('schedule', '12'), ('workflow_dispatch', ''), ('workflow_dispatch', 'bad')):
            with patch('sys.argv', ['review_bot.py', '--run', '--persist-git', '--move-review-chat']), \
                    patch.dict('os.environ', {'GITHUB_EVENT_NAME': event, 'GITHUB_RUN_ID': run_id}, clear=True), \
                    patch('review_bot.Store') as store:
                with self.assertRaisesRegex(SafeError, 'explicit GitHub manual workflow run'):
                    main()
                store.assert_not_called()

    def test_published_report_moves_without_resending_and_manual_group_test_is_explicit(self):
        self.store.data['reports'][TARGET].update(status='published', publish_ids=[105])
        bot = self.move()
        self.start(bot)
        bot.advance(TODAY)
        self.tg.call.assert_not_called()
        bot.forecast = Mock(return_value=Forecast(TARGET, 'Test spot', {}, [TARGET + ' fresh report']))
        self.assertTrue(bot.reopen_published(TARGET, TODAY, '12345'))
        bot.advance(TODAY)
        report = bot.s['reports'][TARGET]
        self.assertEqual(report['publication_history'][0]['publish_ids'], [105])
        self.assertEqual(report['review_chat_id'], -200)
        self.assertTrue(all(c.kwargs['chat_id'] == -200 for c in self.tg.call.call_args_list))
        self.assertIn('already published', self.tg.call.call_args.kwargs['text'])
        self.assertFalse(bot.reopen_published(TARGET, TODAY, '12345'))

    def test_move_cli_verifies_group_and_bot_then_consumes_start_before_delivery(self):
        original_send = self.tg.call.side_effect
        def call(method, **kwargs):
            if method == 'getChat':
                self.assertEqual(kwargs, {'chat_id': -200})
                return {'id': -200, 'type': 'supergroup'}
            if method == 'getMe':
                return {'username': 'surf_test_bot'}
            if method == 'getWebhookInfo':
                return {'url': ''}
            if method == 'getUpdates':
                return [self.message('/start@surf_test_bot')]
            return original_send(method, **kwargs)
        self.tg.call.side_effect = call
        with patch('sys.argv', ['review_bot.py', '--run', '--persist-git', '--move-review-chat']), \
                patch('review_bot.Store', return_value=self.store), \
                patch('review_bot.Telegram', return_value=self.tg), \
                patch('review_bot.datetime', wraps=datetime) as clock, \
                patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'SECRET', 'LEO_TELEGRAM_USER_ID': '42',
                                         'LEO_TELEGRAM_CHAT_ID': '-200', 'TELEGRAM_CHANNEL_ID': '-100',
                                         'SURF_REVIEW_TRANSPORT': 'poll', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                                         'GITHUB_RUN_ID': '12345'}, clear=True):
            clock.now.return_value = datetime(2026, 10, 29, 12, tzinfo=BALI)
            main()
        saved = Store(self.path).data
        self.assertTrue(saved['started'])
        self.assertEqual(saved['reports'][TARGET]['status'], 'review')
        self.assertEqual(saved['reports'][TARGET]['review_chat_id'], -200)
        self.assertEqual([c.kwargs['chat_id'] for c in self.tg.call.call_args_list if c.args[0] == 'sendMessage'],
                         [-200, -200])

    def test_move_cli_rejects_channel_destination_before_modifying_state(self):
        before = self.path.read_bytes()
        self.tg.call.return_value = {'id': -200, 'type': 'channel'}
        self.tg.call.side_effect = None
        with patch('sys.argv', ['review_bot.py', '--run', '--persist-git', '--move-review-chat']), \
                patch('review_bot.Store', return_value=self.store), \
                patch('review_bot.Telegram', return_value=self.tg), \
                patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'SECRET', 'LEO_TELEGRAM_USER_ID': '42',
                                         'LEO_TELEGRAM_CHAT_ID': '-200', 'TELEGRAM_CHANNEL_ID': '-100',
                                         'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ID': '12345'}, clear=True):
            with self.assertRaisesRegex(SafeError, 'must identify the review group'):
                main()
        self.assertEqual(self.path.read_bytes(), before)
        self.tg.call.assert_called_once_with('getChat', chat_id=-200)

    def test_new_install_accepts_configured_group_without_a_chat_move(self):
        self.store.data = dict(version=1, reports={}, offset=0, started=False)
        bot = Review(self.store, self.tg, 42, -200, -100, bot_username='surf_test_bot')
        self.assertEqual(bot.s['binding'], [42, -200, -100])
        self.assertEqual(bot.process(self.message('/start@surf_test_bot'), TODAY), 'started')
        self.tg.call.assert_not_called()


class TwoReviewerTests(unittest.TestCase):
    message = GroupReviewTests.message
    start = GroupReviewTests.start

    def setUp(self):
        GroupReviewTests.setUp(self)
        self.bot = Review(self.store, self.tg, 42, -200, -100, self.llm,
                          move_chat=True, bot_username='surf_test_bot', owner=99)
        self.report = self.start(self.bot)

    def owner_update(self, text, update_id=96):
        update = self.message(text, self.report['prompt_ids'][-1], **{'from': {'id': 99}})
        update['update_id'] = update_id
        return update

    def sends_to_channel(self):
        return [call for call in self.tg.call.call_args_list
                if call.args[0] == 'sendMessage' and call.kwargs['chat_id'] == -100]

    def test_owner_approval_records_actual_sender_and_publishes_once(self):
        self.assertEqual(self.bot.process(self.owner_update('correct'), TODAY), 'approved')
        self.assertEqual(self.report['approval']['user_id'], 99)
        self.store.save()
        restarted = Review(Store(self.path), self.tg, 42, -200, -100, self.llm, owner=99)
        restarted.advance(TODAY)
        restarted.process(self.owner_update('correct'), TODAY)
        restarted.advance(TODAY)
        self.assertEqual([call.kwargs['text'] for call in self.sends_to_channel()], self.original['parts'])

    def test_leo_can_approve_with_both_reviewers_enabled(self):
        self.assertIn('Either of you:', self.tg.call.call_args.kwargs['text'])
        self.assertEqual(self.bot.process(self.message('correct', self.report['prompt_ids'][-1]), TODAY), 'approved')
        self.assertEqual(self.report['approval']['user_id'], 42)
        self.bot.advance(TODAY)
        self.assertEqual(len(self.sends_to_channel()), 1)

    def test_owner_can_revise_and_leo_can_approve_the_new_prompt(self):
        old_prompt = self.report['prompt_ids'][-1]
        self.bot.consume_updates([self.owner_update('remove late window change')], TODAY)
        saved = Store(self.path).data['reports'][TARGET]
        self.assertEqual(saved['feedback_log'][0], {
            'user_id': 99, 'chat_id': -200, 'update_id': 96,
            'revision': 4, 'text': 'remove late window change'})
        self.bot.advance(TODAY)
        self.llm.assert_called_once()
        self.assertEqual(self.llm.call_args.args[1], 'remove late window change')
        self.assertNotIn('pending_feedback', self.report)
        self.assertEqual(self.bot.process(self.message('correct', old_prompt), TODAY), 'ignored_stale_prompt')
        self.assertEqual(self.bot.process(self.message('correct', self.report['prompt_ids'][-1]), TODAY), 'approved')
        self.bot.advance(TODAY)
        self.assertEqual(len(self.sends_to_channel()), 1)

    def test_other_members_bots_forwards_anonymous_admins_and_wrong_chats_are_ignored(self):
        prompt = self.report['prompt_ids'][-1]
        for override in ({'from': {'id': 100}}, {'from': {'id': 99, 'is_bot': True}},
                         {'chat': {'id': -201, 'type': 'supergroup'}},
                         {'chat': {'id': 99, 'type': 'private'}}, {'chat': {'id': -200, 'type': 'channel'}},
                         {'sender_chat': {'id': -200}}, {'forward_origin': {'type': 'user'}}):
            for text in ('correct', 'remove late window change'):
                self.assertEqual(self.bot.process(self.message(text, prompt, **override), TODAY),
                                 'ignored_unauthorized')
        self.assertEqual(self.report['status'], 'review')
        self.assertNotIn('feedback_log', self.report)
        self.llm.assert_not_called()
        self.assertFalse(self.sends_to_channel())

    def test_both_pending_corrections_reach_one_revision_and_survive_restart(self):
        leo = self.message('remove early window change', self.report['prompt_ids'][-1])
        leo['update_id'] = 97
        self.bot.consume_updates([self.owner_update('remove late window change'), leo], TODAY)
        restarted = Review(Store(self.path), self.tg, 42, -200, -100, self.llm, owner=99)
        restarted.advance(TODAY)
        feedback = self.llm.call_args.args[1]
        self.assertIn('Group owner: remove late window change', feedback)
        self.assertIn('Leo: remove early window change', feedback)
        self.assertEqual(len(Store(self.path).data['reports'][TARGET]['feedback_log']), 2)
        self.assertEqual(len(self.tg.call.call_args_list), 4)  # Two report/prompt pairs only.
        self.assertFalse(self.sends_to_channel())

    def test_latest_pending_correction_per_person_replaces_only_their_own_text(self):
        leo = self.message('keep the coach restriction change', self.report['prompt_ids'][-1])
        leo['update_id'] = 97
        self.bot.consume_updates([self.owner_update('remove 18:00 change'), leo,
                                  self.owner_update('remove 17:00 change', 98)], TODAY)
        self.assertNotIn('18:00', self.report['feedback'])
        self.assertIn('17:00', self.report['feedback'])
        self.assertIn('coach restriction', self.report['feedback'])
        self.assertEqual([item['user_id'] for item in self.report['feedback_log']], [99, 42, 99])
        self.assertIn('18:00', self.report['feedback_log'][0]['text'])

    def test_duplicate_update_does_not_duplicate_correction_history(self):
        update = self.owner_update('keep the coach restriction change')
        self.bot.consume_updates([update, update], TODAY)
        self.bot.consume_updates([update], TODAY)
        self.assertEqual(len(self.report['feedback_log']), 1)

    def test_both_note_only_edits_remain_free_of_llm_calls(self):
        leo = self.message('note: Coach to assess currents change', self.report['prompt_ids'][-1])
        leo['update_id'] = 97
        self.bot.consume_updates([self.owner_update('note: Meet at the beach change'), leo], TODAY)
        self.bot.advance(TODAY)
        self.llm.assert_not_called()
        self.assertIn('Meet at the beach', '\n'.join(self.report['parts']))
        self.assertIn('Coach to assess currents', '\n'.join(self.report['parts']))
        self.assertEqual(self.report['status'], 'review')
        self.assertEqual(len(self.report['feedback_log']), 2)

    def test_old_leo_pending_feedback_is_retained_when_owner_adds_a_correction(self):
        self.report.update(status='revision_pending', feedback='legacy saved correction change')
        self.bot.process(self.owner_update('remove late window change'), TODAY)
        self.assertIn('Leo: legacy saved correction change', self.report['feedback'])
        self.assertIn('Group owner: remove late window change', self.report['feedback'])
        self.bot.advance(TODAY)
        self.assertEqual(self.report['status'], 'review')

    def test_removed_owner_cannot_complete_a_saved_approval(self):
        self.bot.process(self.owner_update('correct'), TODAY)
        self.store.save()
        restarted = Review(Store(self.path), self.tg, 42, -200, -100, self.llm)
        with self.assertRaisesRegex(ValueError, 'Approval does not match draft'):
            restarted.advance(TODAY)
        self.assertFalse(self.sends_to_channel())

    def test_owner_must_have_a_valid_personal_id_and_both_reviewers_need_a_group(self):
        for owner in (0, -100, True, 99.5, '99', 2**52 + 1):
            with self.assertRaisesRegex(SafeError, 'positive numeric personal user ID'):
                Review(self.store, self.tg, 42, -200, -100, owner=owner)
        with self.assertRaisesRegex(SafeError, 'Two reviewers require'):
            Review(self.store, self.tg, 42, 42, -100, owner=99)

    def test_owner_can_use_addressed_group_commands(self):
        self.bot.s['started'] = False
        for text, expected in (('/start@surf_test_bot', 'started'),
                               ('/status@surf_test_bot', 'status_requested'),
                               ('/dryrun@surf_test_bot', 'dryrun_requested')):
            self.assertEqual(self.bot.process(self.owner_update(text), TODAY), expected)
        self.assertTrue(self.bot.s['started'])
        self.assertEqual(self.report['status'], 'review')
        self.assertFalse(self.sends_to_channel())

    def test_manual_resend_and_later_group_move_preserve_dated_feedback_log(self):
        self.bot.process(self.owner_update('remove late window change'), TODAY)
        self.bot.advance(TODAY)
        self.bot.reopen_published(TARGET, TODAY, '12345')
        log = self.bot.s['reports'][TARGET]['feedback_log']
        self.assertEqual(log[0]['user_id'], 99)
        moved = Review(self.store, self.tg, 42, -300, -100, self.llm, move_chat=True, owner=99)
        self.assertEqual(moved.s['reports'][TARGET]['feedback_log'], log)
        self.assertEqual(moved.s['reports'][TARGET]['review_chat_id'], -300)

    def test_new_forecast_does_not_automatically_reuse_old_date_corrections(self):
        self.bot.process(self.owner_update('wind is 12345 change'), TODAY)
        self.bot.advance(TODAY)
        self.bot.advance(TARGET)  # Prior forecast expires at the start of its date.
        next_date = '2026-10-31'
        snapshot = Forecast(next_date, 'Test spot', {'fresh': True}, [next_date + ' fresh report'])
        self.bot.forecast = Mock(return_value=snapshot)
        with patch('review_bot.build_blocks', return_value=[next_date + ' fresh report']) as builder:
            self.bot.generate_next_day(next_date)
        builder.assert_called_once_with({'fresh': True}, next_date, 'Test spot')
        new = self.bot.s['reports'][next_date]
        self.assertNotIn('feedback', new)
        self.assertNotIn('feedback_log', new)
        self.assertNotIn('12345', '\n'.join(new['parts']))
        self.assertIn('12345', self.bot.s['reports'][TARGET]['feedback_log'][0]['text'])

    def test_two_approvals_in_the_same_batch_publish_only_once(self):
        leo = self.message('correct', self.report['prompt_ids'][-1])
        leo['update_id'] = 97
        self.bot.consume_updates([self.owner_update('correct'), leo], TODAY)
        self.assertEqual(self.report['approval']['user_id'], 99)
        self.bot.advance(TODAY)
        self.assertEqual(len(self.sends_to_channel()), 1)

    def test_feedback_before_an_approval_in_one_batch_requires_a_new_prompt(self):
        leo = self.message('correct', self.report['prompt_ids'][-1])
        leo['update_id'] = 97
        self.bot.consume_updates([self.owner_update('remove late window change'), leo], TODAY)
        self.assertEqual(self.report['status'], 'revision_pending')
        self.bot.advance(TODAY)
        self.assertEqual(self.report['status'], 'review')
        self.assertFalse(self.sends_to_channel())

    def test_workflow_reads_owner_setting_and_publishes_their_exact_approval(self):
        original_send = self.tg.call.side_effect
        def call(method, **kwargs):
            if method == 'getChat':
                return {'id': -200, 'type': 'supergroup'}
            if method == 'getMe':
                return {'username': 'surf_test_bot'}
            if method == 'getWebhookInfo':
                return {'url': ''}
            if method == 'getUpdates':
                return [self.owner_update('correct')]
            return original_send(method, **kwargs)
        self.tg.call.side_effect = call
        with patch('sys.argv', ['review_bot.py', '--run', '--persist-git']), \
                patch('review_bot.Store', return_value=self.store), \
                patch('review_bot.Telegram', return_value=self.tg), \
                patch('review_bot.datetime', wraps=datetime) as clock, \
                patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'SECRET', 'LEO_TELEGRAM_USER_ID': '42',
                                         'OWNER_TELEGRAM_USER_ID': '99', 'LEO_TELEGRAM_CHAT_ID': '-200',
                                         'TELEGRAM_CHANNEL_ID': '-100', 'SURF_REVIEW_TRANSPORT': 'poll'}, clear=True):
            clock.now.return_value = datetime(2026, 10, 29, 12, tzinfo=BALI)
            main()
        self.assertEqual(Store(self.path).data['reports'][TARGET]['approval']['user_id'], 99)
        self.assertEqual(len(self.sends_to_channel()), 1)


if __name__ == '__main__':
    unittest.main()
