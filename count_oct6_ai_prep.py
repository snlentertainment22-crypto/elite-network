import json
import sqlite3

db = r"game_builder\question_bank.sqlite3"
scheduled_date = "2026-10-06"

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    """
    SELECT
        g.game_key,
        gq.slot_id,
        gq.question_type,
        q.id AS question_id,
        q.wrong_answers_json,
        q.network_status,
        q.roulette_hint,
        q.roulette_hint_status,
        q.roulette_suitable

    FROM games g

    JOIN game_questions gq
      ON gq.game_id = g.id

    JOIN questions q
      ON q.id = gq.question_id

    WHERE g.scheduled_for LIKE ?

    ORDER BY
        g.scheduled_for,
        gq.display_order
    """,
    (scheduled_date + "%",),
).fetchall()

conn.close()


total = len(rows)
final_wagers = 0
already_choices = 0
needs_choices = 0
roulette_total = 0
roulette_hint_ready = 0
roulette_hint_needed = 0


for row in rows:

    if row["question_type"] == "final_wager":
        final_wagers += 1
        continue

    try:
        wrongs = json.loads(
            row["wrong_answers_json"] or "[]"
        )
    except Exception:
        wrongs = []

    reusable_choices = (
        isinstance(wrongs, list)
        and len(wrongs) == 5
        and row["network_status"] != "NEEDS_CHOICES"
    )

    if reusable_choices:
        already_choices += 1
    else:
        needs_choices += 1

    if row["question_type"] == "roulette":

        roulette_total += 1

        hint_ready = (
            bool((row["roulette_hint"] or "").strip())
            and bool(row["roulette_suitable"])
            and row["roulette_hint_status"]
                not in (
                    "NEEDS_HINT",
                    "NEEDS_MANUAL_HINT",
                )
        )

        if hint_ready:
            roulette_hint_ready += 1
        else:
            roulette_hint_needed += 1


print("========================================")
print(" OCT 6 AUTO-BUILD PREP COUNT")
print("========================================")
print("TOTAL SLOTS:", total)
print("FINAL WAGER / NO PREP:", final_wagers)
print("CHOICES ALREADY PREPARED:", already_choices)
print("CHOICES NEED AI PREP:", needs_choices)
print()
print("ROULETTE SLOTS:", roulette_total)
print("ROULETTE HINTS READY:", roulette_hint_ready)
print("ROULETTE HINTS NEED PREP:", roulette_hint_needed)
print("========================================")
