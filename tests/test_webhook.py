from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from review_bot import Review, SafeError, Store, WebhookInbox
from webhook_setup import configure


class WebhookConsumption(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.target, self.today = '2026-10-31', '2026-10-30'
        self.data = {'version': 1, 'reports': {self.target: {
            'date': self.target, 'status': 'review', 'revision': 1, 'parts': [self.target + ' surf'],
            'forecast': {}, 'draft_ids': [100], 'prompt_ids': [101],
        }}, 'offset': 1000, 'started': True, 'binding': [42, 42, -100]}
        self.path.write_text(json.dumps(self.data))
        self.store = Store(self.path)
        self.telegram = Mock()
        self.bot = Review(self.store, self.telegram, 42, 42, -100)
        self.update = {'update_id': 2, 'message': {'from': {'id': 42},
                       'chat': {'id': 42, 'type': 'private'}, 'text': 'fix wind change',
                       'reply_to_message': {'message_id': 101}}}

    def test_webhook_ids_can_reset_and_ack_follows_durable_save(self):
        def ack(update_id):
            self.assertEqual(update_id, 2)
            saved = Store(self.path).data
            self.assertEqual(saved['reports'][self.target]['status'], 'revision_pending')
            self.assertIn(2, saved['webhook_processed_ids'])
        self.bot.consume_updates([self.update], self.today, ack=ack)
        self.assertEqual(self.store.data['offset'], 1000)  # poll cursor never moves backward.
        self.telegram.call.assert_not_called()

    def test_failed_checkpoint_does_not_acknowledge_webhook(self):
        ack = Mock()
        self.store.save = Mock(side_effect=RuntimeError('Git push failed'))
        with self.assertRaises(RuntimeError):
            self.bot.consume_updates([self.update], self.today, ack=ack)
        ack.assert_not_called()
        self.assertEqual(Store(self.path).data['reports'][self.target]['status'], 'review')

    def test_ack_failure_retry_does_not_reinterpret_feedback(self):
        with self.assertRaises(RuntimeError):
            self.bot.consume_updates([self.update], self.today,
                                     ack=Mock(side_effect=RuntimeError('inbox unavailable')))
        restarted = Review(Store(self.path), self.telegram, 42, 42, -100)
        restarted.process = Mock(side_effect=AssertionError('must not process duplicate'))
        ack = Mock()
        restarted.consume_updates([self.update], self.today, ack=ack)
        ack.assert_called_once_with(2)
        restarted.process.assert_not_called()

    def test_webhook_client_keeps_secret_in_header_and_disables_redirects(self):
        response = Mock(status_code=200)
        response.json.return_value = {'updates': [self.update]}
        get, post = Mock(return_value=response), Mock(return_value=response)
        with patch.dict('sys.modules', {'requests': Mock(get=get, post=post)}):
            inbox = WebhookInbox('https://surf.example/', 'PRIVATE_TOKEN')
            self.assertEqual(inbox.updates(), [self.update])
            inbox.ack(2)
            inbox.complete()
        get.assert_called_once_with('https://surf.example/inbox',
                                    headers={'Authorization': 'Bearer PRIVATE_TOKEN'},
                                    timeout=30, allow_redirects=False)
        self.assertEqual(post.call_count, 2)
        self.assertNotIn('PRIVATE_TOKEN', get.call_args.args[0])
        self.assertEqual(post.call_args.args[0], 'https://surf.example/complete')

    def test_bad_urls_or_redirects_are_not_followed(self):
        for url in ('http://surf.example', 'https://user:pass@surf.example',
                    'https://surf.example/path', 'https://surf.example?token=PRIVATE'):
            with self.assertRaises(SafeError):
                WebhookInbox(url, 'token')
        response = Mock(status_code=302)
        with patch.dict('sys.modules', {'requests': Mock(get=Mock(return_value=response))}):
            with self.assertRaises(SafeError):
                WebhookInbox('https://surf.example', 'token').updates()


class WebhookSetupTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'PRIVATE_BOT_TOKEN',
            'SURF_REVIEW_ENABLED': 'false', 'SURF_REVIEW_TRANSPORT': 'webhook',
            'TELEGRAM_WEBHOOK_SECRET': 's' * 40, 'SURF_WEBHOOK_TOKEN': 'a' * 40,
            'SURF_WEBHOOK_URL': 'https://surf.example'}, clear=True)
        self.env.start()
        self.telegram = Mock()
        self.telegram.call.side_effect = [{'url': ''}, True, {'url': 'https://surf.example/telegram'}]
        patch('webhook_setup.Telegram', return_value=self.telegram).start()
        self.inbox = Mock(url='https://surf.example')
        self.inbox.call.return_value = {'enabled': True}
        patch('webhook_setup.WebhookInbox', return_value=self.inbox).start()
        self.addCleanup(patch.stopall)

    def test_enable_preserves_pending_updates_and_verifies_registration(self):
        configure('enable')
        self.telegram.call.assert_any_call('setWebhook', url='https://surf.example/telegram',
            secret_token='s' * 40, max_connections=1, allowed_updates=['message'], drop_pending_updates=False)
        self.assertFalse(any(call.args[0] == 'sendMessage' for call in self.telegram.call.call_args_list))

    def test_setup_refuses_active_poller_or_replacing_other_webhook(self):
        with patch.dict('os.environ', {'SURF_REVIEW_ENABLED': 'true'}):
            with self.assertRaises(SafeError):
                configure('enable')
        self.telegram.call.assert_not_called()
        self.telegram.call.side_effect = [{'url': 'https://other.example/secret'}]
        with self.assertRaises(SafeError):
            configure('enable')
        self.telegram.call.assert_called_once_with('getWebhookInfo')

    def test_inspect_omits_token_url_and_raw_telegram_errors(self):
        self.telegram.call.side_effect = [{'url': 'https://example/PRIVATE_SECRET',
            'last_error_message': 'PRIVATE_BOT_TOKEN', 'last_error_date': 123,
            'pending_update_count': 2}]
        output = io.StringIO()
        with redirect_stdout(output):
            configure('inspect')
        self.assertNotIn('PRIVATE', output.getvalue())
        self.assertIn('pending deliveries: 2', output.getvalue())
