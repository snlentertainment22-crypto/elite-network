from __future__ import annotations

import json
import re
from datetime import datetime, timezone

try:
    from .question_bank import connect, initialize_database
except ImportError:
    from question_bank import connect, initialize_database


# ============================================================
# ELITE NETWORK GAME BUILDER
# GAME-SPECIFIC REVIEW / APPROVAL
# Build 1A
#
# Does NOT alter the master Fact Checked question.
#
# Actions:
#   validate
#   approve
#   reset
# ============================================================


def load_json_object(raw_value) -> dict:

    if not raw_value:
        return {}

    try:
        value = json.loads(raw_value)

        if isinstance(value, dict):
            return value

    except Exception:
        pass

    return {}


def load_json_list(raw_value) -> list:

    if not raw_value:
        return []

    try:
        value = json.loads(raw_value)

        if isinstance(value, list):
            return value

    except Exception:
        pass

    return []


def clean_text(value) -> str:

    if value is None:
        return ""

    return str(value).strip()


def normalize_answer(value) -> str:

    text = clean_text(
        value
    ).lower()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return " ".join(
        text.split()
    )


def utc_now() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )


def get_current_content(
    row,
) -> tuple[dict, dict]:

    snapshot = load_json_object(
        row[
            "question_snapshot_json"
        ]
    )

    game_edit = snapshot.get(
        "game_edit",
        {},
    )

    if not isinstance(
        game_edit,
        dict,
    ):
        game_edit = {}

    category = clean_text(
        game_edit.get(
            "category",
            row["category"],
        )
    )

    question = clean_text(
        game_edit.get(
            "question",
            row["question"],
        )
    )

    correct_answer = clean_text(
        game_edit.get(
            "correct_answer",
            row["correct_answer"],
        )
    )

    wrong_answers = game_edit.get(
        "wrong_answers"
    )

    if not isinstance(
        wrong_answers,
        list,
    ):
        wrong_answers = load_json_list(
            row[
                "wrong_answers_json"
            ]
        )

    wrong_answers = [
        clean_text(answer)
        for answer in wrong_answers
        if clean_text(answer)
    ]

    roulette_hint = clean_text(
        game_edit.get(
            "roulette_hint",
            row["roulette_hint"],
        )
    )

    content = {
        "category":
            category,

        "question":
            question,

        "correct_answer":
            correct_answer,

        "wrong_answers":
            wrong_answers,

        "roulette_hint":
            roulette_hint,

        "question_type":
            row["question_type"],
    }

    return content, snapshot


def validate_for_game(
    content: dict,
) -> list[str]:

    issues = []

    category = content[
        "category"
    ]

    question = content[
        "question"
    ]

    correct_answer = content[
        "correct_answer"
    ]

    wrong_answers = content[
        "wrong_answers"
    ]

    question_type = content[
        "question_type"
    ]

    roulette_hint = content[
        "roulette_hint"
    ]

    # --------------------------------------------------------
    # REQUIRED CONTENT
    # --------------------------------------------------------

    if not category:
        issues.append(
            "Category is blank."
        )

    if not question:
        issues.append(
            "Question is blank."
        )

    if not correct_answer:
        issues.append(
            "Correct answer is blank."
        )

    # --------------------------------------------------------
    # DISTRACTORS
    #
    # We store 5 for reusable Network questions even though
    # Rounds 1-3 display only 3 at a time.
    # --------------------------------------------------------

    if (
        question_type
        !=
        "final_wager"
    ):

        if len(
            wrong_answers
        ) != 5:

            issues.append(
                "Question requires exactly "
                "5 prepared distractors."
            )

        normalized_wrong = [
            normalize_answer(
                answer
            )
            for answer in wrong_answers
        ]

        if (
            len(
                normalized_wrong
            )
            !=
            len(
                set(
                    normalized_wrong
                )
            )
        ):

            issues.append(
                "Duplicate distractors detected."
            )

        normalized_correct = (
            normalize_answer(
                correct_answer
            )
        )

        if (
            normalized_correct
            in
            normalized_wrong
        ):

            issues.append(
                "A distractor matches the "
                "correct answer."
            )

    # --------------------------------------------------------
    # ROULETTE
    # --------------------------------------------------------

    if (
        question_type
        ==
        "roulette"
    ):

        if not roulette_hint:

            issues.append(
                "Roulette hint is missing."
            )

    return issues


