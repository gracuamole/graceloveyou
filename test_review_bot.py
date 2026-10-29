import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, patch

from review_bot import Review, Store, digest, revise, validate_parts

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
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'secret', 'OPENAI_MODEL': 'test-model'}), \
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


if __name__ == '__main__':
    unittest.main()
