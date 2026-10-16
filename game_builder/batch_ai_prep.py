from __future__ import annotations

import argparse

from .ai_prepare_service import prepare_game_slot
from .question_bank import connect, initialize_database


def get_scheduled_slots(
    scheduled_date: str,
) -> list[dict]:

    initialize_database()

    conn = connect()

    try:

        rows = conn.execute(
            """
            SELECT
                g.game_key,
                g.title,
                g.scheduled_for,
                gq.slot_id,
                gq.display_order,
                gq.question_type

            FROM games g

            JOIN game_questions gq
              ON gq.game_id = g.id

            WHERE g.scheduled_for LIKE ?

            ORDER BY
                g.scheduled_for ASC,
                gq.display_order ASC
            """,
            (
                scheduled_date + "%",
            ),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()


def prep_scheduled_games(
    scheduled_date: str,
) -> dict:

    slots = get_scheduled_slots(
        scheduled_date
    )

    if not slots:
        raise RuntimeError(
            f"No scheduled games found for {scheduled_date}."
        )


    game_keys = []

    for slot in slots:

        if slot["game_key"] not in game_keys:
            game_keys.append(
                slot["game_key"]
            )


    print()
    print("======================================================")
    print(" ELITE NETWORK - BATCH AI PREP")
    print("======================================================")
    print("DATE:", scheduled_date)
    print("GAMES:", len(game_keys))
    print("SLOTS:", len(slots))
    print("======================================================")
    print()


    success = 0
    failed = 0
    zero_call = 0
    api_calls = 0
    failures = []


    for index, slot in enumerate(
        slots,
        start=1,
    ):

        print()
        print(
            f"[{index}/{len(slots)}] "
            f"{slot['title']} - {slot['slot_id']}"
        )

        try:

            result = prepare_game_slot(
                slot["game_key"],
                slot["slot_id"],
            )

            calls = int(
                result.get(
                    "api_calls",
                    0,
                )
                or 0
            )

            api_calls += calls

            if result.get("ok"):

                success += 1

                if calls == 0:
                    zero_call += 1

            else:

                failed += 1

                failures.append(
                    {
                        "game_key":
                            slot["game_key"],

                        "slot_id":
                            slot["slot_id"],

                        "reason":
                            result.get(
                                "reason",
                                "UNKNOWN",
                            ),
                    }
                )

        except Exception as exc:

            failed += 1

            failures.append(
                {
                    "game_key":
                        slot["game_key"],

                    "slot_id":
                        slot["slot_id"],

                    "reason":
                        str(exc),
                }
            )


    print()
    print("======================================================")
    print(" BATCH PREP COMPLETE")
    print("======================================================")
    print("DATE:", scheduled_date)
    print("GAMES:", len(game_keys))
    print("SLOTS:", len(slots))
    print("SUCCESS:", success)
    print("ZERO-CALL / REUSED:", zero_call)
    print("FAILED:", failed)
    print("OPENAI CALLS:", api_calls)

    if failures:

        print()
        print("NEEDS ATTENTION:")

        for item in failures:

            print(
                f"- {item['game_key']} "
                f"{item['slot_id']}: "
                f"{item['reason']}"
            )

    print("======================================================")

    return {
        "scheduled_date":
            scheduled_date,

        "games":
            len(game_keys),

        "slots":
            len(slots),

        "success":
            success,

        "zero_call":
            zero_call,

        "failed":
            failed,

        "api_calls":
            api_calls,

        "failures":
            failures,
    }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        required=True,
        help="Scheduled date in YYYY-MM-DD format.",
    )

    args = parser.parse_args()

    prep_scheduled_games(
        args.date
    )


if __name__ == "__main__":

    main()
