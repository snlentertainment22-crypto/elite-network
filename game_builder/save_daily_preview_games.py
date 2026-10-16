from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone

try:
    from .question_bank import connect, initialize_database

    from .auto_block_selector import (
        load_questions,
        get_pool_questions,
        build_games,
        collect_ids,
        verify_global_uniqueness,
    )

except ImportError:
    from question_bank import connect, initialize_database

    from auto_block_selector import (
        load_questions,
        get_pool_questions,
        build_games,
        collect_ids,
        verify_global_uniqueness,
    )


# ============================================================
# ELITE NETWORK
# SAVE DAILY AUTO-BUILD AS REAL GAME BUILDER DRAFTS
# Build 1A
#
# Uses the SAME selector/seed already proven in:
#
#     auto_block_selector.py
#
# Uses the existing proven game as the SLOT TEMPLATE:
#
#     regular-blitz-test-2022-001
#
# NO AI CALLS.
#
# All newly created games start as DRAFT and NEEDS_REVIEW.
# ============================================================


TEMPLATE_GAME_KEY = (
    "regular-blitz-test-2022-001"
)

DEFAULT_SEED = 20261004


def utc_now() -> str:

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


# ============================================================
# LOAD TEMPLATE SLOT STRUCTURE
# ============================================================


def load_template_slots(
    conn,
) -> list[dict]:

    rows = conn.execute(
        """
        SELECT
            gq.*

        FROM game_questions gq

        JOIN games g
          ON g.id = gq.game_id

        WHERE g.game_key = ?

        ORDER BY
            gq.display_order
        """,
        (
            TEMPLATE_GAME_KEY,
        ),
    ).fetchall()

    slots = [
        dict(row)
        for row in rows
    ]

    if len(slots) != 24:

        raise RuntimeError(
            f"Template game should contain 24 slots, "
            f"but found {len(slots)}."
        )

    return slots


# ============================================================
# LOAD ONE MASTER QUESTION
# ============================================================


def load_question(
    conn,
    question_id: int,
) -> dict:

    row = conn.execute(
        """
        SELECT *
        FROM questions
        WHERE id = ?
        """,
        (
            question_id,
        ),
    ).fetchone()

    if row is None:

        raise RuntimeError(
            f"Question ID {question_id} was not found."
        )

    return dict(row)


# ============================================================
# SNAPSHOT
# ============================================================


def build_question_snapshot(
    question: dict,
) -> dict:

    snapshot = {
        "category":
            question.get(
                "category",
                "",
            ),

        "question":
            question.get(
                "question",
                "",
            ),

        "correct_answer":
            question.get(
                "correct_answer",
                "",
            ),

        "network_status":
            question.get(
                "network_status",
                "NEEDS_REVIEW",
            ),

        "game_review": {
            "status":
                "NEEDS_REVIEW",
        },
    }


    # Preserve useful master metadata when available.

    for field in (
        "fact_check_date",
        "source_year",
        "freshness_status",
        "source_key",
    ):

        if (
            field in question
            and
            question[field] is not None
        ):

            snapshot[
                field
            ] = question[
                field
            ]


    return snapshot


# ============================================================
# GAME EXISTS CHECK
# ============================================================


def game_exists(
    conn,
    game_key: str,
) -> bool:

    row = conn.execute(
        """
        SELECT id
        FROM games
        WHERE game_key = ?
        LIMIT 1
        """,
        (
            game_key,
        ),
    ).fetchone()

    return row is not None


# ============================================================
# CREATE ONE GAME
# ============================================================


