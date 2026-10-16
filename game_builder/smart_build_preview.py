"""ELITE Network — SMART BUILD PREVIEW V3 (READ ONLY).

Offline *review queue* from Network questions + V1 historical evidence. No API calls,
question generation, approval, writes to source database, or changes to Auto Build.

Usage from ELITE NETWORK GAME BUILDER 1A root:
    py -m game_builder.smart_build_preview --seed 20261009

This report is NOT a play-ready batch. Archived distractors are UNVERIFIED,
all current Network questions have NEEDS_REVIEW / NEEDS_CHOICES status, and
historic accuracy is not a guarantee for new players or new distractor sets.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from .game_intelligence import BAD_QUESTION_FLAGS, DATA_DIR, HOME, _choice_status, _round_target
from .question_pools import get_question_pools, normalize_category

POOL_ORDER = (('SPORTS_BLITZ', 'sports'), ('REGULAR_BLITZ', 'regular'), ('AFTER_DARK_BLITZ', 'after_dark'))
PER_GAME = 24
GAMES_EACH = 3
RECENT_DAYS = 183


def _read_csv(name: str) -> dict:
    path = DATA_DIR / name
    with path.open('r', newline='', encoding='utf-8-sig') as f:
        return {r['eq_id']: r for r in csv.DictReader(f)}


def _normalize(value) -> str:
    return ' '.join(str(value or '').casefold().strip().split())


def _suggested_wrong_answers(raw: str, answer: str) -> list[str]:
    try:
        options = json.loads(raw or '[]')
    except (TypeError, ValueError):
        return []
    if not isinstance(options, list):
        return []
    seen = {_normalize(answer)}
    result = []
    for option in options:
        norm = _normalize(option)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        result.append(str(option).strip())
    if len(result) < 5:
        return []
    first_five = result[:5]
    return first_five if _choice_status(json.dumps(first_five), answer) else []


def _recent_play(performance: dict, cutoff: date) -> bool:
    last = performance.get('last_seen') or ''
    try:
        return bool(last) and date.fromisoformat(last) >= cutoff
    except ValueError:
        return True  # malformed evidence gets reviewed, not silently allowed


def scan_candidates(db_path: Path, as_of: date) -> tuple[dict, dict, dict]:
    """Build candidate inventory using a strictly read-only SQLite connection."""
    history = _read_csv('historical_performance_v1.csv')
    distractors = _read_csv('historical_distractor_candidates_v1.csv')
    conn = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    cutoff = as_of - timedelta(days=RECENT_DAYS)
    counters = {p: Counter() for _, p in POOL_ORDER}
    candidates = {p: [] for _, p in POOL_ORDER}
    excluded = {'used_saved_game_question_ids': 0}
    try:
        saved_ids = {int(r[0]) for r in conn.execute('SELECT DISTINCT question_id FROM game_questions')}
        excluded['used_saved_game_question_ids'] = len(saved_ids)
        for row in conn.execute('''SELECT id,source_key,category,question,correct_answer,
                wrong_answers_json,network_status,difficulty_label,roulette_hint
                FROM questions ORDER BY id'''):
            record = dict(row)
            eq = record['source_key'] or ''
            eligible = get_question_pools(record['category'])
            for _, pool in POOL_ORDER:
                if not eligible.get(pool, False):
                    continue
                counters[pool]['total_in_database'] += 1
                if record['id'] in saved_ids:
                    counters[pool]['already_in_saved_games'] += 1
                    continue
                counters[pool]['unused_in_saved_games'] += 1
                if not eq or not str(record['question'] or '').strip() or not str(record['correct_answer'] or '').strip():
                    counters[pool]['blank_or_missing'] += 1
                    continue
                if eq in BAD_QUESTION_FLAGS:
                    counters[pool]['known_fact_check_hold'] += 1
                    continue
                if pool == 'regular' and _normalize(record['category']) == 'current events':
                    counters[pool]['current_events_review_required'] += 1
                    continue
                perf = history.get(eq, {})
                if _recent_play(perf, cutoff):
                    counters[pool]['recent_historical_play_hold'] += 1
                    continue
                saved = record['wrong_answers_json'] or '[]'
                if _choice_status(saved, record['correct_answer']):
                    wrong = json.loads(saved)
                    origin = 'SAVED_BUT_NOT_APPROVED'
                else:
                    wrong = _suggested_wrong_answers(
                        distractors.get(eq, {}).get('suggested_wrongs_json', ''),
                        record['correct_answer'],
                    )
                    origin = 'HISTORICAL_UNVERIFIED'
                if not wrong:
                    counters[pool]['needs_five_wrong_answers'] += 1
                    continue
                n = int(perf.get('responses') or 0)
                sessions = int(perf.get('distinct_sessions') or 0)
                correct = int(perf.get('correct') or 0)
                has_evidence = n >= 12 and sessions >= 2
                score = (correct + 6.5) / (n + 10) if has_evidence else None
                record.update({
                    'proposed_wrong_answers': wrong,
                    'wrong_answer_source': origin,
                    'history_responses': n,
                    'history_sessions': sessions,
                    'historical_smoothed_accuracy': score,
                    'history_confidence': 'LIMITED_OR_BETTER' if has_evidence else 'UNMEASURED',
                    'content_approval': 'NEEDS_HUMAN_FACT_CHECK_AND_DISTRACTOR_REVIEW',
                })
                candidates[pool].append(record)
                counters[pool]['unapproved_candidate_with_five_options'] += 1
                counters[pool][origin] += 1
                if has_evidence:
                    counters[pool]['candidates_with_history_evidence'] += 1
    finally:
        conn.close()
    return candidates, counters, excluded


def _pick_game(pool_candidates: list[dict], selected_ids: set[int], selected_text: set[str], seed: int):
    """Round-aware selection, provisional quotas (max 2/category), no guesses of unknown difficulty."""
    rng = random.Random(seed)
    available = [c for c in pool_candidates if c['id'] not in selected_ids and _normalize(c['question']) not in selected_text]
    if len(available) < PER_GAME:
        return [], f'Only {len(available)} unused candidates for 24 slots'
    rng.shuffle(available)
    chosen = []
    category_counts = Counter()
    local_text = set()
    for rn in range(1, 5):
        target = _round_target(rn)
        for qn in range(1, 7):
            options = [q for q in available if q['id'] not in {x[2]['id'] for x in chosen}
                       and _normalize(q['question']) not in local_text]
            if not options:
                return [], f'Not enough distinct question texts for R{rn}Q{qn}'
            # Include category spread; historical match to target is supporting evidence only.
            def priority(q):
                accuracy = q['historical_smoothed_accuracy']
                cat = _normalize(q['category'])
                return (
                    1 if category_counts[cat] >= 2 else 0,
                    category_counts[cat],
                    abs(accuracy-target) if accuracy is not None else 0.5,
                    0 if accuracy is not None else 1,
                )
            q = min(options, key=priority)
            chosen.append((rn, qn, q))
            category_counts[_normalize(q['category'])] += 1
            local_text.add(_normalize(q['question']))
    return chosen, None



# Sports games are built as a THREE-GAME BLOCK, not one after another.
# The old one-game-at-a-time preview gave all non-generic sports categories
# to Sports Game 1 and left Games 2-3 with only the generic Sports category.
# The existing question_pools.py already recognizes NFL/NHL/NBA/MLB/etc.
SPORT_FAMILY_KEYWORDS = (
    ('FOOTBALL', ('nfl', 'football', 'packers', 'super bowl')),
    ('BASEBALL', ('mlb', 'baseball', 'brewers')),
    ('BASKETBALL', ('nba', 'basketball', 'bucks')),
    ('HOCKEY', ('nhl', 'hockey')),
    ('GOLF', ('golf',)),
    ('RACING', ('nascar', 'racing', 'indycar', 'motorsport', 'motor sport', 'moto racing')),
    ('TENNIS', ('tennis',)),
    ('SOCCER', ('soccer', 'world cup')),
    ('OLYMPICS', ('olympics', 'olympic')),
    ('WRESTLING', ('wrestling', 'wwe')),
    ('COMBAT SPORTS', ('boxing', 'ufc', 'mma')),
)


def sports_category_family(category: str) -> str:
    """Conservative family based on CATEGORY only, never guess from a player name.

    Sports/Geography etc. count as sports subcategories but not as NFL/MLB.
    A bare Sports/Sport label stays GENERAL SPORTS even if its question may
    actually be about baseball or another league.
    """
    normalized = normalize_category(category)
    if normalized in {'sport', 'sports'}:
        return 'GENERAL SPORTS'
    segments = normalized.split()
    for family, terms in SPORT_FAMILY_KEYWORDS:
        for term in terms:
            tokens = term.split()
            if any(segments[i:i+len(tokens)] == tokens for i in range(len(segments)-len(tokens)+1)):
                return family
    return 'OTHER SPORTS SUBCATEGORY'



# Optional low-risk hints for older Master rows labeled only "Sports".
# These are TOPIC HINTS for distribution, not factual validation or proof.
# Keep the hints conservative: named athletes by themselves are not guessed.
SPORT_QUESTION_HINTS = (
    ('FOOTBALL', ('nfl', 'football', 'quarterback', 'quarterbacks', 'super bowl',
                  'packers', 'heisman', 'touchdown')),
    ('BASEBALL', ('mlb', 'baseball', 'major league baseball', 'world series',
                  'home runs', 'pitcher', 'milwaukee brewers')),
    ('BASKETBALL', ('nba', 'wnba', 'basketball', 'final four', 'march madness',
                    'milwaukee bucks', 'chicago bulls')),
    ('HOCKEY', ('nhl', 'hockey', 'stanley cup')),
    ('GOLF', ('golf', 'pga', 'lpga')),
    ('RACING', ('nascar', 'formula 1', 'formula one', 'indycar', 'indy 500',
                'pit crew', 'grand prix')),
    ('TENNIS', ('tennis', 'wimbledon', 'atp tour')),
    ('SOCCER', ('soccer', 'fifa', 'nwsl', 'premier league')),
    ('OLYMPICS', ('olympic', 'olympics', 'paralympic', 'paralympics')),
    ('WRESTLING', ('wrestling', 'wwe')),
    ('COMBAT SPORTS', ('boxing', 'mma', 'ufc', 'judo')),
)


def sport_topic_for_question(candidate: dict) -> tuple[str, str]:
    """Return (family, provenance) for spread; NOT an approved sports tag."""
    category_family = sports_category_family(candidate.get('category', ''))
    if category_family != 'GENERAL SPORTS':
        return category_family, 'CATEGORY'
    text = normalize_category(candidate.get('question', ''))
    tokens = text.split()
    matches = []
    for family, hints in SPORT_QUESTION_HINTS:
        if any(any(tokens[i:i+len(hint.split())] == hint.split()
                   for i in range(len(tokens)-len(hint.split())+1))
               for hint in hints):
            matches.append(family)
    if len(matches) == 1:
        return matches[0], 'QUESTION_KEYWORD_PROVISIONAL'
    if len(matches) > 1:
        return 'MIXED SPORTS TOPICS', 'MULTIPLE_QUESTION_KEYWORDS'
    return 'GENERAL SPORTS', 'NO_CATEGORY_SUBTYPE'


def _pick_sports_block(
    pool_candidates: list[dict], selected_ids: set[int], selected_text: set[str], seed: int
) -> tuple[list[list[tuple[int,int,dict]]], str | None]:
    """Distribute eligible sports *subcategories* across three 24-slot drafts.

    Does not generate, approve, or persist anything. Difficulty evidence is
    secondary. If inventory is insufficient, block the whole block rather
    than silently repeat a question or mislabel a generic Sports question.
    """
    rng = random.Random(seed)
    available = [c for c in pool_candidates
                 if c['id'] not in selected_ids and _normalize(c['question']) not in selected_text]
    by_text = {}
    for c in available:
        by_text.setdefault(_normalize(c['question']), c)
    available = list(by_text.values())
    required = GAMES_EACH * PER_GAME
    if len(available) < required:
        return [], f'Only {len(available)} distinct unused sports candidates for {required} positions'

    assigned = {}  # (game_index, round, question_number): candidate record
    family_counts = [Counter() for _ in range(GAMES_EACH)]
    special_game_counts = Counter()
    special_game_round_counts = Counter()
    evidence_game_round_counts = Counter()
    total_game_round_counts = Counter()
    slots = [(g, r, q) for g in range(GAMES_EACH)
             for r in range(1, 5) for q in range(1, 7)]

    specific = [c for c in available if sport_topic_for_question(c)[0] != 'GENERAL SPORTS']
    generic = [c for c in available if sport_topic_for_question(c)[0] == 'GENERAL SPORTS']
    rng.shuffle(specific)
    rng.shuffle(generic)
    # Cycle across sport families. Do NOT let one large family (e.g. NFL)
    # monopolize the first 72 positions as the candidate bank grows.
    groups = {}
    for c in specific:
        groups.setdefault(sport_topic_for_question(c)[0], []).append(c)
    for candidates in groups.values():
        rng.shuffle(candidates)
    families = list(groups)
    rng.shuffle(families)
    diverse_specific = []
    while any(groups.values()):
        for family in families:
            if groups[family]:
                diverse_specific.append(groups[family].pop())
    for c in diverse_specific:
        free = [slot for slot in slots if slot not in assigned]
        if not free:
            break  # two or more spare questions can remain unused safely
        family = sport_topic_for_question(c)[0]
        acc = c['historical_smoothed_accuracy']
        rng.shuffle(free)
        def special_rank(slot):
            g, r, _ = slot
            return (special_game_counts[g], family_counts[g][family],
                    special_game_round_counts[g,r],
                    abs(acc - _round_target(r)) if acc is not None else 0.5,
                    total_game_round_counts[g,r])
        slot = min(free, key=special_rank)
        assigned[slot] = c
        g, r, _ = slot
        family_counts[g][family] += 1
        special_game_counts[g] += 1
        special_game_round_counts[g,r] += 1
        total_game_round_counts[g,r] += 1
        if acc is not None:
            evidence_game_round_counts[g,r] += 1

    # Known difficulty evidence is placed closest to the corresponding round.
    # Unknown difficulty is NOT treated as a measured success probability.
    generic.sort(key=lambda c: c['historical_smoothed_accuracy'] is None)
    for c in generic:
        free = [slot for slot in slots if slot not in assigned]
        if not free:
            break
        rng.shuffle(free)
        acc = c['historical_smoothed_accuracy']
        if acc is not None:
            slot = min(free, key=lambda slot: (
                abs(acc - _round_target(slot[1])),
                evidence_game_round_counts[slot[0],slot[1]],
                total_game_round_counts[slot[0],slot[1]]))
        else:
            slot = min(free, key=lambda slot: (
                total_game_round_counts[slot[0],slot[1]],
                sum(1 for g,r,_ in assigned if g == slot[0]),
                evidence_game_round_counts[slot[0],slot[1]]))
        assigned[slot] = c
        g, r, _ = slot
        total_game_round_counts[g,r] += 1
        if acc is not None:
            evidence_game_round_counts[g,r] += 1

    if len(assigned) != required:
        return [], f'Only {len(assigned)} unique sports question positions could be filled'
    games = []
    for g in range(GAMES_EACH):
        games.append([(r, q, assigned[g,r,q]) for r in range(1,5) for q in range(1,7)])
    return games, None



def _sports_round_diagnostics(block: list[list[tuple[int,int,dict]]]) -> list[dict]:
    """Historical coverage diagnostics — NEVER present missing history as success."""
    result = []
    for gi, game in enumerate(block, 1):
        for rnd in range(1, 5):
            part = [q for r, _, q in game if r == rnd]
            observed = [q['historical_smoothed_accuracy'] for q in part
                        if q['historical_smoothed_accuracy'] is not None]
            coverage = len(observed)
            target = _round_target(rnd)
            flags = []
            if coverage < 2:
                flags.append('SPARSE_HISTORY')
            if rnd == 1 and any(a < 0.50 for a in observed):
                flags.append('KNOWN_HARD_IN_OPENING_ROUND')
            if coverage and sum(observed)/coverage < target - 0.14:
                flags.append('MEASURED_BELOW_EDITORIAL_TARGET')
            result.append({
                'game': f'SPORTS-{gi}', 'round': f'R{rnd}',
                'target_editorial_pct': round(target*100),
                'observed_questions': coverage,
                'measured_mean_pct': round(sum(observed)/coverage*100, 1) if coverage else None,
                'flags': flags,
            })
    return result


def _rebalance_sports_difficulty(
    block: list[list[tuple[int,int,dict]]], seed: int,
) -> list[list[tuple[int,int,dict]]]:
    """Conservatively position measured questions; preserve all EQ IDs and 24 slots/game.

    The 74-question source pool has far too little evidence to guarantee
    target accuracy. This only avoids obvious placements of measured-hard
    questions in R1 and distributes scarce evidence for useful review.
    Unmeasured questions stay labeled unknown, never assigned an invented score.
    """
    if not block:
        return block
    flat = [(g, r, n, q) for g, game in enumerate(block)
            for r, n, q in game]
    slots = [(g, r, n) for g, r, n, _ in flat]
    values = [q for _, _, _, q in flat]
    targets = [_round_target(r) for _,r,_ in slots]
    families = [sport_topic_for_question(q)[0] for q in values]
    accuracies = [q['historical_smoothed_accuracy'] for q in values]
    rng = random.Random(seed + 1307)

    def cost(records):
        family_per_game = [Counter() for _ in range(GAMES_EACH)]
        family_per_round = Counter()
        evidence_per_round = Counter()
        evidence_per_game = Counter()
        result = 0.0
        for i, index in enumerate(records):
            g, r, _ = slots[i]
            family = families[index]
            family_per_game[g][family] += 1
            family_per_round[g,r,family] += 1
            a = accuracies[index]
            if a is None:
                continue
            evidence_per_round[g,r] += 1
            evidence_per_game[g] += 1
            result += 35 * (a-targets[i])**2
            if r == 1 and a < 0.50:
                result += 12 + 30*(0.50-a)
        # Scarce known data should cover every round rather than cluster.
        for g in range(GAMES_EACH):
            result += 0.75 * (evidence_per_game[g]-7)**2
            for r in range(1,5):
                n = evidence_per_round[g,r]
                if n == 0:
                    result += 4.0
                if n > 3:
                    result += (n-3)**2
            for n in family_per_game[g].values():
                if n > 5:
                    result += 2.2*(n-5)**2
        for n in family_per_round.values():
            if n > 2:
                result += 1.8*(n-2)**2
        return result

    # Reproducible local optimization, never changes the candidate inventory.
    current = list(range(len(values)))
    current_score = cost(current)
    best = current[:]
    best_score = current_score
    iterations = 5500
    for i in range(iterations):
        a, b = rng.sample(range(len(current)), 2)
        current[a], current[b] = current[b], current[a]
        after = cost(current)
        temperature = 1.5 * (1-i/iterations) + 0.015
        if after <= current_score or rng.random() < math.exp(min(0.0, (current_score-after)/temperature)):
            current_score = after
            if after < best_score:
                best_score, best = after, current[:]
        else:
            current[a], current[b] = current[b], current[a]

    result = [[] for _ in range(GAMES_EACH)]
    for (g, r, n), index in zip(slots, best):
        result[g].append((r, n, values[index]))
    for game in result:
        game.sort(key=lambda x:(x[0],x[1]))
    return result

def create_preview(db_path: Path, as_of: date, seed: int) -> tuple[list[dict], dict]:
    candidates, counters, excluded = scan_candidates(db_path, as_of)
    rows = []
    used_ids = set()
    used_text = set()
    games = []
    # Plan Sports as one block to stop Game 1 from taking all NFL/NBA/MLB/etc.
    sports_block, sports_failure = _pick_sports_block(candidates['sports'], used_ids, used_text, seed)
    if not sports_failure:
        sports_block = _rebalance_sports_difficulty(sports_block, seed)
    for game_type, pool in POOL_ORDER:
        for game_num in range(1, GAMES_EACH + 1):
            if pool == 'sports':
                selected, failure = (sports_block[game_num - 1], None) if not sports_failure else ([], sports_failure)
            else:
                selected, failure = _pick_game(candidates[pool], used_ids, used_text, seed + game_num + len(games)*100)
            key = f'{pool.upper()}-{game_num}'
            if failure:
                games.append({'game': key, 'game_type': game_type, 'status': 'BLOCKED', 'reason': failure, 'positions': 0})
                continue
            for rn, qn, q in selected:
                used_ids.add(q['id'])
                used_text.add(_normalize(q['question']))
                evidence = q['historical_smoothed_accuracy']
                rows.append({
                    'preview_game': key,
                    'game_type': game_type,
                    'slot': f'R{rn}Q{qn}',
                    'eq_id': q['source_key'],
                    'category': q['category'],
                    'sports_family': sport_topic_for_question(q)[0] if pool == 'sports' else '',
                    'sports_topic_source': sport_topic_for_question(q)[1] if pool == 'sports' else '',
                    'question': q['question'],
                    'correct_answer': q['correct_answer'],
                    'proposed_wrong_answers_json': json.dumps(q['proposed_wrong_answers'], ensure_ascii=False),
                    'wrong_answer_source': q['wrong_answer_source'],
                    'approval_status': q['content_approval'],
                    'round_target_editorial_pct': round(_round_target(rn)*100),
                    'history_responses': q['history_responses'],
                    'history_sessions': q['history_sessions'],
                    'historical_accuracy_pct': round(evidence*100,1) if evidence is not None else '',
                    'history_confidence': q['history_confidence'],
                    'network_status_original': q['network_status'],
                })
            detail = {'game':key,'game_type':game_type,'status':'REVIEW_ONLY_NOT_APPROVED','reason':'Every position requires manual review; NOT play-ready','positions':PER_GAME}
            if pool == 'sports':
                detail['sport_families'] = dict(Counter(sport_topic_for_question(q)[0] for _,_,q in selected))
                detail['specific_or_provisionally_inferred_topics'] = sum(sport_topic_for_question(q)[0] != 'GENERAL SPORTS' for _,_,q in selected)
                detail['category_specific_topics'] = sum(sports_category_family(q['category']) != 'GENERAL SPORTS' for _,_,q in selected)
            games.append(detail)
    summary = {
        'kind': 'READ_ONLY_UNAPPROVED_SMART_SELECTION_PREVIEW',
        'as_of': as_of.isoformat(),
        'seed': seed,
        'database_path': str(db_path),
        'settings': {'historical_play_cooldown_days': RECENT_DAYS, 'editorial_round_targets': [79,65,56,49], 'provisional_max_category_per_game':2, 'sports_subcategories_balanced_across_three_games': True, 'generic_sports_keyword_topic_hint': 'PROVISIONAL_REVIEW_ONLY'},
        'sports_round_diagnostics': _sports_round_diagnostics(sports_block) if not sports_failure else [],
        'publication_allowed': False,
        'selected_positions_for_review': len(rows),
        'blocked_games': sum(g['status']=='BLOCKED' for g in games),
        'games': games,
        'inventory': {pool:dict(counters[pool]) for _,pool in POOL_ORDER},
        'excluded': excluded,
        'warnings': [
            'NOT A SAVED OR LIVE GAME. Neither questions nor wrong answers have been approved by this script.',
            'Historical wrong-answer options are unverified candidates and must be fact-checked individually.',
            'Historical accuracy was measured under possibly different answer choices; NEVER a guaranteed forecast.',
            'Unmeasured question difficulty cannot be determined from history. Round targets are editorial only.',
            'Old saved-game use is excluded even when those games were only drafts; review that policy before shipping.',
            'This preview creates no new After Dark questions. Insufficient inventory must remain BLOCKED.',
            'Sports topic families from question text are KEYWORD INFERENCES ONLY and require editorial inspection.',
            'Only 21 of 74 Sports candidates have qualifying historical evidence. Three measured questions score at least 75 percent; R1 targets CANNOT be assured for three games.',
            'Round averages from small observed subsets are NOT overall game difficulty forecasts.',
        ],
    }
    return rows, summary


def export_preview(rows: list[dict], summary: dict, report_dir: Path) -> None:
    report_dir.mkdir(parents=True,exist_ok=True)
    csv_path = report_dir/'smart_build_preview_questions.csv'
    columns = ['preview_game','game_type','slot','eq_id','category','sports_family','sports_topic_source','question','correct_answer',
               'proposed_wrong_answers_json','wrong_answer_source','approval_status','round_target_editorial_pct',
               'history_responses','history_sessions','historical_accuracy_pct','history_confidence','network_status_original']
    with csv_path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    (report_dir/'smart_build_preview_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',type=Path,default=HOME/'question_bank.sqlite3')
    p.add_argument('--report-dir',type=Path,default=HOME.parent/'intelligence_review')
    p.add_argument('--seed',type=int,default=20261009)
    p.add_argument('--as-of',type=date.fromisoformat,default=date(2026,10,8))
    args=p.parse_args()
    rows,summary=create_preview(args.database,args.as_of,args.seed)
    export_preview(rows,summary,args.report_dir)
    print('ELITE SMART BUILD — READ-ONLY, UNAPPROVED PREVIEW')
    for g in summary['games']:
        print(f"{g['game']}: {g['status']} ({g['positions']}/24)" + (f" — {g['reason']}" if g['status']=='BLOCKED' else ''))
    print('Positions selected for review:',len(rows))
    for item in summary.get('sports_round_diagnostics', []):
        if item['flags']:
            print('DIFFICULTY REVIEW:', item['game'], item['round'],
                  f"history={item['observed_questions']}/6, mean={item['measured_mean_pct']}, flags={','.join(item['flags'])}")
    for pool,stat in summary['inventory'].items():
        print(pool.upper(), 'unused eligible option-set candidates:', stat.get('unapproved_candidate_with_five_options',0))
    print('WARNING: No questions approved, games saved, or API calls made.')
    print('Reports:',args.report_dir)


if __name__=='__main__': main()
