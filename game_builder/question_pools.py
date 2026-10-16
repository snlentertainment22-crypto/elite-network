from __future__ import annotations

import re

try:
    from .question_bank import connect, initialize_database
except ImportError:
    from question_bank import connect, initialize_database


# ============================================================
# ELITE NETWORK — QUESTION POOLS
# Build 1A
#
# No schema changes.
# No AI calls.
#
# Pool eligibility is calculated from the existing
# Fact Checked category.
#
# Standard After Dark format:
#
#     After Dark - Dating
#     After Dark - Music
#     After Dark - Movies
#
# As long as AFTER DARK appears first, it is recognized.
# ============================================================


SPORTS_TERMS = {
    "sports",
    "sport",
    "football",
    "nfl",
    "baseball",
    "mlb",
    "basketball",
    "nba",
    "hockey",
    "nhl",
    "golf",
    "tennis",
    "soccer",
    "olympics",
    "olympic",
    "ncaa",
    "college football",
    "college basketball",
    "nascar",
    "racing",
    "boxing",
    "mma",
    "ufc",
    "wrestling",
}


def normalize_category(
    value: str | None,
) -> str:

    text = str(
        value or ""
    ).strip().lower()

    # Make hyphens/slashes/etc. behave like spaces.
    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text


def is_after_dark_category(
    category: str | None,
) -> bool:

    normalized = normalize_category(
        category
    )

    return normalized.startswith(
        "after dark"
    )


def is_sports_category(
    category: str | None,
) -> bool:

    normalized = normalize_category(
        category
    )

    if not normalized:
        return False

    # Dedicated After Dark material does not
    # automatically enter Sports games.
    if normalized.startswith(
        "after dark"
    ):
        return False

    for term in SPORTS_TERMS:

        normalized_term = (
            normalize_category(
                term
            )
        )

        if (
            normalized ==
            normalized_term
        ):

            return True

        if (
            normalized.startswith(
                normalized_term + " "
            )
        ):

            return True

        if (
            normalized.endswith(
                " " + normalized_term
            )
        ):

            return True

    return False


def is_regular_category(
    category: str | None,
) -> bool:

    # Regular Elite may use normal categories,
    # including ordinary Sports questions.
    #
    # The only automatic exclusion right now
    # is dedicated After Dark material.

    return not is_after_dark_category(
        category
    )


def get_question_pools(
    category: str | None,
) -> dict:

    return {
        "regular":
            is_regular_category(
                category
            ),

        "sports":
            is_sports_category(
                category
            ),

        "after_dark":
            is_after_dark_category(
                category
            ),
    }


# ============================================================
# INVENTORY REPORT
# ============================================================


def inventory_report() -> None:

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

    finally:

        conn.close()


    counts = {
        "total": 0,
        "regular": 0,
        "sports": 0,
        "after_dark": 0,
    }


    category_counts = {
        "sports": {},
        "after_dark": {},
    }


    for row in rows:

        counts["total"] += 1

        category = (
            row["category"]
            or
            ""
        ).strip()

        pools = get_question_pools(
            category
        )


        if pools["regular"]:

            counts["regular"] += 1


        if pools["sports"]:

            counts["sports"] += 1

            category_counts[
                "sports"
            ][category] = (
                category_counts[
                    "sports"
                ].get(
                    category,
                    0,
                )
                + 1
            )


        if pools["after_dark"]:

            counts["after_dark"] += 1

            category_counts[
                "after_dark"
            ][category] = (
                category_counts[
                    "after_dark"
                ].get(
                    category,
                    0,
                )
                + 1
            )


    print()
    print(
        "======================================================"
    )

    print(
        " ELITE NETWORK — QUESTION POOL INVENTORY"
    )

    print(
        "======================================================"
    )

    print()

    print(
        f"Total questions:     "
        f"{counts['total']}"
    )

    print(
        f"Regular eligible:    "
        f"{counts['regular']}"
    )

    print(
        f"Sports eligible:     "
        f"{counts['sports']}"
    )

    print(
        f"After Dark eligible: "
        f"{counts['after_dark']}"
    )


    print()
    print(
        "------------------------------------------------------"
    )

    print(
        " SPORTS CATEGORIES FOUND"
    )

    print(
        "------------------------------------------------------"
    )


    sports_sorted = sorted(
        category_counts[
            "sports"
        ].items(),
        key=lambda item: (
            -item[1],
            item[0].lower(),
        ),
    )


    if sports_sorted:

        for category, count in sports_sorted:

            print(
                f"{count:5}  "
                f"{category}"
            )

    else:

        print(
            "None found."
        )


    print()
    print(
        "------------------------------------------------------"
    )

    print(
        " AFTER DARK CATEGORIES FOUND"
    )

    print(
        "------------------------------------------------------"
    )


    dark_sorted = sorted(
        category_counts[
            "after_dark"
        ].items(),
        key=lambda item: (
            -item[1],
            item[0].lower(),
        ),
    )


    if dark_sorted:

        for category, count in dark_sorted:

            print(
                f"{count:5}  "
                f"{category}"
            )

    else:

        print(
            "None found yet."
        )


    print()
    print(
        "======================================================"
    )

    print(
        "NO AI CALLS MADE."
    )

    print(
        "NO DATABASE CHANGES MADE."
    )

    print(
        "======================================================"
    )

    print()


if __name__ == "__main__":

    inventory_report()