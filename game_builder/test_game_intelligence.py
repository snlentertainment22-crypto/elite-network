"""Offline checks for Elite Intelligence Bridge; no API calls or data writes."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from .game_intelligence import analyze, _choice_status, _round_target, HOME


class IntelligenceBridgeTests(unittest.TestCase):
    def test_choice_validation(self):
        self.assertTrue(_choice_status('["A","B","C","D","E"]', 'F'))
        self.assertFalse(_choice_status('["A","B","C","D","A"]', 'F'))
        self.assertFalse(_choice_status('["A","B","C","D","E"]', 'A'))
        self.assertFalse(_choice_status('["A","B","C"]', 'D'))

    def test_targets_are_editorial_not_predictions(self):
        self.assertEqual([_round_target(n) for n in (1,2,3,4)], [0.79,0.65,0.56,0.49])

    def test_read_only_against_provided_database(self):
        db=HOME/'question_bank.sqlite3'
        before=hashlib.sha256(db.read_bytes()).hexdigest()
        details,games,inventory=analyze(db)
        after=hashlib.sha256(db.read_bytes()).hexdigest()
        self.assertEqual(before, after, 'Database changed during read-only analysis')
        self.assertEqual((len(games),len(details)),(9,216))
        self.assertEqual(sum('MISSING_OR_INVALID_FIVE_DISTRACTORS' in r['flags'] for r in details),5)
        self.assertEqual(sum('FACT_CHECK_REQUIRED' in r['flags'] for r in details),2)
        self.assertEqual(next(r for r in inventory if r['pool']=='after_dark')['total_master'],79)


if __name__=='__main__':unittest.main()
