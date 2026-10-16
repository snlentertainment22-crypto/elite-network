from __future__ import annotations

import argparse
import json

try:
    from .question_bank import connect, initialize_database

    from .ai_question_prep import (
        MAX_DISTRACTOR_ATTEMPTS,
        MAX_HINT_ATTEMPTS,
        generate_distractors,
        local_validate_distractors,
        judge_answer_set,
        generate_roulette_hint,
        local_validate_hint,
        judge_roulette_hint,
    )

except ImportError:
    from question_bank import connect, initialize_database

    from ai_question_prep import (
        MAX_DISTRACTOR_ATTEMPTS,
        MAX_HINT_ATTEMPTS,
        generate_distractors,
        local_validate_distractors,
        judge_answer_set,
        generate_roulette_hint,
        local_validate_hint,
        judge_roulette_hint,
    )


# ============================================================
# ELITE NETWORK GAME BUILDER
# REUSABLE AI PREP SERVICE
# Build 1A
#
# Purpose:
# Prepare ANY selected game slot.
#
# COST GUARDS:
# - Max 2 distractor attempts.
# - Max 2 hint attempts.
# - Reuse already-prepared material whenever possible.
# - Never endlessly retry.
#
# IMPORTANT:
# AI prep does NOT approve the question.
# Human review still happens in Game Builder.
# ============================================================


def parse_json_list(raw_value) -> list:

    if not raw_value:
        return []

    try:
        value = json.loads(raw_value)

        if isinstance(value, list):
            return value

    except Exception:
        pass

    return []


def parse_json_object(raw_value) -> dict:

    if not raw_value:
        return {}

    try:
        value = json.loads(raw_value)

        if isinstance(value, dict):
            return value

    except Exception:
        pass

    return {}


# ============================================================
# LOAD EXACT GAME SLOT
# ============================================================


def load_game_slot(
    game_key: str,
    slot_id: str,
) -> dict:

    initialize_database()

    conn = connect()

    try:

        row = conn.execute(
            """
            SELECT
                gq.id AS game_question_id,
                gq.slot_id,
                gq.question_type,
                gq.question_snapshot_json,

                q.id AS question_id,
                q.category,
                q.question,
                q.correct_answer,

                q.wrong_answers_json,
                q.network_status,

                q.roulette_hint,
                q.roulette_hint_status,
                q.roulette_suitable

            FROM game_questions gq

            JOIN games g
              ON g.id = gq.game_id

            JOIN questions q
              ON q.id = gq.question_id

            WHERE g.game_key = ?
              AND gq.slot_id = ?
            """,
            (
                game_key,
                slot_id,
            ),
        ).fetchone()

        if row is None:

            raise ValueError(
                f"Could not find "
                f"{game_key} / {slot_id}"
            )

        item = dict(row)

        item["wrong_answers"] = (
            parse_json_list(
                item.pop(
                    "wrong_answers_json",
                    None,
                )
            )
        )

        snapshot = parse_json_object(
            item.pop(
                "question_snapshot_json",
                None,
            )
        )

        # ----------------------------------------------------
        # SAFETY:
        # If Lucas has manually changed the actual question
        # wording/answer for THIS GAME, do not silently use
        # those edits to rewrite reusable master AI prep.
        #
        # We will later support game-copy AI prep separately.
        # ----------------------------------------------------

        game_edit = snapshot.get(
            "game_edit",
            {},
        )

        if not isinstance(
            game_edit,
            dict,
        ):
            game_edit = {}

        master_changed_for_game = False

        for field in (
            "category",
            "question",
            "correct_answer",
        ):

            game_value = game_edit.get(
                field
            )

            if (
                game_value is not None
                and
                str(game_value).strip()
                !=
                str(item[field]).strip()
            ):

                master_changed_for_game = True

                break

        item[
            "has_game_specific_content_edit"
        ] = master_changed_for_game

        return item

    finally:

        conn.close()


# ============================================================
# SAVE REUSABLE NETWORK PREP
# ============================================================


