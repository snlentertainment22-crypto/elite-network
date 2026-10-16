"""ELITE read-only Question Maker request draft from Smart Build V3 summary.

Does NOT call Question Maker, OpenAI, Google Sheets, or modify saved games.
Produces a review-only, never-auto-dispatched JSON manifest.

Usage from ELITE NETWORK GAME BUILDER 1A root:
  py -m game_builder.question_supply_bridge
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path

DEFAULT_BUFFER_PER_POOL=24


def build_request(summary, buffer_per_pool=DEFAULT_BUFFER_PER_POOL):
    if summary.get('kind') != 'READ_ONLY_UNAPPROVED_SMART_SELECTION_PREVIEW':
        raise ValueError('Expected Smart Build read-only preview summary')
    if summary.get('publication_allowed') is not False:
        raise ValueError('Refusing a summary that claims publication approval')
    games=summary.get('games') or []
    inv=summary.get('inventory') or {}
    requests=[]
    for pool,kind,category in [
        ('sports','SPORTS_BLITZ','Sports'),
        ('regular','REGULAR_BLITZ','Regular'),
        ('after_dark','AFTER_DARK_BLITZ','After Dark')]:
        matching=[g for g in games if g.get('game_type')==kind]
        required=sum(24 for _ in matching)
        selected=sum(int(g.get('positions') or 0) for g in matching)
        ready=int((inv.get(pool) or {}).get('unapproved_candidate_with_five_options') or 0)
        minimum_deficit=max(0,required-ready)
        buffer_deficit=max(0,required+buffer_per_pool-ready)
        requests.append({
            'pool':pool,'maker_category':category,'game_count':len(matching),
            'target_positions':required,'preview_selected':selected,
            'unused_five_option_candidates_UNAPPROVED':ready,
            'minimum_additional_candidates':minimum_deficit,
            'additional_candidates_for_24_spare':buffer_deficit,
            'candidate_status':'REVIEW_REQUIRED_NO_APPROVAL',
            'choice_count_for_future_multiple_choice':6,
            'generation_dispatch':'DISABLED',
            'notes': ('Topic-specific easy/medium balance requires editorial review;'
                      ' current Question Maker does not enforce historical accuracy.' if pool=='sports' else
                      'After Dark needs approved content-policy and format instructions before dispatch.' if pool=='after_dark' else
                      'Large candidate inventory; verify questions and distractors before publishing.')
        })
    sports_flags=[]
    for item in summary.get('sports_round_diagnostics') or []:
        if item.get('flags'):
            sports_flags.append({'game':item.get('game'),'round':item.get('round'),
                                 'target_editorial_pct':item.get('target_editorial_pct'),
                                 'flags':item.get('flags'),
                                 'history_count':item.get('observed_questions')})
    return {
        'schema_version':1,
        'kind':'ELITE_QUESTION_SUPPLY_REQUEST_REVIEW_ONLY',
        'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'source_as_of':summary.get('as_of'),
        'source_seed':summary.get('seed'),
        'auto_dispatch':False,
        'openai_api_calls_allowed':False,
        'approval_required':True,
        'write_to_master_allowed':False,
        'automatic_credit_recharge_allowed':False,
        'cost_policy':{'low_balance_warning_usd':5.00,
                       'pre_authorized_generation_budget_usd':0.00,
                       'balance_from_live_openai_account':'UNKNOWN_NOT_QUERIED'},
        'requests':requests,'sports_review_flags':sports_flags,
        'handoff_status':'NOT_CONNECTED_TO_QUESTION_MAKER_YET',
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary',default='intelligence_review/smart_build_preview_summary.json')
    parser.add_argument('--output',default='intelligence_review/question_supply_request_draft.json')
    args=parser.parse_args(argv)
    summary=json.loads(Path(args.summary).read_text(encoding='utf-8-sig'))
    result=build_request(summary)
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('ELITE QUESTION SUPPLY BRIDGE — REQUEST DRAFT ONLY')
    for req in result['requests']:
        print(req['pool'].upper(), 'target:',req['target_positions'],
              'current options-ready (UNAPPROVED):',req['unused_five_option_candidates_UNAPPROVED'],
              'minimum new:',req['minimum_additional_candidates'],
              '24-spare target gap:',req['additional_candidates_for_24_spare'])
    print('Sports flagged rounds:',len(result['sports_review_flags']))
    print('API CALLS: ZERO | SHEET WRITES: ZERO | DISPATCH: DISABLED')
    print('Draft:',output.resolve())
    return 0

if __name__=='__main__': raise SystemExit(main())