def create_game(
    conn,
    template_slots: list[dict],
    game_key: str,
    title: str,
    game_type: str,
    questions: list[dict],
    scheduled_for: str | None = None,
) -> int:

    if len(questions) != 24:

        raise RuntimeError(
            f"{title} does not contain exactly 24 questions."
        )


    if game_exists(
        conn,
        game_key,
    ):

        raise RuntimeError(
            f"Game already exists: {game_key}\n"
            f"No changes were made.\n"
            f"Use a different seed/key or delete the test game first."
        )


    now = utc_now()


    cursor = conn.execute(
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
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_key,
            title,
            game_type,
            scheduled_for,
            "DRAFT",
            now,
            now,
        ),
    )


    game_id = int(
        cursor.lastrowid
    )


    for index, (
        template,
        selected,
    ) in enumerate(
        zip(
            template_slots,
            questions,
        ),
        start=1,
    ):

        question_id = int(
            selected["id"]
        )


        master = load_question(
            conn,
            question_id,
        )


        snapshot = (
            build_question_snapshot(
                master
            )
        )


        # -----------------------------------------------
        # IMPORTANT
        #
        # Do NOT copy choices_json from the old template.
        # Those choices belong to a different question.
        #
        # The question's reusable wrong_answers_json lives
        # on the master question and AI prep/review can fill
        # anything still missing.
        # -----------------------------------------------

        choices_json = "[]"

        correct_index = None


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
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                game_id,
                question_id,

                template[
                    "slot_id"
                ],

                template[
                    "round_number"
                ],

                template[
                    "question_number"
                ],

                template[
                    "display_order"
                ],

                template[
                    "question_type"
                ],

                template[
                    "scoring_type"
                ],

                template[
                    "timer_seconds"
                ],

                template[
                    "wager_seconds"
                ],

                template[
                    "max_points"
                ],

                template[
                    "min_points"
                ],

                "",

                choices_json,

                correct_index,

                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                ),

                "{}",
            ),
        )


    return game_id


# ============================================================
# REBUILD EXACT SAME DAILY SELECTION
# ============================================================


def build_selection(
    seed: int,
    excluded_ids: set[int] | None = None,
):

    if excluded_ids is None:
        excluded_ids = set()

    rng = random.Random(
        seed
    )


    all_questions = (
        load_questions()
    )


    # --------------------------------------------------------
    # SPORTS FIRST
    # --------------------------------------------------------

    sports_pool = (
        get_pool_questions(
            all_questions,
            "sports",
            excluded_ids=excluded_ids,
        )
    )


    sports_games = build_games(
        sports_pool,
        3,
        rng,
    )


    sports_used = collect_ids(
        sports_games
    )


    # --------------------------------------------------------
    # REGULAR NEXT
    # Excludes Sports questions already used that day.
    # --------------------------------------------------------

    regular_pool = (
        get_pool_questions(
            all_questions,
            "regular",
            excluded_ids=(
                excluded_ids
                |
                sports_used
            ),
        )
    )


    regular_games = build_games(
        regular_pool,
        3,
        rng,
    )


    regular_used = collect_ids(
        regular_games
    )


    # --------------------------------------------------------
    # AFTER DARK
    # --------------------------------------------------------

    used_before_dark = (
        sports_used
        |
        regular_used
    )


    after_dark_pool = (
        get_pool_questions(
            all_questions,
            "after_dark",
            excluded_ids=(
                excluded_ids
                |
                used_before_dark
            ),
        )
    )


    after_dark_games = build_games(
        after_dark_pool,
        3,
        rng,
    )


    all_games = (
        sports_games
        +
        regular_games
        +
        after_dark_games
    )


    verify_global_uniqueness(
        all_games
    )


    return (
        sports_games,
        regular_games,
        after_dark_games,
    )


# ============================================================
# SAVE ALL SEVEN
# ============================================================


