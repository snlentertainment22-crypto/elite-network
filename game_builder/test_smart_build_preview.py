"""Offline safety checks for Smart Build preview."""
from __future__ import annotations
import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

from .game_intelligence import HOME
from .smart_build_preview import create_preview, export_preview, _suggested_wrong_answers, sports_category_family, sport_topic_for_question, _pick_sports_block, _rebalance_sports_difficulty, _sports_round_diagnostics


class SmartBuildPreviewTests(unittest.TestCase):
    def test_unverified_options_are_validated(self):
        self.assertEqual(_suggested_wrong_answers('["A","B","C","D","E","A"]','F'),['A','B','C','D','E'])
        self.assertEqual(_suggested_wrong_answers('["A","B","C","D","F"]','F'),[])
        self.assertEqual(_suggested_wrong_answers('bad json','F'),[])

    def test_league_and_sport_categories_are_recognized(self):
        # The sports matcher already exists in question_pools. Ensure the
        # new balancing code assigns the appropriate family without changing it.
        expected = {
            'NFL': 'FOOTBALL', 'NHL': 'HOCKEY', 'NBA': 'BASKETBALL',
            'MLB': 'BASEBALL', 'Golf': 'GOLF', 'Racing/NASCAR': 'RACING',
            'Sports/Tennis': 'TENNIS', 'Soccer': 'SOCCER',
            'Sports': 'GENERAL SPORTS', 'Sports/Geography': 'OTHER SPORTS SUBCATEGORY',
        }
        for category, family in expected.items():
            with self.subTest(category=category):
                self.assertEqual(sports_category_family(category), family)

    def test_generically_labeled_sports_question_gets_conservative_topic_hint(self):
        self.assertEqual(
            sport_topic_for_question({'category':'Sports',
                                       'question':'Which NHL team won the Stanley Cup?'}),
            ('HOCKEY', 'QUESTION_KEYWORD_PROVISIONAL'))
        self.assertEqual(
            sport_topic_for_question({'category':'Sports',
                                       'question':'Who was the most famous athlete?'}),
            ('GENERAL SPORTS', 'NO_CATEGORY_SUBTYPE'))
        self.assertEqual(
            sport_topic_for_question({'category':'Sports',
                                       'question':'Which former NBA player won the Heisman Trophy?'}),
            ('MIXED SPORTS TOPICS', 'MULTIPLE_QUESTION_KEYWORDS'))

    def test_sports_leagues_spread_across_all_three_games(self):
        # Before this change, the 18 specifically labeled questions were all
        # consumed by Sports Game 1, leaving only generic Sports for 2 and 3.
        sample = []
        for n in range(54):
            sample.append({'id':n+1, 'question':f'General sports {n}',
                           'category':'Sports', 'historical_smoothed_accuracy':None})
        leagues = ['NFL','NHL','NBA','MLB','Golf','Racing']
        for n in range(18):
            sample.append({'id':55+n,'question':f'League sports {n}',
                           'category':leagues[n%6], 'historical_smoothed_accuracy':None})
        selected,reason = _pick_sports_block(sample,set(),set(),20261009)
        self.assertIsNone(reason)
        self.assertEqual([len(g) for g in selected],[24,24,24])
        self.assertEqual(len({q['id'] for game in selected for _,_,q in game}),72)
        self.assertEqual([sum(sports_category_family(q['category']) != 'GENERAL SPORTS'
                              for _,_,q in game) for game in selected],[6,6,6])
        for game in selected:
            # Different leagues must be visible in all games, not consumed in game 1.
            self.assertGreaterEqual(len({sports_category_family(q['category'])
                                         for _,_,q in game if q['category'] != 'Sports'}),3)

    def test_rebalancing_preserves_all_questions_and_slots(self):
        sample = []
        for i in range(72):
            score = ([0.86,0.75,0.64,0.53,0.42,0.30,0.22][i%7]
                     if i < 21 else None)
            sample.append({'id':i, 'question':f'Unique sports question {i}',
                           'category':['NFL','NBA','MLB','Sports'][i%4],
                           'historical_smoothed_accuracy':score})
        before, reason = _pick_sports_block(sample,set(),set(),1)
        self.assertIsNone(reason)
        result = _rebalance_sports_difficulty(before,1)
        self.assertEqual([len(game) for game in result],[24]*3)
        self.assertEqual({q['id'] for game in before for _,_,q in game},
                         {q['id'] for game in result for _,_,q in game})
        self.assertEqual(len({q['id'] for game in result for _,_,q in game}),72)
        self.assertEqual(_rebalance_sports_difficulty(before,1),result)
        self.assertEqual(len(_sports_round_diagnostics(result)),12)

    def test_live_sports_difficulty_warning_is_explicit(self):
        db=HOME/'question_bank.sqlite3'
        rows,summary=create_preview(db,date(2026,10,8),20261009)
        sports=[r for r in rows if r['game_type']=='SPORTS_BLITZ']
        self.assertEqual(len(sports),72)
        opening=[r for r in sports if r['slot'].startswith('R1')]
        # The known ~27% answer must not be left in an opening round.
        self.assertFalse(any(r['eq_id']=='EQ020562' for r in opening))
        self.assertTrue(summary['sports_round_diagnostics'])
        self.assertFalse(summary['publication_allowed'])
        self.assertEqual(sum(r['historical_accuracy_pct']!='' for r in sports),21)

    def test_select_and_export_do_not_touch_database(self):
        db=HOME/'question_bank.sqlite3'
        before=hashlib.sha256(db.read_bytes()).hexdigest()
        rows,summary=create_preview(db,date(2026,10,8),20261009)
        with tempfile.TemporaryDirectory() as work:
            export_preview(rows,summary,Path(work))
            self.assertTrue((Path(work)/'smart_build_preview_questions.csv').exists())
            self.assertTrue((Path(work)/'smart_build_preview_summary.json').exists())
        self.assertEqual(before,hashlib.sha256(db.read_bytes()).hexdigest())
        self.assertFalse(summary['publication_allowed'])
        self.assertEqual(len(summary['games']),9)
        self.assertEqual(sum(g['positions'] for g in summary['games']),len(rows))
        self.assertEqual(len({r['eq_id'] for r in rows}),len(rows))
        self.assertEqual(len({r['question'].casefold().strip() for r in rows}),len(rows))
        self.assertEqual(sum(g['status']=='BLOCKED' for g in summary['games'] if g['game_type']=='AFTER_DARK_BLITZ'),3)
        self.assertTrue(all(r['approval_status'].startswith('NEEDS_') for r in rows))


if __name__=='__main__': unittest.main()