def save_distractors(
    question_id: int,
    wrong_answers: list[str],
) -> None:

    conn = connect()

    try:

        conn.execute(
            """
            UPDATE questions

            SET
                wrong_answers_json = ?,
                network_status = 'NEEDS_REVIEW',
                updated_at = datetime('now')

            WHERE id = ?
            """,
            (
                json.dumps(
                    wrong_answers,
                    ensure_ascii=False,
                ),
                question_id,
            ),
        )

        conn.commit()

    finally:

        conn.close()


def save_roulette_hint(
    question_id: int,
    hint: str,
) -> None:

    conn = connect()

    try:

        conn.execute(
            """
            UPDATE questions

            SET
                roulette_hint = ?,
                roulette_hint_status = 'NEEDS_REVIEW',
                roulette_suitable = 1,
                network_status = 'NEEDS_REVIEW',
                updated_at = datetime('now')

            WHERE id = ?
            """,
            (
                hint,
                question_id,
            ),
        )

        conn.commit()

    finally:

        conn.close()


def mark_manual_hint(
    question_id: int,
) -> None:

    conn = connect()

    try:

        conn.execute(
            """
            UPDATE questions

            SET
                roulette_hint_status =
                    'NEEDS_MANUAL_HINT',

                roulette_suitable = 0,

                network_status =
                    'NEEDS_REVIEW',

                updated_at =
                    datetime('now')

            WHERE id = ?
            """,
            (
                question_id,
            ),
        )

        conn.commit()

    finally:

        conn.close()


# ============================================================
# REUSE CHECKS
# ============================================================


def reusable_distractors(
    item: dict,
) -> bool:

    wrong_answers = item[
        "wrong_answers"
    ]

    if len(
        wrong_answers
    ) != 5:

        return False

    # Imported untouched questions start as NEEDS_CHOICES.
    # A prepared question moves beyond that status.
    if item[
        "network_status"
    ] == "NEEDS_CHOICES":

        return False

    issues = local_validate_distractors(
        item[
            "correct_answer"
        ],
        wrong_answers,
    )

    return not issues


def reusable_roulette_hint(
    item: dict,
) -> bool:

    hint = (
        item[
            "roulette_hint"
        ]
        or
        ""
    ).strip()

    if not hint:
        return False

    if not item[
        "roulette_suitable"
    ]:
        return False

    if item[
        "roulette_hint_status"
    ] in (
        "NEEDS_HINT",
        "NEEDS_MANUAL_HINT",
    ):

        return False

    issues = local_validate_hint(
        item[
            "correct_answer"
        ],
        hint,
    )

    return not issues


# ============================================================
# DISTRACTOR PREP
# ============================================================


def prepare_distractors(
    item: dict,
    counters: dict,
) -> list[str] | None:

    if reusable_distractors(
        item
    ):

        print()
        print(
            "DISTRACTORS ALREADY PREPARED"
        )

        print(
            "Reusing 5 saved distractors."
        )

        print(
            "OpenAI calls used: 0"
        )

        return item[
            "wrong_answers"
        ]

    previous_issues = []

    for attempt in range(
        1,
        MAX_DISTRACTOR_ATTEMPTS + 1,
    ):

        print()
        print(
            f"[DISTRACTORS] "
            f"Attempt {attempt} of "
            f"{MAX_DISTRACTOR_ATTEMPTS}"
        )

        counters[
            "api_calls"
        ] += 1

        wrong_answers = (
            generate_distractors(
                item,
                previous_issues,
            )
        )

        print()
        print(
            "GENERATED WRONG ANSWERS"
        )

        print(
            "-----------------------"
        )

        for number, answer in enumerate(
            wrong_answers,
            start=1,
        ):

            print(
                f"{number}. {answer}"
            )

        # ----------------------------------------------------
        # FREE LOCAL CHECK FIRST
        # ----------------------------------------------------

        local_issues = (
            local_validate_distractors(
                item[
                    "correct_answer"
                ],
                wrong_answers,
            )
        )

        print()
        print(
            "LOCAL VALIDATION"
        )

        print(
            "----------------"
        )

        if local_issues:

            print(
                "FAILED"
            )

            for issue in local_issues:

                print(
                    f"- {issue}"
                )

            previous_issues = (
                local_issues
            )

            # No paid validator call when local check fails.
            continue

        print(
            "PASSED"
        )

        # ----------------------------------------------------
        # AI VALIDATOR
        # ----------------------------------------------------

        print(
            "[AI VALIDATOR] "
            "Checking distractor safety..."
        )

        counters[
            "api_calls"
        ] += 1

        judge = judge_answer_set(
            item,
            wrong_answers,
        )

        passed = bool(
            judge.get(
                "pass",
                False,
            )
        )

        issues = judge.get(
            "issues",
            [],
        )

        print()
        print(
            "AI VALIDATION"
        )

        print(
            "-------------"
        )

        if passed:

            print(
                "PASSED"
            )

            save_distractors(
                item[
                    "question_id"
                ],
                wrong_answers,
            )

            print()
            print(
                "Validated distractors SAVED."
            )

            return wrong_answers

        print(
            "FAILED"
        )

        if issues:

            for issue in issues:

                print(
                    f"- {issue}"
                )

            previous_issues = (
                issues
            )

        else:

            previous_issues = [
                "AI validator rejected "
                "the answer set."
            ]

    print()
    print(
        "DISTRACTOR LIMIT REACHED."
    )

    print(
        "No additional AI attempts "
        "will be made."
    )

    return None


