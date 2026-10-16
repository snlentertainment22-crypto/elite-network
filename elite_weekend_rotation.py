"""Install the October 16–18, 2026 Elite Network burn-in lineup.

Run from the folder containing network_schedule.json:
    python install_elite_weekend_rotation.py

Only edits network_schedule.json. Never edits saved games, main.py, or database.
"""

import copy
import json
import os
from pathlib import Path
import sqlite3
import sys

SCHEDULE_PATH = Path('network_schedule.json')
DB_PATH = Path('game_builder/question_bank.sqlite3')
BACKUP_PATH = Path('network_schedule.before-weekend-rotation-2026-10-15.json')

BASE_IDS = ('sports_1200', 'blitz_1800', 'blitz_1900', 'after_dark_2200')
TYPES = {
    'sports_1200': 'SPORTS_BLITZ',
    'blitz_1800': 'REGULAR_BLITZ',
    'blitz_1900': 'REGULAR_BLITZ',
    'after_dark_2200': 'AFTER_DARK_BLITZ',
}
EXPECTED_STARTS = {
    'sports_1200': '12:00',
    'blitz_1800': '18:00',
    'blitz_1900': '19:00',
    'after_dark_2200': '22:00',
}
EXPECTED_KINDS = {
    'sports_1200': 'sports_blitz',
    'blitz_1800': 'elite_blitz',
    'blitz_1900': 'elite_blitz',
    'after_dark_2200': 'after_dark',
}

# All are existing edited/saved October 6 game keys. These names do NOT
# describe their October 16–18 broadcast dates or clock times.
LINEUP = {
    'FRI': (
        ('sports_1200', 'sports-blitz-20261006-2pm'),
        ('blitz_1800', 'regular-blitz-20261006-6pm'),
        ('blitz_1900', 'regular-blitz-20261006-7pm'),
        ('after_dark_2200', 'after-dark-20261006-9pm'),
    ),
    'SAT': (
        ('sports_1200', 'sports-blitz-20261006-3pm'),
        ('blitz_1800', 'regular-blitz-20261006-8pm'),
        ('blitz_1900', 'regular-blitz-20261006-6pm'),
        ('after_dark_2200', 'after-dark-20261006-10pm'),
    ),
    'SUN': (
        ('sports_1200', 'sports-blitz-20261006-4pm'),
        ('blitz_1800', 'regular-blitz-20261006-7pm'),
        ('blitz_1900', 'regular-blitz-20261006-8pm'),
        ('after_dark_2200', 'after-dark-20261006-11pm'),
    ),
}


def fail(message):
    sys.exit('STOP — NO CHANGES MADE: ' + message)


