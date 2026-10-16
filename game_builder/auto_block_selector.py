from __future__ import annotations

import argparse
import random
from collections import defaultdict

try:
    from .question_bank import connect, initialize_database
    from .question_pools import get_question_pools
except ImportError:
    from question_bank import connect, initialize_database
    from question_pools import get_question_pools


# ============================================================
# ELITE NETWORK — DAILY BLOCK SELECTOR
# Build 1A
#
# FREE DRY RUN ONLY.
#
# Builds:
#   3 Sports games  x 24 = 72
#   3 Regular games x 24 = 72
#   1 After Dark game x 24 = 24
#
# TOTAL = 168 UNIQUE QUESTIONS
#
# IMPORTANT:
# - NO AI CALLS
# - NO DATABASE CHANGES
# - NO QUESTIONS MARKED USED
# - NO GAMES SAVED
#
# Sports is selected FIRST.
# Regular then excludes those Sports questions so the same
# question cannot appear in Sports and Regular on the same day.
# ============================================================


QUESTIONS_PER_GAME = 24

SPORTS_GAMES = 3
REGULAR_GAMES = 3
AFTER_DARK_GAMES = 3


# Avoid obviously time-sensitive material in this old
# test database until freshness checking is wired in.
EXCLUDED_REGULAR_CATEGORIES = {
    "current events",
}


def normalize(value) -> str:

    return " ".join(
        str(
            value or ""
        )
        .strip()
        .lower()
        .split()
    )


