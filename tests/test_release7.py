import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from recommendations import batu_recommend, windy_hour, wave_line
from review_bot import Store, Review

class ReleaseSeven(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / 'fixtures/november_2_2026.json'
        report = json.loads(fixture.read_text())
        self.data = report['forecast']
        self.date, self.name = report['date'], report['name']
        self.today = '2026-11-01'
        self.day = next(d for d in self.data['daily'] if d['date'] == self.date)
        self.row = copy.deepcopy(self.day['hourly'][6])
        self.row['rating']['key'] = 'POOR_TO_FAIR'
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 'state.json'
        path.write_text(json.dumps(dict(version=1, reports={}, offset=0, started=True)))
        self.store = Store(path)
        self.tg = Mock()
        self.tg.call.side_effect = lambda *args, **kw: {'message_id': self.tg.call.call_count}
        self.bot = Review(self.store, self.tg, 11, 11, -100)
        timer = patch('review_bot.time.sleep')
        timer.start()
        self.addCleanup(timer.stop)

    def test_rating_and_rounded_wind(self):
        for rating, speeds in [('POOR_TO_FAIR', (15,16)), ('FAIR',(19,20))]:
            self.row['rating']['key'] = rating
            for expected, speed in zip((False, True), speeds):
                self.row['wind']['speed_kts'] = speed / 1.852
                self.assertEqual(windy_hour(self.row), expected)

    def test_low_tide_exception_and_high_tide_minimum(self):
        for tide, energy, allowed in [(.5,60,True),(.5,400,True),(.75,399,False),(.75,400,True)]:
            self.row['energy']['nearshore'] = energy
            for tier in ('beginner','intermediate','advanced'):
                advice = batu_recommend(self.row, {'height_m':tide}, tier)
                self.assertEqual(advice['status']=='suitable to consider', allowed)

    def test_partial_wave_height_does_not_claim_all_day(self):
        intervals = [dict(start=i*3600, end=(i+1)*3600, row={'surf_human':label})
                     for i,label in enumerate(('Chest',None,'Shoulder'))]
        text = wave_line(intervals)
        self.assertIn('chest',text)
        self.assertIn('shoulder',text)
        self.assertNotIn('all day',text)

    def reply(self, text, msg, seq):
        return self.bot.process({'update_id':seq,'message':{'text':text,'chat':{'type':'private','id':11},
                                'from':{'id':11},'reply_to_message':{'message_id':msg}}}, self.today)

    def test_uncovered_case_waits_then_learns_and_rebuilds(self):
        row = next(r for r in self.day['hourly'] if r['local_hour']==8)
        row['rating']['key'] = 'NEW_PROVIDER_RATING'
        row['energy']['nearshore'] = 450
        self.bot.generate(self.date,self.data,self.name)
        self.bot.advance(self.today)
        report = self.store.data['reports'][self.date]
        self.assertEqual(self.tg.call.call_count,1)
        question = report['question_ids'][0]
        self.bot.advance(self.today)
        self.assertEqual(self.tg.call.call_count,1)
        self.assertEqual(self.reply('Intermediate and advanced outside',question,101),'rule_answer')
        self.store.save()
        self.bot = Review(Store(self.store.path), self.tg, 11, 11, -100)
        with patch('rule_questions.interpret',return_value=['intermediate','advanced']) as model:
            self.bot.advance(self.today)
            model.assert_called_once()
        report = self.bot.s['reports'][self.date]
        self.assertEqual(report['status'],'review')
        self.assertEqual(len(self.bot.s['surf_rules']),1)
        self.assertIn('08:00', '\n'.join(report['parts']))
        self.assertEqual(self.reply('correct',question,102),'ignored_stale_prompt')
        self.assertFalse(any(c.kwargs['chat_id']==-100 for c in self.tg.call.call_args_list))
        from rule_questions import attach_rules
        later = dict(report,forecast=copy.deepcopy(self.data))
        self.assertIsNone(attach_rules(later,self.bot.s['surf_rules']))

    def test_failure_message_cancel_accepts_replacement_on_original_prompt(self):
        self.bot.generate(self.date,self.data,self.name)
        self.bot.advance(self.today)
        report = self.bot.s['reports'][self.date]
        prompt = report['prompt_ids'][0]
        self.bot.revision = Mock(side_effect=ValueError())
        self.reply('shorten report change',prompt,101)
        with self.assertRaises(ValueError):
            self.bot.advance(self.today)
        failure = report['failure_ids'][0]
        self.assertEqual(self.reply('correct',failure,102),'ignored_stale_prompt')
        self.assertEqual(self.reply('cancel change',failure,103),'revision_cancelled')
        self.assertEqual(self.reply('correct',prompt,104),'ignored_not_reviewing')
        self.assertEqual(self.reply('remove caution change',prompt,105),'revision_pending')