# ============================================================
# ROULETTE HINT PREP
# ============================================================


def prepare_hint(
    item: dict,
    wrong_answers: list[str],
    counters: dict,
) -> str | None:

    if reusable_roulette_hint(
        item
    ):

        print()
        print(
            "ROULETTE HINT ALREADY PREPARED"
        )

        print(
            item[
                "roulette_hint"
            ]
        )

        print(
            "OpenAI calls used: 0"
        )

        return item[
            "roulette_hint"
        ]

    previous_issues = []

    for attempt in range(
        1,
        MAX_HINT_ATTEMPTS + 1,
    ):

        print()
        print(
            f"[ROULETTE HINT] "
            f"Attempt {attempt} of "
            f"{MAX_HINT_ATTEMPTS}"
        )

        counters[
            "api_calls"
        ] += 1

        hint = generate_roulette_hint(
            item,
            previous_issues,
        )

        print()
        print(
            "GENERATED HINT"
        )

        print(
            "--------------"
        )

        print(
            hint
        )

        # ----------------------------------------------------
        # FREE LOCAL CHECK FIRST
        # ----------------------------------------------------

        local_issues = (
            local_validate_hint(
                item[
                    "correct_answer"
                ],
                hint,
            )
        )

        if local_issues:

            print()
            print(
                "LOCAL HINT VALIDATION: FAILED"
            )

            for issue in local_issues:

                print(
                    f"- {issue}"
                )

            previous_issues = (
                local_issues
            )

            continue

        print()
        print(
            "LOCAL HINT VALIDATION: PASSED"
        )

        # ----------------------------------------------------
        # AI VALIDATOR
        # ----------------------------------------------------

        counters[
            "api_calls"
        ] += 1

        judge = judge_roulette_hint(
            item,
            wrong_answers,
            hint,
        )

        passed = bool(
            judge.get(
                "pass",
                False,
            )
        )

        issues = judge.get(
            "issues",
            [],
        )

        if passed:

            print(
                "AI HINT VALIDATION: PASSED"
            )

            save_roulette_hint(
                item[
                    "question_id"
                ],
                hint,
            )

            print()
            print(
                "Validated Roulette hint SAVED."
            )

            return hint

        print(
            "AI HINT VALIDATION: FAILED"
        )

        if issues:

            for issue in issues:

                print(
                    f"- {issue}"
                )

            previous_issues = (
                issues
            )

        else:

            previous_issues = [
                "AI validator rejected "
                "the hint."
            ]

    mark_manual_hint(
        item[
            "question_id"
        ]
    )

    print()
    print(
        "ROULETTE HINT LIMIT REACHED."
    )

    print(
        "Marked NEEDS_MANUAL_HINT."
    )

    print(
        "No additional AI attempts "
        "will be made."
    )

    return None