def load_questions() -> list[dict]:

    initialize_database()

    conn = connect()

    try:

        rows = conn.execute(
            """
            SELECT
                id,
                category,
                question,
                correct_answer,
                network_status

            FROM questions

            ORDER BY id
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()


# ============================================================
# POOL FILTERS
# ============================================================


def get_pool_questions(
    all_questions: list[dict],
    pool_name: str,
    excluded_ids: set[int] | None = None,
) -> list[dict]:

    if excluded_ids is None:
        excluded_ids = set()

    result = []

    for question in all_questions:

        question_id = int(
            question["id"]
        )

        if question_id in excluded_ids:
            continue

        category = (
            question["category"]
            or ""
        ).strip()

        pools = get_question_pools(
            category
        )

        if not pools.get(
            pool_name,
            False,
        ):
            continue

        if (
            pool_name == "regular"
            and
            normalize(category)
            in EXCLUDED_REGULAR_CATEGORIES
        ):
            continue

        result.append(
            question
        )

    return result


# ============================================================
# BALANCED CATEGORY SELECTOR
#
# Tries to spread categories around instead of grabbing
# twenty questions from one category.
# ============================================================


def select_balanced_questions(
    candidates: list[dict],
    count: int,
    rng: random.Random,
) -> list[dict]:

    if len(candidates) < count:

        raise RuntimeError(
            f"Need {count} questions, "
            f"but only {len(candidates)} are available."
        )

    by_category = defaultdict(
        list
    )

    for question in candidates:

        category = (
            question["category"]
            or
            "Uncategorized"
        ).strip()

        by_category[
            category
        ].append(
            question
        )

    # Randomize question order inside each category.
    for questions in by_category.values():

        rng.shuffle(
            questions
        )

    categories = list(
        by_category.keys()
    )

    rng.shuffle(
        categories
    )

    selected = []

    # Round-robin through category buckets.
    # This naturally spreads categories across the game.
    while (
        len(selected) < count
    ):

        made_progress = False

        for category in categories:

            bucket = by_category[
                category
            ]

            if not bucket:
                continue

            selected.append(
                bucket.pop()
            )

            made_progress = True

            if len(selected) >= count:
                break

        if not made_progress:
            break

        # Shuffle the category order before the next pass
        # so repeated categories don't always occur
        # in the same sequence.
        rng.shuffle(
            categories
        )

    if len(selected) != count:

        raise RuntimeError(
            f"Could only select "
            f"{len(selected)} of {count} questions."
        )

    return selected


# ============================================================
# BUILD MULTIPLE GAMES
# ============================================================


def build_games(
    pool_questions: list[dict],
    game_count: int,
    rng: random.Random,
) -> list[list[dict]]:

    games = []

    used_ids = set()

    for _ in range(
        game_count
    ):

        available = [
            question
            for question
            in pool_questions
            if int(
                question["id"]
            )
            not in used_ids
        ]

        game = select_balanced_questions(
            available,
            QUESTIONS_PER_GAME,
            rng,
        )

        games.append(
            game
        )

        for question in game:

            used_ids.add(
                int(
                    question["id"]
                )
            )

    return games


def collect_ids(
    games: list[list[dict]],
) -> set[int]:

    result = set()

    for game in games:

        for question in game:

            result.add(
                int(
                    question["id"]
                )
            )

    return result


# ============================================================
# PRINTING
# ============================================================


def print_game(
    title: str,
    questions: list[dict],
) -> None:

    print()
    print(
        "======================================================"
    )

    print(
        f" {title}"
    )

    print(
        "======================================================"
    )

    for number, question in enumerate(
        questions,
        start=1,
    ):

        print()

        print(
            f"{number:02d}. "
            f"[{question['category']}]"
        )

        print(
            f"    {question['question']}"
        )

        print(
            f"    ANSWER: "
            f"{question['correct_answer']}"
        )


def verify_global_uniqueness(
    all_games: list[list[dict]],
) -> None:

    all_ids = []

    for game in all_games:

        for question in game:

            all_ids.append(
                int(
                    question["id"]
                )
            )

    unique_ids = set(
        all_ids
    )

    if (
        len(all_ids)
        !=
        len(unique_ids)
    ):

        raise RuntimeError(
            "DUPLICATE QUESTION DETECTED "
            "ACROSS DAILY BLOCK."
        )


# ============================================================
# MAIN BUILD
# ============================================================


def build_daily_preview(
    seed: int,
) -> None:

    rng = random.Random(
        seed
    )

    all_questions = (
        load_questions()
    )

    # --------------------------------------------------------
    # 1. SPORTS FIRST
    # --------------------------------------------------------

    sports_pool = (
        get_pool_questions(
            all_questions,
            "sports",
        )
    )

    sports_games = build_games(
        sports_pool,
        SPORTS_GAMES,
        rng,
    )

    sports_used = collect_ids(
        sports_games
    )

    # --------------------------------------------------------
    # 2. REGULAR
    #
    # Exclude everything already used in Sports.
    # --------------------------------------------------------

    regular_pool = (
        get_pool_questions(
            all_questions,
            "regular",
            excluded_ids=sports_used,
        )
    )

    regular_games = build_games(
        regular_pool,
        REGULAR_GAMES,
        rng,
    )

    regular_used = collect_ids(
        regular_games
    )

    # --------------------------------------------------------
    # 3. AFTER DARK
    #
    # Dedicated After Dark categories are already excluded
    # from Regular by question_pools.py.
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
            excluded_ids=already_used,
        )
    )

    after_dark_games = build_games(
        after_dark_pool,
        AFTER_DARK_GAMES,
        rng,
    )

    # --------------------------------------------------------
    # VERIFY ALL QUESTIONS UNIQUE FOR THIS DAY
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    print()
    print(
        "======================================================"
    )

    print(
        " ELITE NETWORK — DAILY AUTO-BUILD PREVIEW"
    )

    print(
        "======================================================"
    )

    print()

    print(
        f"Seed: {seed}"
    )

    print()

    print(
        f"Sports pool available:     "
        f"{len(sports_pool)}"
    )

    print(
        f"Regular pool available:    "
        f"{len(regular_pool)}"
    )

    print(
        f"After Dark pool available: "
        f"{len(after_dark_pool)}"
    )

    # --------------------------------------------------------
    # SPORTS
    # --------------------------------------------------------

    for index, game in enumerate(
        sports_games,
        start=1,
    ):

        print_game(
            f"SPORTS GAME {index}",
            game,
        )

    # --------------------------------------------------------
    # REGULAR
    # --------------------------------------------------------

    regular_labels = [
        "REGULAR — 6 PM",
        "REGULAR — 7 PM",
        "REGULAR — 8 PM",
    ]

    for label, game in zip(
        regular_labels,
        regular_games,
    ):

        print_game(
            label,
            game,
        )

    # --------------------------------------------------------
    # AFTER DARK
    # --------------------------------------------------------

    for index, game in enumerate(
        after_dark_games,
        start=1,
    ):

        print_game(
            "AFTER DARK TEST GAME",
            game,
        )

    # --------------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------------

    total_questions = sum(
        len(game)
        for game
        in all_games
    )

    print()
    print(
        "======================================================"
    )

    print(
        " DAILY PREVIEW SUMMARY"
    )

    print(
        "======================================================"
    )

    print(
        f"Sports games:       "
        f"{len(sports_games)}"
    )

    print(
        f"Regular games:      "
        f"{len(regular_games)}"
    )

    print(
        f"After Dark games:   "
        f"{len(after_dark_games)}"
    )

    print()

    print(
        f"Questions selected: "
        f"{total_questions}"
    )

    print(
        f"Unique questions:   "
        f"{total_questions}"
    )

    print(
        "Duplicates:         0"
    )

    print()
    print(
        "AI calls made:      0"
    )

    print(
        "Database changes:   0"
    )

    print()
    print(
        "THIS IS A PREVIEW ONLY."
    )

    print()


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--seed",
        type=int,
        default=20261004,
    )

    args = parser.parse_args()

    build_daily_preview(
        args.seed
    )


if __name__ == "__main__":

    main()