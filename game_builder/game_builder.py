from __future__ import annotations

import json
from collections import Counter

from question_bank import (
    connect,
    initialize_database,
    utc_now,
)


# ============================================================
# ELITE NETWORK GAME BUILDER
# Draft Game Creator
# Build 1A
# ============================================================

TARGET_YEAR = 2022
GAME_SIZE = 24
MAX_PER_CATEGORY = 2

TEST_GAME_KEY = "regular-blitz-test-2022-001"
TEST_GAME_TITLE = "Regular Blitz — 2022 Test Draft"


# ============================================================
# LOAD QUESTION CANDIDATES
# ============================================================

def load_candidates(target_year: int):
    conn = connect()

    try:
        rows = conn.execute(
            """
            SELECT
                id,
                category,
                question,
                correct_answer,
                fact_check_date,
                source_year,
                network_status,
                freshness_status
            FROM questions
            WHERE source_year = ?
              AND eligible_regular = 1
              AND network_status != 'RETIRED'
              AND network_status != 'HOLD'
            ORDER BY
                fact_check_date ASC,
                id ASC
            """,
            (target_year,),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


# ============================================================
# BALANCED SELECTION
# ============================================================

def select_balanced_questions(
    candidates,
    count: int,
    max_per_category: int,
):
    selected = []
    selected_ids = set()
    category_counts = Counter()

    # --------------------------------------------------------
    # PASS 1
    # Oldest first with category limit.
    # --------------------------------------------------------

    for item in candidates:

        if len(selected) >= count:
            break

        question_id = item["id"]
        category = item["category"]

        if question_id in selected_ids:
            continue

        if category_counts[category] >= max_per_category:
            continue

        selected.append(item)
        selected_ids.add(question_id)
        category_counts[category] += 1

    # --------------------------------------------------------
    # PASS 2
    # Safety fallback if category variety is too small.
    # --------------------------------------------------------

    if len(selected) < count:

        for item in candidates:

            if len(selected) >= count:
                break

            question_id = item["id"]

            if question_id in selected_ids:
                continue

            selected.append(item)
            selected_ids.add(question_id)

            category_counts[item["category"]] += 1

    return selected


# ============================================================
# SLOT RULES
# ============================================================

def make_slot(index: int):
    round_number = (index // 6) + 1
    question_number = (index % 6) + 1

    slot_id = f"R{round_number}Q{question_number}"

    return (
        slot_id,
        round_number,
        question_number,
    )


def get_slot_rules(
    round_number: int,
    question_number: int,
):
    """
    Mirrors the current Elite Blitz format.
    """

    # --------------------------------------------------------
    # FINAL WAGER
    # R4Q6
    # --------------------------------------------------------

    if round_number == 4 and question_number == 6:
        return {
            "question_type": "final_wager",
            "scoring_type": "final_wager",
            "timer_seconds": 75,
            "wager_seconds": None,
            "max_points": None,
            "min_points": None,
            "special": {
                "typed_answer": True,
                "needs_choices": False,
            },
        }

    # --------------------------------------------------------
    # ROULETTE
    # R1Q6, R2Q6, R3Q6
    # --------------------------------------------------------

    if (
        round_number in {1, 2, 3}
        and question_number == 6
    ):
        return {
            "question_type": "roulette",
            "scoring_type": "roulette",
            "timer_seconds": 45,
            "wager_seconds": 45,
            "max_points": None,
            "min_points": None,
            "special": {
                "needs_choices": True,
                "choice_count": 4,
            },
        }

    # --------------------------------------------------------
    # NORMAL FASTEST ANSWER
    # --------------------------------------------------------

    round_points = {
        1: 10,
        2: 20,
        3: 30,
        4: 40,
    }

    special = {
        "needs_choices": True,
        "choice_count": (
            6
            if round_number == 4
            else 4
        ),
    }

    # R3Q4 speed bonus
    if (
        round_number == 3
        and question_number == 4
    ):
        special["speed_bonus_points"] = [
            20,
            10,
            5,
        ]

        special["speed_bonus_phone_seconds"] = 4
        special["speed_bonus_tv_seconds"] = 5

    return {
        "question_type": "normal",
        "scoring_type": "fastest",
        "timer_seconds": 45,
        "wager_seconds": None,
        "max_points": round_points[round_number],
        "min_points": 5,
        "special": special,
    }


# ============================================================
# SAVE DRAFT GAME
# ============================================================

def save_draft_game(selected):
    conn = connect()

    now = utc_now()

    try:
        # ----------------------------------------------------
        # CREATE / UPDATE GAME HEADER
        # ----------------------------------------------------

        conn.execute(
            """
            INSERT INTO games (
                game_key,
                title,
                game_type,
                scheduled_for,
                status,
                created_at,
                updated_at
            )
            VALUES (
                ?,
                ?,
                'REGULAR_BLITZ',
                NULL,
                'DRAFT',
                ?,
                ?
            )

            ON CONFLICT(game_key)
            DO UPDATE SET
                title = excluded.title,
                game_type = excluded.game_type,
                status = 'DRAFT',
                updated_at = excluded.updated_at
            """,
            (
                TEST_GAME_KEY,
                TEST_GAME_TITLE,
                now,
                now,
            ),
        )

        game_row = conn.execute(
            """
            SELECT id
            FROM games
            WHERE game_key = ?
            """,
            (TEST_GAME_KEY,),
        ).fetchone()

        game_id = game_row["id"]

        # ----------------------------------------------------
        # REBUILD TEST DRAFT SAFELY
        # ----------------------------------------------------

        conn.execute(
            """
            DELETE FROM game_questions
            WHERE game_id = ?
            """,
            (game_id,),
        )

        # ----------------------------------------------------
        # SAVE ALL 24 SLOTS
        # ----------------------------------------------------

        for index, item in enumerate(selected):

            (
                slot_id,
                round_number,
                question_number,
            ) = make_slot(index)

            rules = get_slot_rules(
                round_number,
                question_number,
            )

            snapshot = {
                "category": item["category"],
                "question": item["question"],
                "correct_answer": item[
                    "correct_answer"
                ],
                "fact_check_date": item[
                    "fact_check_date"
                ],
                "source_year": item[
                    "source_year"
                ],
                "network_status": item[
                    "network_status"
                ],
                "freshness_status": item[
                    "freshness_status"
                ],
                "special": rules["special"],
            }

            conn.execute(
                """
                INSERT INTO game_questions (
                    game_id,
                    question_id,

                    slot_id,
                    round_number,
                    question_number,
                    display_order,

                    question_type,
                    scoring_type,

                    timer_seconds,
                    wager_seconds,

                    max_points,
                    min_points,

                    hint,

                    choices_json,
                    correct_index,

                    question_snapshot_json,
                    presentation_overrides_json
                )
                VALUES (
                    ?,
                    ?,

                    ?,
                    ?,
                    ?,
                    ?,

                    ?,
                    ?,

                    ?,
                    ?,

                    ?,
                    ?,

                    '',

                    '[]',
                    NULL,

                    ?,
                    '{}'
                )
                """,
                (
                    game_id,
                    item["id"],

                    slot_id,
                    round_number,
                    question_number,
                    index + 1,

                    rules["question_type"],
                    rules["scoring_type"],

                    rules["timer_seconds"],
                    rules["wager_seconds"],

                    rules["max_points"],
                    rules["min_points"],

                    json.dumps(
                        snapshot,
                        ensure_ascii=False,
                    ),
                ),
            )

        conn.commit()

        return game_id

    finally:
        conn.close()


# ============================================================
# PRINT SAVED DRAFT
# ============================================================

def print_saved_game(game_id):
    conn = connect()

    try:
        game = conn.execute(
            """
            SELECT *
            FROM games
            WHERE id = ?
            """,
            (game_id,),
        ).fetchone()

        rows = conn.execute(
            """
            SELECT
                gq.slot_id,
                gq.round_number,
                gq.question_number,
                gq.question_type,
                gq.scoring_type,
                gq.timer_seconds,
                gq.wager_seconds,
                gq.max_points,
                gq.min_points,

                q.category,
                q.question,
                q.correct_answer,
                q.fact_check_date,
                q.network_status,
                q.freshness_status

            FROM game_questions gq

            JOIN questions q
              ON q.id = gq.question_id

            WHERE gq.game_id = ?

            ORDER BY
                gq.display_order
            """,
            (game_id,),
        ).fetchall()

    finally:
        conn.close()

    print()
    print(
        "=============================================================="
    )
    print(
        " ELITE NETWORK — SAVED DRAFT GAME"
    )
    print(
        "=============================================================="
    )

    print(f"Game ID:           {game['id']}")
    print(f"Game Key:          {game['game_key']}")
    print(f"Title:             {game['title']}")
    print(f"Type:              {game['game_type']}")
    print(f"Status:            {game['status']}")
    print(f"Questions saved:   {len(rows)}")

    print(
        "=============================================================="
    )

    category_counts = Counter()

    for row in rows:

        category_counts[
            row["category"]
        ] += 1

        print()
        print(
            "--------------------------------------------------------------"
        )

        print(
            f"{row['slot_id']}  |  "
            f"{row['question_type']}  |  "
            f"{row['category']}  |  "
            f"{row['fact_check_date']}"
        )

        print(
            "--------------------------------------------------------------"
        )

        print(row["question"])
        print()
        print(
            f"CORRECT ANSWER: "
            f"{row['correct_answer']}"
        )

        if row["slot_id"] == "R4Q6":
            print(
                "CHOICES: Not required — Final Wager"
            )

        elif row["network_status"] == "NEEDS_CHOICES":
            print(
                "CHOICES: ⚠ NEEDS DISTRACTORS"
            )

        print(
            f"FRESHNESS: "
            f"{row['freshness_status']}"
        )

    print()
    print(
        "=============================================================="
    )
    print(" CATEGORY MIX")
    print(
        "=============================================================="
    )

    for category, amount in sorted(
        category_counts.items(),
        key=lambda pair: (
            -pair[1],
            pair[0],
        ),
    ):
        print(
            f"{amount:>2}  {category}"
        )

    print(
        "=============================================================="
    )
    print()
    print(
        "Draft game saved successfully."
    )
    print()


# ============================================================
# MAIN
# ============================================================

def main():
    initialize_database()

    candidates = load_candidates(
        TARGET_YEAR
    )

    if len(candidates) < GAME_SIZE:
        raise RuntimeError(
            f"Only {len(candidates)} "
            "eligible questions found. "
            f"Need at least {GAME_SIZE}."
        )

    selected = select_balanced_questions(
        candidates=candidates,
        count=GAME_SIZE,
        max_per_category=
            MAX_PER_CATEGORY,
    )

    if len(selected) != GAME_SIZE:
        raise RuntimeError(
            f"Draft only produced "
            f"{len(selected)} questions. "
            f"Expected {GAME_SIZE}."
        )

    game_id = save_draft_game(
        selected
    )

    print_saved_game(
        game_id
    )


if __name__ == "__main__":
    main()