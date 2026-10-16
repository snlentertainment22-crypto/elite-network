"""ELITE NETWORK — Game Intelligence Bridge V1 (read-only).

Reads the copied Network database and matched historical archives to assess
saved games and candidate inventory. It NEVER changes source questions,
approves distractors, creates games, marks usage, or spends AI tokens.

Usage: python -m game_builder.game_intelligence --report-dir ./intelligence_review
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from .question_pools import get_question_pools

HOME = Path(__file__).resolve().parent
DATA_DIR = HOME / 'intelligence_data'
BAD_QUESTION_FLAGS = {
    'EQ003845': 'FACT_CHECK_REQUIRED_FACEBOOK_YEAR',
    'EQ008017': 'FACT_CHECK_REQUIRED_MISMATCHED_ANSWER',
}


def _csv_map(name):
    file = DATA_DIR / name
    with file.open('r', encoding='utf-8-sig', newline='') as f:
        return {r['eq_id']: r for r in csv.DictReader(f)}


def _parse_json(raw, expected, default):
    try:
        obj = json.loads(raw or '')
    except (ValueError, TypeError):
        return default
    return obj if isinstance(obj, expected) else default


def _choice_status(raw, answer):
    options = _parse_json(raw, list, [])
    if len(options) != 5:
        return False
    normalize = lambda v: ' '.join(str(v or '').casefold().strip().split())
    wrong = [normalize(v) for v in options]
    correct = normalize(answer)
    return bool(correct) and all(wrong) and correct not in wrong and len(set(wrong)) == 5


def _round_target(round_no):
    # Selection goals only, not predictions of new/unplayed questions.
    return {1: 0.79, 2: 0.65, 3: 0.56, 4: 0.49}.get(round_no)


def analyze(db_path: Path, reference_date: date | None = None):
    """Return detailed rows, game summaries and pool counts. No writes."""
    reference_date = reference_date or date.today()
    hist = _csv_map('historical_performance_v1.csv')
    candidates = _csv_map('historical_distractor_candidates_v1.csv')
    connection = sqlite3.connect('file:' + str(db_path.resolve()) + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        question_rows = connection.execute('SELECT id,source_key,category,wrong_answers_json,correct_answer FROM questions').fetchall()
        used_in_game = {int(r[0]) for r in connection.execute('SELECT DISTINCT question_id FROM game_questions')}
        pool_count = Counter(); ready_count = Counter(); unused_ready = Counter()
        for r in question_rows:
            eligible = get_question_pools(r['category'])
            for name, is_in in eligible.items():
                if not is_in: continue
                pool_count[name] += 1
                if _choice_status(r['wrong_answers_json'], r['correct_answer']):
                    ready_count[name] += 1
                    if int(r['id']) not in used_in_game: unused_ready[name] += 1

        rows=[]
        query='''SELECT g.id game_id,g.game_key,g.title,g.game_type,g.status game_status,
           gq.slot_id,gq.round_number,gq.question_number,gq.question_type,
           gq.question_snapshot_json,gq.choices_json,gq.correct_index,
           q.id internal_id,q.source_key,q.category,q.question,q.correct_answer,
           q.wrong_answers_json,q.network_status,q.roulette_hint
           FROM games g JOIN game_questions gq ON gq.game_id=g.id
           JOIN questions q ON q.id=gq.question_id
           WHERE g.id>=11 ORDER BY g.id,gq.display_order'''
        for r in connection.execute(query):
            eq=r['source_key']
            snap=_parse_json(r['question_snapshot_json'],dict,{})
            edit=snap.get('game_edit') if isinstance(snap.get('game_edit'),dict) else {}
            question=edit.get('question') or r['question']
            correct=edit.get('correct_answer') or r['correct_answer']
            wrong=edit.get('wrong_answers') if isinstance(edit.get('wrong_answers'),list) else _parse_json(r['wrong_answers_json'],list,[])
            # Effective five-wrong validation (excluding typed final wager).
            valid_wrong=_choice_status(json.dumps(wrong,ensure_ascii=False),correct)
            hist_row=hist.get(eq,{})
            n=int(hist_row.get('responses') or 0)
            sessions=int(hist_row.get('distinct_sessions') or 0)
            correct_count=int(hist_row.get('correct') or 0)
            confidence=('MODERATE' if n>=30 and sessions>=2 else
                        'LIMITED' if n>=12 and sessions>=2 else 'INSUFFICIENT')
            # Bayesian shrinkage: evidence only. No claim of a future accuracy forecast.
            smoothed=(correct_count + 10*0.65)/(n+10) if n else None
            last=hist_row.get('last_seen') or ''
            recent=False
            try:recent=date.fromisoformat(last)>=reference_date-timedelta(days=183)
            except ValueError:pass
            available=candidates.get(eq,{})
            suggested=int(available.get('unique_suggested_wrongs') or 0)
            flags=[]
            if not question.strip() or not correct.strip(): flags.append('BLANK_QUESTION_OR_ANSWER')
            if r['question_type']!='final_wager' and not valid_wrong: flags.append('MISSING_OR_INVALID_FIVE_DISTRACTORS')
            if eq in BAD_QUESTION_FLAGS:flags.append(BAD_QUESTION_FLAGS[eq])
            if r['question_type']=='roulette' and not (edit.get('roulette_hint') or r['roulette_hint']):flags.append('ROULETTE_HINT_REQUIRED')
            if recent:flags.append('RECENT_HISTORICAL_PLAY_REVIEW_REUSE_POLICY')
            if not get_question_pools(r['category']).get('after_dark' if r['game_type']=='AFTER_DARK_BLITZ' else 'sports' if r['game_type']=='SPORTS_BLITZ' else 'regular',False): flags.append('CATEGORY_POOL_MISMATCH')
            if confidence=='INSUFFICIENT':flags.append('DIFFICULTY_NOT_MEASURED_RELIABLY')
            rows.append({
                'game_key':r['game_key'],'game_type':r['game_type'],'slot':r['slot_id'],
                'round':r['round_number'],'question_number':r['question_number'],'eq_id':eq,
                'category':r['category'],'question':question,'correct_answer':correct,
                'valid_five_distractors':valid_wrong,'historical_suggestions':suggested,
                'history_responses':n,'history_distinct_sessions':sessions,
                'historical_correct_pct':round(correct_count/n*100,1) if n else '',
                'historical_smoothed_pct':round(smoothed*100,1) if smoothed is not None else '',
                'history_confidence':confidence,'last_hist_play':last,
                'round_target_pct':round(_round_target(r['round_number'])*100),
                'flags':'; '.join(flags),
            })
        game_summary=[]
        for key in dict.fromkeys(r['game_key'] for r in rows):
            group=[r for r in rows if r['game_key']==key]
            game_summary.append({
                'game_key':key,'type':group[0]['game_type'],'slots':len(group),
                'slots_needing_distractors':sum('MISSING_OR_INVALID_FIVE_DISTRACTORS' in r['flags'] for r in group),
                'factual_flags':sum('FACT_CHECK_REQUIRED' in r['flags'] for r in group),
                'with_12plus_history_responses':sum(r['history_responses']>=12 and r['history_distinct_sessions']>=2 for r in group),
                'recent_play_warnings':sum('RECENT_HISTORICAL_PLAY' in r['flags'] for r in group),
            })
        inventory=[{
            'pool':p, 'total_master':pool_count[p],
            'ready_five_distractors':ready_count[p],
            'not_in_any_saved_game_and_ready':unused_ready[p],
            'needed_for_one_day':72,
        } for p in ('sports','regular','after_dark')]
        return rows,game_summary,inventory
    finally:
        connection.close()


def _write_csv(path, records):
    with path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', type=Path, default=HOME/'question_bank.sqlite3')
    p.add_argument('--report-dir', type=Path, default=HOME/'intelligence_review')
    p.add_argument('--as-of', type=date.fromisoformat, default=date(2026,10,8))
    args=p.parse_args()
    details,games,inventory=analyze(args.database,args.as_of)
    args.report_dir.mkdir(exist_ok=True,parents=True)
    _write_csv(args.report_dir/'nine_games_question_review.csv',details)
    _write_csv(args.report_dir/'nine_games_summary.csv',games)
    _write_csv(args.report_dir/'question_inventory.csv',inventory)
    report={
        'as_of':str(args.as_of),'report_status':'READ_ONLY_PRELIMINARY_NOT_APPROVAL',
        'reviewed_saved_games':len(games), 'reviewed_positions':len(details),
        'games':games,'inventory':inventory,
        'historical_summary':'Provisional exact-match record; NOT a validated prediction for new questions.',
        'critical_note':'Master question correctness and historical distractors require human fact check; no changes have been made to active game/database.'
    }
    (args.report_dir/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('READ-ONLY INTELLIGENCE REVIEW — games:',len(games),'positions:',len(details))
    print('CHOICE WARNINGS:',sum('MISSING_OR_INVALID_FIVE_DISTRACTORS' in r['flags'] for r in details))
    print('FACT-CHECK WARNINGS:',sum('FACT_CHECK_REQUIRED' in r['flags'] for r in details))
    print('INVENTORY:',inventory)
    print('REPORT DIR:',args.report_dir)

if __name__=='__main__': main()