def main():
    if not SCHEDULE_PATH.is_file():
        fail('network_schedule.json not found. Run from the Elite Network project folder.')
    if not DB_PATH.is_file():
        fail('Game database not found at game_builder/question_bank.sqlite3.')
    if BACKUP_PATH.exists():
        fail('Backup path already exists. Refusing to overwrite: ' + str(BACKUP_PATH))

    original = SCHEDULE_PATH.read_bytes()
    try:
        schedule = json.loads(original.decode('utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as e:
        fail('Cannot read valid schedule JSON: ' + str(e))

    if schedule.get('timezone') != 'America/Chicago':
        fail('Unexpected timezone: ' + repr(schedule.get('timezone')))
    channel = schedule.get('channel') or {}
    if channel.get('network_start') != '11:00' or channel.get('network_end') != '01:00':
        fail('Expected channel hours 11:00–01:00. Check schedule before proceeding.')

    events = schedule.get('events')
    if not isinstance(events, list) or len(events) != 4:
        fail('Expected exactly four original daily broadcast events. Found ' + str(len(events) if isinstance(events, list) else type(events)))
    originals = {event.get('id'): event for event in events}
    if len(originals) != 4 or set(originals) != set(BASE_IDS):
        fail('Unexpected event IDs. Refusing to modify a different schedule.')
    for eid in BASE_IDS:
        event = originals[eid]
        if event.get('days') != ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']:
            fail(eid + ' no longer has all seven weekdays.')
        if event.get('start') != EXPECTED_STARTS[eid] or event.get('kind') != EXPECTED_KINDS[eid]:
            fail('Unexpected broadcast time/type in ' + eid)
        if not str(event.get('game_key', '')).startswith(('sports-blitz-20261006-', 'regular-blitz-20261006-', 'after-dark-20261006-')):
            fail('Unexpected existing fallback key in ' + eid)

    keys_to_check = sorted({key for day in LINEUP.values() for _, key in day})
    if len(keys_to_check) != 9:
        fail('Lineup does not contain exactly nine distinct saved games.')
    try:
        conn = sqlite3.connect('file:' + DB_PATH.as_posix() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        with conn:
            db_games = {
                row['game_key']: (row['game_type'], row['id'])
                for row in conn.execute(
                    'SELECT game_key, game_type, id FROM games WHERE game_key IN ('
                    + ','.join('?' for _ in keys_to_check) + ')', keys_to_check
                )
            }
            if len(db_games) != 9:
                fail('Some October 6 games are missing: ' + ', '.join(sorted(set(keys_to_check) - set(db_games))))
            for day, lineup in LINEUP.items():
                for eid, key in lineup:
                    if db_games[key][0] != TYPES[eid]:
                        fail('Game type mismatch for ' + day + ' ' + eid + ': ' + key)
                    count = conn.execute('SELECT COUNT(*) FROM game_questions WHERE game_id = ?', (db_games[key][1],)).fetchone()[0]
                    if count != 24:
                        fail('Expected 24 saved slots in ' + key + '; found ' + str(count))
            assigned = conn.execute(
                "SELECT game_key, scheduled_for FROM games "
                "WHERE substr(scheduled_for, 1, 10) IN ('2026-10-16', '2026-10-17', '2026-10-18')"
            ).fetchall()
            if assigned:
                fail('Other date-specific games already assigned Oct 16–18. These override fallback events: '
                     + ', '.join(r['game_key'] for r in assigned))
    except sqlite3.Error as e:
        fail('Could not validate game database: ' + str(e))
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass

    # Original default fallback events stay available MON–THU. They cannot
    # match Friday/Saturday/Sunday, so first-match event precedence is safe.
    for eid in BASE_IDS:
        originals[eid]['days'] = ['MON', 'TUE', 'WED', 'THU']

    # Clone the original four events per day to preserve titles and end times.
    for day, lineup in LINEUP.items():
        for eid, game_key in lineup:
            event = copy.deepcopy(originals[eid])
            event['id'] = eid + '_' + day.lower() + '_20261016burnin'
            event['days'] = [day]
            event['game_key'] = game_key
            events.append(event)

    # File-level rollback copy must be written before new config is installed.
    try:
        with BACKUP_PATH.open('xb') as backup:
            backup.write(original)
        temp_path = SCHEDULE_PATH.with_name(SCHEDULE_PATH.name + '.tmp-weekend-rotation')
        if temp_path.exists():
            fail('Temporary path exists: ' + str(temp_path))
        with temp_path.open('x', encoding='utf-8', newline='\n') as temp:
            json.dump(schedule, temp, ensure_ascii=False, indent=2)
            temp.write('\n')
        os.replace(temp_path, SCHEDULE_PATH)
    except OSError as e:
        fail('Could not save schedule: ' + str(e))

    print('SUCCESS — Only network_schedule.json was updated.')
    print('Rollback copy:', BACKUP_PATH)
    print('Channel hours: 11 AM–1 AM Central; standby 1 AM–11 AM.')
    print('Day  | Noon Sports                      | 6 PM Regular                      | 7 PM Regular                      | 10 PM After Dark')
    for day, lineup in LINEUP.items():
        print(day, '|', ' | '.join(key for _, key in lineup))
    print('NOTE: These are weekly day-of-week rules; restore ordinary schedule after weekend test.')
    print('NOTE: Server restart/reload may be required for new schedule to take effect.')


if __name__ == '__main__':
    main()
