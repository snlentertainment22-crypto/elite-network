from __future__ import annotations

# Game-level preflight and LOCAL-ONLY publish path.

# No AI calls, no automatic approvals, no destructive database migrations.
# Published content is snapshotted per game to survive later master imports.


import hashlib
import json
import re
from datetime import datetime, timezone

from .question_bank import connect, initialize_database
from .admin_review import get_current_content, validate_for_game
from .runtime_game_loader import _build_choices


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_content(content):
    # Game review covers the question's effective content and its slot type.
    return {
        'category': str(content.get('category') or '').strip(),
        'question': str(content.get('question') or '').strip(),
        'correct_answer': str(content.get('correct_answer') or '').strip(),
        'wrong_answers': [str(v).strip() for v in content.get('wrong_answers', [])],
        'roulette_hint': str(content.get('roulette_hint') or '').strip(),
        'question_type': str(content.get('question_type') or '').strip(),
    }


def content_fingerprint(content):
    data = json.dumps(canonical_content(content), ensure_ascii=False,
                      sort_keys=True, separators=(',', ':')).encode('utf8')
    return hashlib.sha256(data).hexdigest()


def _get_game(conn, game_key):
    row = conn.execute('SELECT * FROM games WHERE game_key=?', (game_key,)).fetchone()
    if row is None:
        raise ValueError('Game not found: ' + game_key)
    return dict(row)


def _inspect(conn, game_key):
    game = _get_game(conn, game_key)
    issues = []
    when = str(game.get('scheduled_for') or '').strip()
    if not when:
        issues.append('Game has no scheduled date/time.')
    else:
        try:
            parsed = datetime.fromisoformat(when)
            expected_hour = {'SPORTS_BLITZ': {12}, 'REGULAR_BLITZ': {18, 19},
                             'AFTER_DARK_BLITZ': {22}}.get(game['game_type'])
            if expected_hour is None:
                issues.append('Unexpected game type: ' + str(game['game_type']))
            elif parsed.hour not in expected_hour or parsed.minute != 0 or parsed.second != 0:
                issues.append('Scheduled time does not match this game type: ' + when)
        except ValueError:
            issues.append('Invalid scheduled date/time: ' + when)

    rows = conn.execute('''
        SELECT gq.*, q.category, q.question, q.correct_answer,
               q.wrong_answers_json, q.roulette_hint, q.source_key,
               q.audio_mp3, q.question_image, q.reveal_image, q.video_clip,
               q.voiceover_audio, q.roulette_suitable
        FROM game_questions gq JOIN questions q ON q.id=gq.question_id
        WHERE gq.game_id=? ORDER BY gq.display_order
    ''', (game['id'],)).fetchall()
    if len(rows) != 24:
        issues.append(f'Expected 24 questions; found {len(rows)}.')
    positions, question_ids, source_keys, normalized_questions = set(), set(), set(), set()
    prepared = []
    approved_count = 0
    for row in rows:
        label = str(row['slot_id'])
        qissues = []
        r, n = int(row['round_number']), int(row['question_number'])
        if not (1 <= r <= 4 and 1 <= n <= 6):
            qissues.append('Invalid round/question position.')
        if (r,n) in positions:
            qissues.append('Duplicate round/question position.')
        positions.add((r,n))
        if int(row['question_id']) in question_ids:
            qissues.append('Question reused within the same game.')
        question_ids.add(int(row['question_id']))
        source_key = str(row['source_key'] or '').strip()
        if not source_key:
            qissues.append('Missing permanent source question ID.')
        elif source_key in source_keys:
            qissues.append('Duplicate permanent source question ID.')
        source_keys.add(source_key)
        qtype = str(row['question_type'] or '').lower()
        required_type = 'final_wager' if (r,n)==(4,6) else ('roulette' if n==6 else 'normal')
        if qtype != required_type:
            qissues.append(f'Expected {required_type} for round {r} question {n}; found {qtype}.')
        if row['timer_seconds'] is not None and int(row['timer_seconds']) <= 0:
            qissues.append('Question timer must be positive.')
        if qtype == 'roulette' and row['wager_seconds'] is not None and int(row['wager_seconds']) <= 0:
            qissues.append('Roulette wager timer must be positive.')
        if qtype == 'roulette' and not int(row['roulette_suitable']):
            qissues.append('Question is marked unsuitable for Roulette.')
        if any(str(row[field] or '').strip() for field in
               ('audio_mp3','question_image','reveal_image','video_clip','voiceover_audio')):
            qissues.append('Master question contains media; Network Blitz is text-only.')
        content, snapshot = get_current_content(row)
        qissues.extend(validate_for_game(content, r))
        question_normalized = re.sub(r'\W+', ' ', content['question'].casefold()).strip()
        if question_normalized and question_normalized in normalized_questions:
            qissues.append('Duplicate question wording in this game.')
        normalized_questions.add(question_normalized)
        try:
            if qtype != 'final_wager' and content.get('correct_answer'):
                _build_choices(game_key, label, content['correct_answer'],
                               content['wrong_answers'], 6 if r==4 else 4)
        except (RuntimeError, ValueError) as exc:
            qissues.append(str(exc))
        review = snapshot.get('game_review') or {}
        if not isinstance(review, dict):
            review = {}
        if review.get('status') != 'APPROVED':
            qissues.append('Not individually approved.')
        elif review.get('content_sha256') != content_fingerprint(content):
            qissues.append('Approval predates content fingerprint or question changed; reapprove.')
        else:
            approved_count += 1
        prepared.append({'slot_id': label, 'round': r, 'number': n,
                         'question_id': int(row['question_id']), 'content': content,
                         'snapshot': snapshot, 'issues': list(dict.fromkeys(qissues)),
                         'row_id': int(row['id'])})
        issues += [f'{label}: {msg}' for msg in dict.fromkeys(qissues)]

    if positions != {(r,n) for r in range(1,5) for n in range(1,7)}:
        issues.append('Game does not contain exactly R1–R4, Q1–Q6.')
    if when:
        conflicts = conn.execute('''SELECT game_key FROM games
                                  WHERE scheduled_for=? AND game_type=?
                                    AND status='PUBLISHED' AND id<>?''',
                                 (when,game['game_type'],game['id'])).fetchall()
        if conflicts:
            issues.append('A different game is already PUBLISHED for this slot: ' +
                          ', '.join(row[0] for row in conflicts))
    return {
        'game_key': game_key, 'game_type': game['game_type'],
        'status': game['status'], 'scheduled_for': when,
        'approved': approved_count, 'total': len(rows),
        'can_publish': not issues and game['status']=='DRAFT',
        'issues': issues,
    }, prepared, game


