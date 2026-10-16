from __future__ import annotations

import argparse
import json

try:
    from .question_bank import connect, initialize_database

    from .ai_prepare_service import (
        load_game_slot,
        reusable_distractors,
        reusable_roulette_hint,
        prepare_game_slot,
    )

    from .auto_repair import replace_failed_slot

except ImportError:
    from question_bank import connect, initialize_database

    from ai_prepare_service import (
        load_game_slot,
        reusable_distractors,
        reusable_roulette_hint,
        prepare_game_slot,
    )

    from auto_repair import replace_failed_slot


# ============================================================
# ELITE NETWORK
# FULL GAME AI PREP
# Build 1A
#
# Default = FREE PREFLIGHT ONLY.
#
# --run = actually prepare every slot that needs AI.
#
# Existing prepared material is reused.
# Game-specific wording is protected.
# ============================================================


def get_game_slots(game_key: str) -> list[str]:

    initialize_database()

    conn = connect()

    try:

        rows = conn.execute(
            """
            SELECT
                gq.slot_id

            FROM game_questions gq

            JOIN games g
              ON g.id = gq.game_id

            WHERE g.game_key = ?

            ORDER BY
                gq.display_order
            """,
            (game_key,),
        ).fetchall()

        return [
            row["slot_id"]
            for row in rows
        ]

    finally:

        conn.close()


def inspect_slot(
    game_key: str,
    slot_id: str,
) -> dict:

    item = load_game_slot(
        game_key,
        slot_id,
    )

    question_type = item[
        "question_type"
    ]

    # --------------------------------------------------------
    # FINAL WAGER
    # --------------------------------------------------------

    if question_type == "final_wager":

        return {
            "slot_id": slot_id,
            "status": "NO_AI_NEEDED",
            "expected_calls": 0,
            "max_calls": 0,
        }

    distractors_ready = (
        reusable_distractors(
            item
        )
    )

    hint_ready = True

    if question_type == "roulette":

        hint_ready = (
            reusable_roulette_hint(
                item
            )
        )

    # --------------------------------------------------------
    # GAME-SPECIFIC WORDING
    #
    # Do NOT use reusable master AI generation against
    # manually changed question wording.
    # --------------------------------------------------------

    if item[
        "has_game_specific_content_edit"
    ]:

        if (
            distractors_ready
            and
            hint_ready
        ):

            return {
                "slot_id": slot_id,
                "status":
                    "GAME_EDIT_READY_FOR_REVIEW",
                "expected_calls": 0,
                "max_calls": 0,
            }

        return {
            "slot_id": slot_id,
            "status":
                "GAME_EDIT_NEEDS_MANUAL_PREP",
            "expected_calls": 0,
            "max_calls": 0,
        }

    # --------------------------------------------------------
    # EVERYTHING ALREADY READY
    # --------------------------------------------------------

    if (
        distractors_ready
        and
        hint_ready
    ):

        return {
            "slot_id": slot_id,
            "status": "ALREADY_PREPARED",
            "expected_calls": 0,
            "max_calls": 0,
        }

    # --------------------------------------------------------
    # CALCULATE EXPECTED / HARD MAX CALLS
    #
    # Normal successful missing component:
    # generation + validator = 2 calls.
    #
    # Hard ceiling:
    # 2 attempts × generation/validator = 4 calls.
    # --------------------------------------------------------

    expected_calls = 0
    max_calls = 0

    missing = []

    if not distractors_ready:

        missing.append(
            "DISTRACTORS"
        )

        expected_calls += 2
        max_calls += 4

    if (
        question_type == "roulette"
        and
        not hint_ready
    ):

        missing.append(
            "ROULETTE_HINT"
        )

        expected_calls += 2
        max_calls += 4

    return {
        "slot_id":
            slot_id,

        "status":
            "NEEDS_"
            +
            "_AND_".join(
                missing
            ),

        "expected_calls":
            expected_calls,

        "max_calls":
            max_calls,
    }


def reset_game_review(
    game_key: str,
    slot_id: str,
) -> None:

    conn = connect()

    try:

        row = conn.execute(
            """
            SELECT
                gq.id,
                gq.question_snapshot_json

            FROM game_questions gq

            JOIN games g
              ON g.id = gq.game_id

            WHERE g.game_key = ?
              AND gq.slot_id = ?
            """,
            (
                game_key,
                slot_id,
            ),
        ).fetchone()

        if row is None:
            return

        try:

            snapshot = json.loads(
                row[
                    "question_snapshot_json"
                ]
                or
                "{}"
            )

        except Exception:

            snapshot = {}

        if not isinstance(
            snapshot,
            dict,
        ):
            snapshot = {}

        snapshot[
            "game_review"
        ] = {
            "status":
                "NEEDS_REVIEW"
        }

        conn.execute(
            """
            UPDATE game_questions

            SET question_snapshot_json = ?

            WHERE id = ?
            """,
            (
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                ),
                row["id"],
            ),
        )

        conn.commit()

    finally:

        conn.close()


