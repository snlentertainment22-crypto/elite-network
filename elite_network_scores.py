"""Append-only Elite Network completed Blitz scoreboard journal.

Store ELITE_SCORE_ARCHIVE_PATH on a persistent Render disk before bar beta.
Neither client device tokens nor IP addresses are archived.
"""
import json
import os
from pathlib import Path


def scoreboard_path():
    override = os.environ.get('ELITE_SCORE_ARCHIVE_PATH', '').strip()
    if override:
        return Path(override).expanduser()
    if Path('/var/data').is_dir():
        return Path('/var/data/elite_score_history.jsonl')
    return Path(__file__).resolve().parent / 'data' / 'elite_score_history.jsonl'


def archive_completed_game(record):
    """Append and fsync one completed game. Raise on failure (don't clear teams)."""
    path = scoreboard_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n'
    with path.open('a', encoding='utf-8') as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    return str(path)