# ============================================================
# PREPARE ONE GAME SLOT
# ============================================================


def prepare_game_slot(
    game_key: str,
    slot_id: str,
) -> dict:

    item = load_game_slot(
        game_key,
        slot_id,
    )

    counters = {
        "api_calls":
            0,
    }

    print()
    print(
        "======================================================"
    )

    print(
        " ELITE NETWORK — SELECTED SLOT AI PREP"
    )

    print(
        "======================================================"
    )

    print(
        f"Game:        {game_key}"
    )

    print(
        f"Slot:        {item['slot_id']}"
    )

    print(
        f"Type:        {item['question_type']}"
    )

    print(
        f"Question ID: {item['question_id']}"
    )

    print(
        f"Category:    {item['category']}"
    )

    print()
    print(
        item[
            "question"
        ]
    )

    print()
    print(
        "Correct:"
    )

    print(
        item[
            "correct_answer"
        ]
    )

    # --------------------------------------------------------
    # PROTECT GAME-SPECIFIC CONTENT EDITS
    # --------------------------------------------------------

    if item[
        "has_game_specific_content_edit"
    ]:

        print()
        print(
            "STOPPED:"
        )

        print(
            "This slot has game-specific "
            "question/category/correct-answer edits."
        )

        print(
            "Reusable question-bank AI prep "
            "will not overwrite or infer from them."
        )

        print()
        print(
            "OpenAI calls used: 0"
        )

        return {
            "ok":
                False,

            "reason":
                "GAME_SPECIFIC_CONTENT_EDIT",

            "api_calls":
                0,
        }

    # --------------------------------------------------------
    # FINAL WAGER
    # --------------------------------------------------------

    if item[
        "question_type"
    ] == "final_wager":

        print()
        print(
            "Final Wager does not require "
            "multiple-choice distractors."
        )

        print(
            "No AI preparation required."
        )

        print(
            "OpenAI calls used: 0"
        )

        return {
            "ok":
                True,

            "reused":
                True,

            "api_calls":
                0,
        }

    # --------------------------------------------------------
    # DISTRACTORS
    # --------------------------------------------------------

    wrong_answers = (
        prepare_distractors(
            item,
            counters,
        )
    )

    if wrong_answers is None:

        return {
            "ok":
                False,

            "reason":
                "DISTRACTOR_PREP_FAILED",

            "api_calls":
                counters[
                    "api_calls"
                ],
        }

    # --------------------------------------------------------
    # ROULETTE HINT
    # --------------------------------------------------------

    hint = None

    if item[
        "question_type"
    ] == "roulette":

        # Reload so a newly-saved state is available.
        item = load_game_slot(
            game_key,
            slot_id,
        )

        hint = prepare_hint(
            item,
            wrong_answers,
            counters,
        )

        if hint is None:

            return {
                "ok":
                    False,

                "reason":
                    "ROULETTE_HINT_FAILED",

                "distractors_saved":
                    True,

                "api_calls":
                    counters[
                        "api_calls"
                    ],
            }

    # --------------------------------------------------------
    # DONE
    # --------------------------------------------------------

    print()
    print(
        "======================================================"
    )

    print(
        "AI PREP COMPLETE"
    )

    print(
        f"OpenAI calls used: "
        f"{counters['api_calls']}"
    )

    print(
        "Human review still required."
    )

    print(
        "======================================================"
    )

    print()

    return {
        "ok":
            True,

        "slot_id":
            slot_id,

        "question_id":
            item[
                "question_id"
            ],

        "wrong_answers":
            wrong_answers,

        "roulette_hint":
            hint,

        "api_calls":
            counters[
                "api_calls"
            ],
    }


# ============================================================
# COMMAND LINE TEST
# ============================================================


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--game-key",
        default=
        "regular-blitz-test-2022-001",
    )

    parser.add_argument(
        "--slot",
        required=True,
    )

    args = parser.parse_args()

    prepare_game_slot(
        args.game_key,
        args.slot,
    )


if __name__ == "__main__":

    main()