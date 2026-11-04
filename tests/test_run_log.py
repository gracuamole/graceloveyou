"""Offline checks for secret-safe logging and the production schedule boundary."""
import contextlib
from datetime import datetime
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import run_log
import review_bot
from recommendations import BALI


class RunLogTests(unittest.TestCase):
    def setUp(self):
        run_log.COUNTS.clear()
        run_log.DURATIONS.clear()
        run_log.ENDPOINT_DURATIONS.clear()

    def test_secrets_and_unapproved_fields_are_never_logged(self):
        secret = 'FAKE-secret-token-123456'
        stream = io.StringIO()
        with patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': secret, 'GEMINI_API_KEY': secret}), contextlib.redirect_stdout(stream):
            run_log.log_event('surfline_request', endpoint='wind', status=403, attempt=1,
                              url='https://example/' + secret, feedback=secret,
                              transport=secret, duration_ms=secret)
            run_log.log_event(secret, status=200)
        self.assertNotIn(secret, stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue()), {
            'event': 'surfline_request', 'endpoint': 'wind', 'status': 403, 'attempt': 1})

    def test_failure_is_timed_without_logging_exception_or_swallowing_it(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), patch('run_log.time.monotonic', side_effect=[1, 1.25]):
            with self.assertRaisesRegex(ValueError, 'private'):
                with run_log.timed('telegram_call'):
                    raise ValueError('private message and URL')
        event = json.loads(stream.getvalue())
        self.assertEqual(event['outcome'], 'failure')
        self.assertEqual(event['duration_ms'], 250)
        self.assertNotIn('private', stream.getvalue())

    def test_summary_aggregates_without_reporting_unimplemented_cache_hits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'summary.md'
            with patch.dict('os.environ', {'GITHUB_STEP_SUMMARY': str(path)}), contextlib.redirect_stdout(io.StringIO()):
                run_log.log_event('surfline_request', endpoint='wind', status=403, attempt=1)
                run_log.log_event('stage', stage='forecast_fetch', duration_ms=2500, outcome='failure')
                run_log.write_summary()
            text = path.read_text()
            self.assertIn('Surfline HTTP attempts: 1', text)
            self.assertIn('| forecast_fetch | 2.500 |', text)
            self.assertIn('403: 1', text)
            self.assertIn('not implemented until Release 2', text)

    def test_metrics_io_failure_does_not_break_operations(self):
        with patch('builtins.print', side_effect=OSError):
            run_log.log_event('stage', stage='state_save', duration_ms=1)
        with patch.dict('os.environ', {'GITHUB_STEP_SUMMARY': '/unused'}), patch.object(Path, 'open', side_effect=OSError):
            run_log.write_summary()

    def test_main_generation_boundary_0306_and_0307(self):
        for minute, expected in [(6, False), (7, True)]:
            with self.subTest(minute=minute):
                store = Mock(data={'started': True, 'reports': {}})
                bot = Mock()
                bot.poll.return_value = set()
                bot.tg.call.return_value = {'url': ''}
                settings = {'TELEGRAM_BOT_TOKEN': 'fake', 'LEO_TELEGRAM_USER_ID': 1,
                            'LEO_TELEGRAM_CHAT_ID': 1, 'TELEGRAM_CHANNEL_ID': -2}
                with patch('sys.argv', ['review_bot.py', '--run', '--persist-git']), \
                     patch.dict('os.environ', {'SURF_REVIEW_TRANSPORT': 'poll', 'OWNER_TELEGRAM_USER_ID': ''}), \
                     patch.object(review_bot, 'Store', return_value=store), \
                     patch.object(review_bot, 'Telegram'), \
                     patch.object(review_bot, 'Review', return_value=bot), \
                     patch.object(review_bot, 'setting', side_effect=lambda name, **kw: settings[name]), \
                     patch.object(review_bot, 'show_status'), \
                     patch.object(review_bot, 'datetime', wraps=datetime) as clock:
                    clock.now.return_value = datetime(2026, 11, 4, 3, minute, tzinfo=BALI)
                    review_bot.main()
                self.assertEqual(bot.generate_next_day.called, expected)
                if expected:
                    bot.generate_next_day.assert_called_once_with('2026-11-05')
