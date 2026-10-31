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

    def test_generate_target_is_never_replaced(self):
        original = self.report['parts'][:]
        self.bot.generate(TARGET, {}, 'ignored')
        self.assertEqual(self.report['parts'], original)

    def test_second_active_report_is_rejected_before_fetching(self):
        self.bot.forecast = Mock()
        with self.assertRaisesRegex(SafeError, 'Another report is still active'):
            self.bot.generate_next_day('2026-10-31')
        self.bot.forecast.assert_not_called()
        self.assertEqual(list(self.bot.s['reports']), [TARGET])

    def test_private_status_command_survives_restart_and_duplicate_delivery(self):
        self.draft()
        self.report['feedback'] = 'PRIVATE_FEEDBACK_SECRET'
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
        self.assertIn('PRIVATE PREVIEW ONLY', preview['parts'][0])
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
        self.assertIn('Private preview failed', self.bot.s['outbox']['dryrun:5']['parts'][0])
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


if __name__ == '__main__':
    unittest.main()
