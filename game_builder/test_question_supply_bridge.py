import json
import unittest
from pathlib import Path
from .question_supply_bridge import build_request

class SupplyBridgeTests(unittest.TestCase):
    def sample(self):
        return {'kind':'READ_ONLY_UNAPPROVED_SMART_SELECTION_PREVIEW',
                'publication_allowed':False,'as_of':'2026-10-08','seed':20261009,
                'games':([{'game_type':'SPORTS_BLITZ','positions':24}]*3
                         +[{'game_type':'REGULAR_BLITZ','positions':24}]*3
                         +[{'game_type':'AFTER_DARK_BLITZ','positions':0}]*3),
                'inventory':{'sports':{'unapproved_candidate_with_five_options':74},
                             'regular':{'unapproved_candidate_with_five_options':838},
                             'after_dark':{'unapproved_candidate_with_five_options':1}},
                'sports_round_diagnostics':[{'game':'SPORTS-1','round':'R4','flags':['SPARSE_HISTORY'],'target_editorial_pct':49,'observed_questions':1}]}
    def test_shortage_calculation(self):
        requests=build_request(self.sample())['requests']
        self.assertEqual([(x['pool'],x['minimum_additional_candidates']) for x in requests],
                        [('sports',0),('regular',0),('after_dark',71)])
        self.assertEqual(requests[0]['additional_candidates_for_24_spare'],22)
        self.assertEqual(requests[2]['additional_candidates_for_24_spare'],95)
    def test_never_dispatched_or_paid(self):
        result=build_request(self.sample())
        self.assertFalse(result['auto_dispatch'])
        self.assertFalse(result['openai_api_calls_allowed'])
        self.assertFalse(result['write_to_master_allowed'])
        self.assertFalse(result['automatic_credit_recharge_allowed'])
        self.assertEqual(result['cost_policy']['pre_authorized_generation_budget_usd'],0)
    def test_refuse_approved_or_wrong_input(self):
        sample=self.sample();sample['publication_allowed']=True
        with self.assertRaises(ValueError):build_request(sample)
        sample['publication_allowed']=False;sample['kind']='X'
        with self.assertRaises(ValueError):build_request(sample)
    def test_round_flags_preserved(self):
        result=build_request(self.sample())
        self.assertEqual(len(result['sports_review_flags']),1)

if __name__=='__main__':unittest.main()