def preflight_game(game_key):
    if not isinstance(game_key, str) or not game_key.strip():
        raise ValueError('Missing game key.')
    initialize_database()
    conn = connect()
    try:
        report, _prepared, _game = _inspect(conn, game_key.strip())
        return report
    finally:
        conn.close()


def publish_game(game_key, confirm):
    if not isinstance(game_key, str) or not game_key.strip():
        raise ValueError('Missing game key.')
    game_key = game_key.strip()
    if confirm != 'PUBLISH ' + game_key:
        raise ValueError('Explicit confirmation mismatch. Nothing published.')
    initialize_database()
    conn = connect()
    try:
        # Writer lock protects the entire preflight and status change.
        conn.execute('BEGIN IMMEDIATE')
        report, prepared, game = _inspect(conn, game_key)
        if not report['can_publish']:
            return dict(report, published=False)
        now = utc_now()
        # Freeze every reviewed question so future master CSV imports cannot
        # silently change already approved live game content.
        for item in prepared:
            snapshot = dict(item['snapshot'])
            snapshot['game_edit'] = {
                key: item['content'][key] for key in
                ('category','question','correct_answer','wrong_answers','roulette_hint')
            }
            snapshot['published_content_sha256'] = content_fingerprint(item['content'])
            conn.execute('''UPDATE game_questions SET question_snapshot_json=? WHERE id=?''',
                         (json.dumps(snapshot, ensure_ascii=False), item['row_id']))
        conn.execute('''UPDATE games SET status='PUBLISHED', updated_at=?
                        WHERE id=? AND status='DRAFT' ''', (now, game['id']))
        if conn.total_changes < len(prepared)+1:
            raise RuntimeError('Publish status changed unexpectedly; transaction canceled.')
        conn.commit()
        return dict(report, published=True, status='PUBLISHED', published_at=now)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