def prepare_full_game(
    game_key: str,
    execute: bool = False,
) -> None:

    slots = get_game_slots(
        game_key
    )

    if not slots:

        raise ValueError(
            f"No game slots found for {game_key}"
        )

    print()
    print(
        "======================================================"
    )

    print(
        " ELITE NETWORK — FULL GAME AI PREP"
    )

    print(
        "======================================================"
    )

    print(
        f"Game: {game_key}"
    )

    print(
        f"Slots: {len(slots)}"
    )

    print()

    plan = []

    expected_total = 0
    max_total = 0

    for slot_id in slots:

        info = inspect_slot(
            game_key,
            slot_id,
        )

        plan.append(
            info
        )

        expected_total += (
            info[
                "expected_calls"
            ]
        )

        max_total += (
            info[
                "max_calls"
            ]
        )

        print(
            f"{slot_id:5}  "
            f"{info['status']}"
        )

    print()
    print(
        "------------------------------"
    )

    print(
        "FREE PREFLIGHT SUMMARY"
    )

    print(
        "------------------------------"
    )

    print(
        f"Expected API calls: "
        f"{expected_total}"
    )

    print(
        f"Absolute hard max:  "
        f"{max_total}"
    )

    if not execute:

        print()
        print(
            "NO AI CALLS WERE MADE."
        )

        print()
        print(
            "Run again with --run "
            "to prepare the full game."
        )

        print()

        return

    # ========================================================
    # EXECUTE FULL GAME
    # ========================================================

    print()
    print(
        "======================================================"
    )

    print(
        " RUNNING FULL GAME PREP"
    )

    print(
        "======================================================"
    )

    actual_calls = 0

    prepared = 0
    reused = 0
    manual = 0
    failed = 0

    for info in plan:

        slot_id = info[
            "slot_id"
        ]

        status = info[
            "status"
        ]

        print()
        print(
            "------------------------------------------------------"
        )

        print(
            f" SLOT {slot_id}"
        )

        print(
            "------------------------------------------------------"
        )

        if status in (
            "ALREADY_PREPARED",
            "NO_AI_NEEDED",
            "GAME_EDIT_READY_FOR_REVIEW",
        ):

            print(
                status
            )

            print(
                "API calls: 0"
            )

            reused += 1

            continue

        if (
            status
            ==
            "GAME_EDIT_NEEDS_MANUAL_PREP"
        ):

            print(
                "Manual prep required because "
                "this slot has game-specific wording."
            )

            print(
                "API calls: 0"
            )

            manual += 1

            continue

        result = prepare_game_slot(
            game_key,
            slot_id,
        )

        calls = int(
            result.get(
                "api_calls",
                0,
            )
            or
            0
        )

        actual_calls += calls

        # If AI touched this slot,
        # require human approval again.
        if calls > 0:

            reset_game_review(
                game_key,
                slot_id,
            )

        if result.get(
            "ok"
        ):

            prepared += 1

        else:

            print()
            print(
                "AI PREP FAILED - AUTO REPLACING SLOT"
            )

            print(
                result.get(
                    "reason",
                    "UNKNOWN",
                )
            )

            failed_question_ids = set()

            retry_result = result

            max_replacement_attempts = 5

            replacement_attempt = 0

            while (
                not retry_result.get("ok")
                and
                replacement_attempt
                < max_replacement_attempts
            ):

                replacement_attempt += 1

                try:

                    replacement = replace_failed_slot(
                        game_key,
                        slot_id,
                        excluded_ids=failed_question_ids,
                    )

                except Exception as exc:

                    print()
                    print(
                        "AUTO REPLACEMENT ERROR:"
                    )
                    print(exc)

                    break

                failed_question_ids.add(
                    int(
                        replacement[
                            "old_question_id"
                        ]
                    )
                )

                print()
                print(
                    f"AUTO REPLACEMENT ATTEMPT "
                    f"{replacement_attempt} / "
                    f"{max_replacement_attempts}"
                )

                print(
                    f"Replaced question "
                    f"{replacement['old_question_id']} "
                    f"with "
                    f"{replacement['new_question_id']}"
                )

                print(
                    replacement.get(
                        "question",
                        "",
                    )
                )

                retry_result = prepare_game_slot(
                    game_key,
                    slot_id,
                )

                retry_calls = int(
                    retry_result.get(
                        "api_calls",
                        0,
                    )
                    or
                    0
                )

                actual_calls += retry_calls

                if retry_calls > 0:

                    reset_game_review(
                        game_key,
                        slot_id,
                    )

                if retry_result.get("ok"):

                    prepared += 1

                    print()
                    print(
                        "AUTO REPLACEMENT PREP PASSED"
                    )

                    break

                print()
                print(
                    "REPLACEMENT FAILED:"
                )

                print(
                    retry_result.get(
                        "reason",
                        "UNKNOWN",
                    )
                )

            if not retry_result.get("ok"):

                failed += 1

                print()
                print(
                    "AUTO REPAIR GAVE UP AFTER "
                    f"{replacement_attempt} "
                    "REPLACEMENT ATTEMPTS"
                )

    print()
    print(
        "======================================================"
    )

    print(
        " FULL GAME PREP COMPLETE"
    )

    print(
        "======================================================"
    )

    print(
        f"Prepared now:       {prepared}"
    )

    print(
        f"Already ready:      {reused}"
    )

    print(
        f"Manual attention:   {manual}"
    )

    print(
        f"Failed prep:        {failed}"
    )

    print(
        f"Actual API calls:   {actual_calls}"
    )

    print()
    print(
        "Game is ready for manual review "
        "except any slots listed above "
        "for manual attention."
    )

    print()


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--game-key",
        default=
            "regular-blitz-test-2022-001",
    )

    parser.add_argument(
        "--run",
        action="store_true",
        help=
            "Actually run AI preparation. "
            "Without this flag the command "
            "is a free preflight only.",
    )

    args = parser.parse_args()

    prepare_full_game(
        args.game_key,
        execute=args.run,
    )


if __name__ == "__main__":

    main()