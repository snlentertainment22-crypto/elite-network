from __future__ import annotations

import random

try:
    from .question_bank import (
        connect,
        initialize_database,
    )

    from .auto_block_selector import (
        load_questions,
        get_pool_questions,
        build_games,
        collect_ids,
        verify_global_uniqueness,
    )

    from .save_daily_preview_games import (
        load_template_slots,
        create_game,
    )

except ImportError:
    from question_bank import (
        connect,
        initialize_database,
    )

    from auto_block_selector import (
        load_questions,
        get_pool_questions,
        build_games,
        collect_ids,
        verify_global_uniqueness,
    )

    from save_daily_preview_games import (
        load_template_slots,
        create_game,
    )


# ============================================================
# ELITE NETWORK
# ADD MISSING AFTER DARK 10 PM + 11 PM TEST GAMES
#
# Reconstructs the SAME daily selection:
#
# Seed: 20261004
#
# Then saves only:
#
#   After Dark — 10 PM Test
#   After Dark — 11 PM Test
#
# Existing 7 games are NOT changed.
#
# NO AI CALLS.
# ============================================================


SEED = 20261004


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


def build_full_day_selection():

    rng = random.Random(
        SEED
    )

    all_questions = (
        load_questions()
    )

    # --------------------------------------------------------
    # SPORTS — 3 GAMES
    # --------------------------------------------------------

    sports_pool = (
        get_pool_questions(
            all_questions,
            "sports",
        )
    )

    sports_games = (
        build_games(
            sports_pool,
            3,
            rng,
        )
    )

    sports_used = (
        collect_ids(
            sports_games
        )
    )

    # --------------------------------------------------------
    # REGULAR — 3 GAMES
    # --------------------------------------------------------

    regular_pool = (
        get_pool_questions(
            all_questions,
            "regular",
            excluded_ids=
                sports_used,
        )
    )

    regular_games = (
        build_games(
            regular_pool,
            3,
            rng,
        )
    )

    regular_used = (
        collect_ids(
            regular_games
        )
    )

    # --------------------------------------------------------
    # AFTER DARK — 3 GAMES
    # --------------------------------------------------------

    already_used = (
        sports_used
        |
        regular_used
    )

    after_dark_pool = (
        get_pool_questions(
            all_questions,
            "after_dark",
            excluded_ids=
                already_used,
        )
    )

    after_dark_games = (
        build_games(
            after_dark_pool,
            3,
            rng,
        )
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

    return after_dark_games


def main():

    initialize_database()

    after_dark_games = (
        build_full_day_selection()
    )

    specs = [

        (
            f"after-dark-test-{SEED}-10pm",
            "After Dark — 10 PM Test",
            "AFTER_DARK_BLITZ",
            after_dark_games[1],
        ),

        (
            f"after-dark-test-{SEED}-11pm",
            "After Dark — 11 PM Test",
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
        # ----------------------------------------------------

        for (
            game_key,
            title,
            game_type,
            questions,
        ) in specs:

            if game_exists(
                conn,
                game_key,
            ):

                raise RuntimeError(
                    "\nSTOPPED BEFORE CHANGING DATABASE.\n\n"
                    f"Game already exists:\n"
                    f"{game_key}\n"
                )

        # ----------------------------------------------------
        # SAVE TWO GAMES
        # ----------------------------------------------------

        for (
            game_key,
            title,
            game_type,
            questions,
        ) in specs:

            game_id = (
                create_game(
                    conn,
                    template_slots,
                    game_key,
                    title,
                    game_type,
                    questions,
                )
            )

            created.append(
                {
                    "id":
                        game_id,

                    "key":
                        game_key,

                    "title":
                        title,
                }
            )

        conn.commit()

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


    print()
    print(
        "======================================================"
    )

    print(
        " ELITE NETWORK — AFTER DARK COMPLETION"
    )

    print(
        "======================================================"
    )

    print()

    for item in created:

        print(
            f"✓ {item['title']}"
        )

        print(
            f"  Key: {item['key']}"
        )

        print(
            "  Questions: 24"
        )

        print()

    print(
        "------------------------------------------------------"
    )

    print(
        f"Games created:      {len(created)}"
    )

    print(
        f"Questions assigned: {len(created) * 24}"
    )

    print(
        "AI calls made:      0"
    )

    print()

    print(
        "Full test day now contains:"
    )

    print(
        "3 Sports + 3 Regular + 3 After Dark"
    )

    print(
        "= 9 games / 216 question slots"
    )

    print()


if __name__ == "__main__":

    main()