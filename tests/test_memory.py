import json
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import test_review_bot as existing
from forecast_sources import Forecast
from phase2 import build_blocks, chunks
from review_bot import APPLY_MEMORY, Review, SafeError, Store, active_memory, revise

TODAY, TARGET = existing.TODAY, existing.TARGET
FUTURE_TODAY, FUTURE_DATE = '2026-10-31', '2026-11-01'


class MemoryTests(unittest.TestCase):
    message = existing.GroupReviewTests.message
    start = existing.GroupReviewTests.start
    owner_update = existing.TwoReviewerTests.owner_update
    sends_to_channel = existing.TwoReviewerTests.sends_to_channel

    def setUp(self):
        existing.TwoReviewerTests.setUp(self)

    def remember(self, text='Please remember to keep commentary short change', update_id=96):
        return self.bot.consume_updates([self.owner_update(text, update_id)], TODAY)

    def future(self):
        self.bot.advance(TODAY)
        self.bot.advance(FUTURE_TODAY)
        fixture = json.loads((Path(__file__).parent / 'fixtures/november_1_2026.json').read_text())
        data, name = fixture['forecast'], fixture['name']
        parts = chunks(build_blocks(data, FUTURE_DATE, name), limit=3000)
        self.bot.forecast = Mock(return_value=Forecast(FUTURE_DATE, name, data, parts))
        self.llm.reset_mock()
        self.llm.side_effect = None
        self.llm.return_value = parts
        self.bot.generate_next_day(FUTURE_DATE)
        return self.bot.s['reports'][FUTURE_DATE]

    def test_remember_matches_a_whole_word_anywhere_and_ignores_case(self):
        samples = ['remember keep it short change', 'Keep it short; remember this change',
                   'Please REMEMBER to use full sentences change\n']
        for index, text in enumerate(samples):
            self.assertEqual(self.remember(text, 96 + index), {'memory_revision_pending'})
        entries = Store(self.path).data['memory']['entries']
        self.assertEqual([entry['text'] for entry in entries], samples)
        self.assertTrue(all(entry['user_id'] == 99 and entry['chat_id'] == -200 for entry in entries))
        self.assertEqual([entry['id'] for entry in entries], [1, 2, 3])
        self.llm.assert_not_called()

    def test_leo_and_owner_can_each_save_standing_feedback(self):
        self.remember()
        leo = self.message('remember keep the coach restriction change', self.report['prompt_ids'][-1])
        leo['update_id'] = 97
        self.bot.consume_updates([leo], TODAY)
        self.assertEqual([entry['user_id'] for entry in active_memory(self.bot.s)], [99, 42])
        self.assertEqual(len(self.report['pending_feedback']), 2)
        self.bot.advance(TODAY)
        self.assertIn('remember', self.llm.call_args.args[1])
        self.assertIn('Feedback marked remember has been saved', self.tg.call.call_args.kwargs['text'])
        self.assertFalse(self.sends_to_channel())

    def test_ordinary_feedback_and_invalid_trigger_text_do_not_create_memory(self):
        for index, text in enumerate(['keep commentary short change', 'I remembered this change',
                                      'unremembered idea change', 'please remember this',
                                      'remember this Change', 'remember change please']):
            self.bot.process(self.owner_update(text, 96 + index), TODAY)
        self.assertNotIn('memory', self.bot.s)

    def test_unauthorized_unthreaded_stale_edited_and_expired_replies_cannot_save_memory(self):
        base = self.owner_update('remember keep commentary short change')
        for changes in ({'from': {'id': 100}}, {'chat': {'id': -201, 'type': 'supergroup'}},
                        {'forward_origin': {'type': 'user'}}, {'sender_chat': {'id': -200}},
                        {'from': {'id': 99, 'is_bot': True}}, {'reply_to_message': {}},
                        {'reply_to_message': {'message_id': 0}}):
            update = deepcopy(base)
            update['message'].update(changes)
            self.bot.process(update, TODAY)
        self.bot.process({'update_id': 97, 'edited_message': base['message']}, TODAY)
        self.bot.process(base, TARGET)
        self.assertNotIn('memory', self.bot.s)
        self.llm.assert_not_called()

    def test_memory_and_feedback_are_saved_before_webhook_ack_or_llm(self):
        def ack(update_id):
            saved = Store(self.path).data
            self.assertEqual(update_id, 96)
            self.assertEqual(saved['memory']['entries'][0]['source_date'], TARGET)
            self.assertEqual(saved['reports'][TARGET]['status'], 'revision_pending')
            self.assertEqual(saved['reports'][TARGET]['feedback_log'][0]['memory_id'], 1)
            self.llm.assert_not_called()
        self.bot.consume_updates([self.owner_update('remember short captions change')], TODAY, ack=ack)

    def test_checkpoint_failure_does_not_ack_or_call_llm(self):
        self.store.save = Mock(side_effect=RuntimeError('Git checkpoint failed'))
        ack = Mock()
        with self.assertRaises(RuntimeError):
            self.bot.consume_updates([self.owner_update('remember short captions change')], TODAY, ack=ack)
        self.assertNotIn('memory', Store(self.path).data)
        ack.assert_not_called()
        self.llm.assert_not_called()

    def test_ack_failure_retry_does_not_save_the_same_memory_twice(self):
        update = self.owner_update('remember short captions change')
        with self.assertRaises(RuntimeError):
            self.bot.consume_updates([update], TODAY, ack=Mock(side_effect=RuntimeError('ack failed')))
        restarted = Review(Store(self.path), self.tg, 42, -200, -100, self.llm, owner=99)
        restarted.consume_updates([update], TODAY, ack=Mock())
        self.assertEqual(len(restarted.s['memory']['entries']), 1)
        self.assertEqual(restarted.s['memory']['next_id'], 2)

    def test_saved_memory_survives_a_failed_current_revision(self):
        self.remember()
        self.llm.side_effect = SafeError('Gemini revision HTTP 429: quota exhausted.')
        with self.assertRaises(SafeError):
            self.bot.advance(TODAY)
        saved = Store(self.path).data
        self.assertEqual(len(active_memory(saved)), 1)
        self.assertEqual(saved['reports'][TARGET]['status'], 'revision_pending')
        self.assertFalse(self.sends_to_channel())

    def test_new_day_applies_saved_feedback_to_fresh_data_before_review_and_still_needs_approval(self):
        self.remember()
        report = self.future()
        saved = Store(self.path).data['reports'][FUTURE_DATE]
        self.assertTrue(saved['memory_pending'])
        self.assertEqual(saved['draft_ids'] + saved['prompt_ids'], [])
        self.llm.assert_not_called()
        def memory_edit(draft, feedback):
            self.assertEqual(feedback, APPLY_MEMORY)
            self.assertEqual(draft['date'], FUTURE_DATE)
            self.assertEqual(draft['forecast']['daily'][0]['date'], FUTURE_DATE)
            self.assertEqual(draft['remembered_feedback'][0]['source_date'], TARGET)
            self.assertTrue(Store(self.path).data['reports'][FUTURE_DATE]['memory_pending'])
            return [FUTURE_DATE + ' report using the saved style']
        self.llm.side_effect = memory_edit
        self.bot.advance(FUTURE_TODAY)
        self.assertEqual(report['parts'], [FUTURE_DATE + ' report using the saved style'])
        self.assertFalse(report['memory_pending'])
        self.assertEqual(report['status'], 'review')
        self.assertFalse(self.sends_to_channel())
        self.bot.advance(FUTURE_TODAY)
        self.llm.assert_called_once()
        approval = self.message('correct', report['prompt_ids'][-1], **{'from': {'id': 99}})
        self.bot.process(approval, FUTURE_TODAY)
        self.bot.advance(FUTURE_TODAY)
        self.bot.advance(FUTURE_TODAY)
        self.assertEqual(len(self.sends_to_channel()), 1)

    def test_failed_future_memory_application_keeps_delivery_pending_and_retries_without_a_partial_report(self):
        self.remember()
        report = self.future()
        self.llm.side_effect = SafeError('Gemini revision HTTP 429: quota exhausted.')
        self.tg.reset_mock()
        with self.assertRaises(SafeError):
            self.bot.advance(FUTURE_TODAY)
        saved = Store(self.path).data['reports'][FUTURE_DATE]
        self.assertTrue(saved['memory_pending'])
        self.assertEqual(saved['draft_ids'] + saved['prompt_ids'], [])
        self.assertEqual(len(self.tg.call.call_args_list), 1)  # One failure notice, no draft.
        with self.assertRaises(SafeError):
            self.bot.advance(FUTURE_TODAY)
        self.assertEqual(len(self.tg.call.call_args_list), 1)
        self.llm.side_effect = None
        self.bot.advance(FUTURE_TODAY)
        self.assertEqual(report['status'], 'review')
        self.assertEqual(len(self.tg.call.call_args_list), 3)
        self.assertFalse(self.sends_to_channel())

    def test_an_uncertain_send_blocks_memory_model_calls_and_all_new_messages(self):
        self.remember()
        report = self.future()
        report['intent'] = {'kind': 'draft'}
        self.store.save()
        self.tg.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'Uncertain send'):
            self.bot.advance(FUTURE_TODAY)
        self.llm.assert_not_called()
        self.tg.call.assert_not_called()

    def test_memory_cannot_rewrite_a_report_after_partial_delivery(self):
        self.remember()
        report = self.future()
        report['draft_ids'] = [500]
        self.tg.reset_mock()
        with self.assertRaisesRegex(SafeError, 'delivery has begun'):
            self.bot.advance(FUTURE_TODAY)
        self.llm.assert_not_called()
        self.tg.call.assert_not_called()

    def test_memory_list_and_forget_are_authenticated_group_commands_with_durable_audit(self):
        self.remember()
        update = self.owner_update('/memory@surf_test_bot', 97)
        self.assertEqual(self.bot.consume_updates([update], TODAY), {'memory_requested'})
        self.assertIn('1. Please remember', self.bot.s['outbox']['memory:-200:97']['parts'][0])
        unauthorized = self.owner_update('/forget 1', 98)
        unauthorized['message']['from']['id'] = 100
        self.bot.consume_updates([unauthorized], TODAY)
        self.assertEqual(len(active_memory(self.bot.s)), 1)
        leo = self.message('/forget@surf_test_bot 1')
        leo['update_id'] = 99
        self.assertEqual(self.bot.consume_updates([leo], TODAY), {'memory_forgotten'})
        saved = Store(self.path).data
        self.assertEqual(active_memory(saved), [])
        self.assertFalse(saved['memory']['entries'][0]['active'])
        self.assertEqual(saved['memory']['entries'][0]['forgotten_by'], 42)
        self.assertEqual(saved['reports'][TARGET]['feedback_log'][0]['memory_id'], 1)

    def test_forget_removes_instruction_from_new_reports_without_erasing_history_or_reusing_ids(self):
        self.remember()
        self.bot.consume_updates([self.owner_update('/forget 1', 97)], TODAY)
        report = self.future()
        self.assertNotIn('remembered_feedback', report)
        self.bot.advance(FUTURE_TODAY)
        self.llm.assert_not_called()
        update = self.message('remember use full sentences change', report['prompt_ids'][-1])
        update['update_id'] = 100
        self.bot.consume_updates([update], FUTURE_TODAY)
        self.assertEqual([entry['id'] for entry in self.bot.s['memory']['entries']], [1, 2])
        self.assertEqual([entry['id'] for entry in active_memory(self.bot.s)], [2])

    def test_missing_or_wrong_bot_forget_command_does_not_disable_memory(self):
        self.remember()
        for text in ('/forget', '/forget 999', '/forget@another_bot 1'):
            self.bot.process(self.owner_update(text, 100), TODAY)
            self.assertEqual(len(active_memory(self.bot.s)), 1)

    def test_preview_uses_saved_feedback_without_changing_the_current_approval_cycle(self):
        self.remember()
        self.bot.advance(TODAY)
        before = deepcopy(self.report)
        self.bot.forecast = Mock(return_value=Forecast(TARGET, 'Test spot', {'fresh': True}, [TARGET + ' preview']))
        self.llm.reset_mock()
        self.llm.return_value = [TARGET + ' preview with the saved style']
        self.bot.consume_updates([self.owner_update('/dryrun@surf_test_bot', 97)], TODAY)
        self.bot.advance(TODAY)
        self.llm.assert_called_once()
        self.assertEqual(self.llm.call_args.args[1], APPLY_MEMORY)
        self.assertEqual(self.report, before)
        self.assertIn('preview with the saved style', self.bot.s['outbox']['dryrun:97']['parts'][0])
        self.assertFalse(self.sends_to_channel())

    def test_manual_test_after_publication_applies_memory_to_fresh_forecast_and_requires_new_approval(self):
        self.remember()
        self.bot.advance(TODAY)
        self.bot.process(self.owner_update('correct', 97), TODAY)
        self.bot.advance(TODAY)
        self.bot.forecast = Mock(return_value=Forecast(TARGET, 'Test spot', {'fresh': True}, [TARGET + ' fresh report']))
        self.llm.reset_mock()
        self.bot.reopen_published(TARGET, TODAY, '12345')
        report = self.bot.s['reports'][TARGET]
        self.assertTrue(report['memory_pending'])
        self.bot.advance(TODAY)
        self.llm.assert_called_once()
        self.assertEqual(report['status'], 'review')
        self.assertEqual(len(self.sends_to_channel()), 1)  # Earlier publication only.
        self.assertEqual(len(report['publication_history']), 1)

    def test_old_states_upgrade_without_reset_and_corrupt_memory_fails_closed(self):
        self.assertNotIn('memory', Store(self.path).data)
        self.remember()
        original = json.loads(self.path.read_text())
        for corruption in ('missing_entries', 'duplicate_id', 'bad_next_id', 'non_boolean_active', 'wrong_version'):
            state = deepcopy(original)
            memory = state['memory']
            if corruption == 'missing_entries':
                memory.pop('entries')
            elif corruption == 'duplicate_id':
                memory['entries'].append(deepcopy(memory['entries'][0]))
            elif corruption == 'bad_next_id':
                memory['next_id'] = 1
            elif corruption == 'non_boolean_active':
                memory['entries'][0]['active'] = 'true'
            else:
                memory['version'] = 2
            self.path.write_text(json.dumps(state))
            with self.assertRaises(ValueError):
                Store(self.path)
        self.assertEqual(original['offset'], 97)
        self.assertEqual(original['binding'], [42, -200, -100])

    def test_provider_receives_only_active_memory_text_and_current_forecast_with_normal_validation(self):
        self.remember()
        report = self.future()
        response = Mock(status_code=200)
        result = '\n\n'.join(report['parts'])
        response.json.return_value = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': result}]}}]}
        post = Mock(return_value=response)
        with patch.dict('os.environ', {'LLM_PROVIDER': 'gemini', 'GEMINI_MODEL': 'gemini-test',
                                       'GEMINI_API_KEY': 'PRIVATE_KEY'}, clear=True), \
                patch.dict('sys.modules', {'requests': Mock(post=post)}):
            revised = revise(report, APPLY_MEMORY)
            self.assertTrue(revised)
            context = json.loads(post.call_args.kwargs['json']['contents'][0]['parts'][0]['text'])
            self.assertEqual(context['remembered_feedback'], ['Please remember to keep commentary short change'])
            self.assertEqual(context['date'], FUTURE_DATE)
            self.assertEqual(context['forecast']['analysis_window'], {'start': '06:00', 'end': '18:00'})
            self.assertNotIn('user_id', json.dumps(context))
            self.assertNotIn('PRIVATE_KEY', json.dumps(context))
            response.json.return_value['candidates'][0]['content']['parts'] = [
                {'text': result + '\nWind 987.65 km/h'}]
            with self.assertRaisesRegex(SafeError, 'unsupported number'):
                revise(report, APPLY_MEMORY)

    def test_memory_times_cannot_bypass_the_daylight_validator(self):
        self.remember('remember consider 19:00–20:00 change')
        report = self.future()
        response = Mock(status_code=200)
        response.json.return_value = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{
            'text': "Forecast date: 1 November 2026\n\n📍OLD MAN'S / BATU BOLONG\n\n🔵 ADVANCED\n19:00–20:00"}]}}]}
        with patch.dict('os.environ', {'LLM_PROVIDER': 'gemini', 'GEMINI_MODEL': 'gemini-test',
                                       'GEMINI_API_KEY': 'PRIVATE_KEY'}, clear=True), \
                patch.dict('sys.modules', {'requests': Mock(post=Mock(return_value=response))}):
            with self.assertRaisesRegex(SafeError, 'rounded daylight window'):
                revise(report, APPLY_MEMORY)

    def test_group_move_preserves_pending_memory_application(self):
        self.remember()
        report = self.future()
        moved = Review(self.store, self.tg, 42, -300, -100, self.llm,
                       move_chat=True, owner=99)
        pending = moved.s['reports'][FUTURE_DATE]
        self.assertTrue(pending['memory_pending'])
        self.assertEqual(pending['remembered_feedback'], report['remembered_feedback'])
        self.assertEqual(len(active_memory(moved.s)), 1)


if __name__ == '__main__':
    unittest.main()