def review_game_builder_question(
    payload: dict,
) -> dict:

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "Invalid review payload."
        )

    initialize_database()

    game_key = clean_text(
        payload.get(
            "game_key"
        )
    )

    slot_id = clean_text(
        payload.get(
            "slot_id"
        )
    )

    action = clean_text(
        payload.get(
            "action",
            "validate",
        )
    ).lower()

    if action not in (
        "validate",
        "approve",
        "reset",
    ):

        raise ValueError(
            f"Invalid review action: "
            f"{action}"
        )

    if not game_key:
        raise ValueError(
            "Missing game_key."
        )

    if not slot_id:
        raise ValueError(
            "Missing slot_id."
        )

    conn = connect()

    try:

        row = conn.execute(
            """
            SELECT
                gq.id AS game_question_id,
                gq.question_id,
                gq.slot_id,
                gq.question_type,
                gq.question_snapshot_json,

                q.category,
                q.question,
                q.correct_answer,
                q.wrong_answers_json,
                q.roulette_hint

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
                f"{game_key} / {slot_id}."
            )

        content, snapshot = (
            get_current_content(
                row
            )
        )

        # ----------------------------------------------------
        # RESET
        # ----------------------------------------------------

        if action == "reset":

            snapshot[
                "game_review"
            ] = {
                "status":
                    "NEEDS_REVIEW",

                "updated_at":
                    utc_now(),
            }

            conn.execute(
                """
                UPDATE game_questions

                SET
                    question_snapshot_json = ?

                WHERE id = ?
                """,
                (
                    json.dumps(
                        snapshot,
                        ensure_ascii=False,
                    ),
                    row[
                        "game_question_id"
                    ],
                ),
            )

            conn.commit()

            return {
                "action":
                    "reset",

                "status":
                    "NEEDS_REVIEW",

                "game_key":
                    game_key,

                "slot_id":
                    slot_id,
            }

        # ----------------------------------------------------
        # VALIDATE CURRENT GAME COPY
        # ----------------------------------------------------

        issues = validate_for_game(
            content
        )

        can_approve = (
            len(issues)
            ==
            0
        )

        if action == "validate":

            return {
                "action":
                    "validate",

                "game_key":
                    game_key,

                "slot_id":
                    slot_id,

                "can_approve":
                    can_approve,

                "issues":
                    issues,

                "content":
                    content,
            }

        # ----------------------------------------------------
        # APPROVE
        # ----------------------------------------------------

        if not can_approve:

            return {
                "action":
                    "approve",

                "game_key":
                    game_key,

                "slot_id":
                    slot_id,

                "approved":
                    False,

                "status":
                    "NEEDS_REVIEW",

                "issues":
                    issues,
            }

        approved_at = utc_now()

        snapshot[
            "game_review"
        ] = {
            "status":
                "APPROVED",

            "approved_at":
                approved_at,

            "review_version":
                1,
        }

        conn.execute(
            """
            UPDATE game_questions

            SET
                question_snapshot_json = ?

            WHERE id = ?
            """,
            (
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                ),
                row[
                    "game_question_id"
                ],
            ),
        )

        conn.commit()

        return {
            "action":
                "approve",

            "game_key":
                game_key,

            "slot_id":
                slot_id,

            "approved":
                True,

            "status":
                "APPROVED",

            "approved_at":
                approved_at,

            "issues":
                [],

            "master_question_changed":
                False,
        }

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()