def save_daily_games(
    seed: int,
):

    initialize_database()


    (
        sports_games,
        regular_games,
        after_dark_games,
    ) = build_selection(
        seed
    )


    game_specs = [

        (
            f"sports-blitz-test-{seed}-01",
            "Sports Blitz — Test Game 1",
            "SPORTS_BLITZ",
            sports_games[0],
        ),

        (
            f"sports-blitz-test-{seed}-02",
            "Sports Blitz — Test Game 2",
            "SPORTS_BLITZ",
            sports_games[1],
        ),

        (
            f"sports-blitz-test-{seed}-03",
            "Sports Blitz — Test Game 3",
            "SPORTS_BLITZ",
            sports_games[2],
        ),


        (
            f"regular-blitz-test-{seed}-6pm",
            "Regular Blitz — 6 PM Test",
            "REGULAR_BLITZ",
            regular_games[0],
        ),

        (
            f"regular-blitz-test-{seed}-7pm",
            "Regular Blitz — 7 PM Test",
            "REGULAR_BLITZ",
            regular_games[1],
        ),

        (
            f"regular-blitz-test-{seed}-8pm",
            "Regular Blitz — 8 PM Test",
            "REGULAR_BLITZ",
            regular_games[2],
        ),


        (
            f"after-dark-test-{seed}-9pm",
            "After Dark — 9 PM Test",
            "AFTER_DARK_BLITZ",
            after_dark_games[0],
        ),

        (
            f"after-dark-test-{seed}-10pm",
            "After Dark - 10 PM Test",
            "AFTER_DARK_BLITZ",
            after_dark_games[1],
        ),

        (
            f"after-dark-test-{seed}-11pm",
            "After Dark - 11 PM Test",
            "AFTER_DARK_BLITZ",
            after_dark_games[2],
        ),
    ]


    conn = connect()


    created = []


    try:

        template_slots = (
            load_template_slots(
                conn
            )
        )


        # ----------------------------------------------------
        # PREFLIGHT
        #
        # Refuse BEFORE writing anything if one of the game
        # keys already exists.
        # ----------------------------------------------------

        existing = []

        for (
            game_key,
            title,
            game_type,
            questions,
        ) in game_specs:

            if game_exists(
                conn,
                game_key,
            ):

                existing.append(
                    game_key
                )


        if existing:

            raise RuntimeError(
                "\nSAVE STOPPED BEFORE CHANGING DATABASE.\n\n"
                "These games already exist:\n\n"
                +
                "\n".join(
                    f"  - {key}"
                    for key
                    in existing
                )
            )


        # ----------------------------------------------------
        # CREATE
        # ----------------------------------------------------

        for (
            game_key,
            title,
            game_type,
            questions,
        ) in game_specs:

            game_id = create_game(
                conn,
                template_slots,
                game_key,
                title,
                game_type,
                questions,
            )


            created.append(
                {
                    "id":
                        game_id,

                    "game_key":
                        game_key,

                    "title":
                        title,

                    "question_count":
                        len(
                            questions
                        ),
                }
            )


        conn.commit()


    except Exception:

        conn.rollback()

        raise


    finally:

        conn.close()


    # ========================================================
    # RESULT
    # ========================================================

    print()

    print(
        "======================================================"
    )

    print(
        " ELITE NETWORK — DAILY GAME SAVE COMPLETE"
    )

    print(
        "======================================================"
    )

    print()


    for game in created:

        print(
            f"✓ {game['title']}"
        )

        print(
            f"  Key: "
            f"{game['game_key']}"
        )

        print(
            f"  Questions: "
            f"{game['question_count']}"
        )

        print()


    print(
        "------------------------------------------------------"
    )

    print(
        f"Games created:      "
        f"{len(created)}"
    )

    print(
        f"Questions assigned: "
        f"{len(created) * 24}"
    )

    print(
        "AI calls made:      0"
    )

    print()

    print(
        "All games are DRAFT."
    )

    print(
        "All questions require manual review."
    )

    print()


    return created


# ============================================================
# COMMAND LINE
# ============================================================


def main():

    parser = argparse.ArgumentParser()


    parser.add_argument(
        "--seed",
        type=int,
        default=
            DEFAULT_SEED,
    )


    args = parser.parse_args()


    save_daily_games(
        args.seed
    )


if __name__ == "__main__":

    main()