from __future__ import annotations

import json

try:
    from .question_bank import connect, initialize_database
except ImportError:
    from question_bank import connect, initialize_database


# ============================================================
# ELITE NETWORK GAME BUILDER
# ADMIN SAVE BRIDGE
# Build 1B
#
# Save scopes:
#
# presentation
#   Saves game-specific visual overrides only.
#
# content
#   Saves game-specific wording / answers / hint into
#   game_questions.question_snapshot_json.
#
# IMPORTANT:
# Normal Game Builder edits DO NOT alter the master
# question-bank wording.
# ============================================================


ALLOWED_QUESTION_TYPES = {
    "normal",
    "roulette",
    "final_wager",
}


def clean_text(value) -> str:

    if value is None:
        return ""

    return str(value).strip()


def clean_optional_int(value):

    if value in (
        None,
        "",
    ):
        return None

    if isinstance(value, bool):
        raise ValueError(
            "Invalid numeric value."
        )

    try:
        return int(value)

    except Exception as exc:
        raise ValueError(
            f'Invalid numeric value: "{value}"'
        ) from exc


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


def normalize_wrong_answers(value) -> list[str]:

    if value is None:
        return []

    if not isinstance(value, list):
        raise ValueError(
            "wrong_answers must be a list."
        )

    cleaned = []

    for answer in value:

        answer = clean_text(answer)

        if answer:
            cleaned.append(answer)

    if len(cleaned) > 5:
        raise ValueError(
            "A question may have no more than "
            "5 saved distractors."
        )

    return cleaned


def validate_background_path(value) -> str:

    value = clean_text(value)

    if not value:
        return ""

    if not value.startswith("/assets/"):
        raise ValueError(
            "Background must use an /assets/ path."
        )

    if ".." in value:
        raise ValueError(
            "Invalid background path."
        )

    return value


def save_game_builder_question(
    payload: dict,
) -> dict:

    if not isinstance(payload, dict):
        raise ValueError(
            "Invalid Game Builder payload."
        )

    initialize_database()

    game_key = clean_text(
        payload.get("game_key")
    )

    slot_id = clean_text(
        payload.get("slot_id")
    )

    save_scope = clean_text(
        payload.get(
            "save_scope",
            "presentation",
        )
    ).lower()

    if save_scope not in (
        "presentation",
        "content",
    ):
        raise ValueError(
            f"Invalid save scope: {save_scope}"
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

                gq.question_type,
                gq.timer_seconds,
                gq.wager_seconds,
                gq.max_points,
                gq.min_points,

                gq.question_snapshot_json,
                gq.presentation_overrides_json,

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

        game_question_id = int(
            row["game_question_id"]
        )

        question_id = int(
            row["question_id"]
        )

        snapshot = load_json_object(
            row["question_snapshot_json"]
        )

        presentation = load_json_object(
            row["presentation_overrides_json"]
        )

        # ====================================================
        # PRESENTATION SAVE
        # ====================================================

        if save_scope == "presentation":

            background_image = (
                validate_background_path(
                    payload.get(
                        "background_image",
                        presentation.get(
                            "background_image",
                            "",
                        ),
                    )
                )
            )

            question_font = clean_optional_int(
                payload.get(
                    "question_font_override",
                    presentation.get(
                        "question_font_override"
                    ),
                )
            )

            answer_font = clean_optional_int(
                payload.get(
                    "answer_font_override",
                    presentation.get(
                        "answer_font_override"
                    ),
                )
            )

            if (
                question_font is not None
                and not (
                    18
                    <= question_font
                    <= 90
                )
            ):
                raise ValueError(
                    "Question font override must "
                    "be between 18 and 90."
                )

            if (
                answer_font is not None
                and not (
                    16
                    <= answer_font
                    <= 72
                )
            ):
                raise ValueError(
                    "Answer font override must "
                    "be between 16 and 72."
                )

            if background_image:
                presentation[
                    "background_image"
                ] = background_image
            else:
                presentation.pop(
                    "background_image",
                    None,
                )

            if question_font is None:
                presentation.pop(
                    "question_font_override",
                    None,
                )
            else:
                presentation[
                    "question_font_override"
                ] = question_font

            if answer_font is None:
                presentation.pop(
                    "answer_font_override",
                    None,
                )
            else:
                presentation[
                    "answer_font_override"
                ] = answer_font

            conn.execute(
                """
                UPDATE game_questions

                SET
                    presentation_overrides_json = ?

                WHERE id = ?
                """,
                (
                    json.dumps(
                        presentation,
                        ensure_ascii=False,
                    ),
                    game_question_id,
                ),
            )

            conn.commit()

            return {
                "ok": True,
                "save_scope":
                    "presentation",
                "game_key":
                    game_key,
                "slot_id":
                    slot_id,
                "question_id":
                    question_id,
                "game_question_id":
                    game_question_id,
                "background_image":
                    background_image,
                "question_font_override":
                    question_font,
                "answer_font_override":
                    answer_font,
            }

        # ====================================================
        # CONTENT SAVE
        # ====================================================

        game_edit = snapshot.get(
            "game_edit"
        )

        if not isinstance(
            game_edit,
            dict,
        ):
            game_edit = {}

        category = clean_text(
            payload.get(
                "category",
                game_edit.get(
                    "category",
                    row["category"],
                ),
            )
        )

        question = clean_text(
            payload.get(
                "question",
                game_edit.get(
                    "question",
                    row["question"],
                ),
            )
        )

        correct_answer = clean_text(
            payload.get(
                "correct_answer",
                game_edit.get(
                    "correct_answer",
                    row["correct_answer"],
                ),
            )
        )

        current_wrong_answers = (
            game_edit.get(
                "wrong_answers"
            )
        )

        if not isinstance(
            current_wrong_answers,
            list,
        ):
            current_wrong_answers = (
                load_json_list(
                    row[
                        "wrong_answers_json"
                    ]
                )
            )

        wrong_answers = (
            normalize_wrong_answers(
                payload.get(
                    "wrong_answers",
                    current_wrong_answers,
                )
            )
        )

        roulette_hint = clean_text(
            payload.get(
                "roulette_hint",
                game_edit.get(
                    "roulette_hint",
                    row["roulette_hint"],
                ),
            )
        )

        question_type = clean_text(
            payload.get(
                "question_type",
                row["question_type"],
            )
        )

        if (
            question_type
            not in
            ALLOWED_QUESTION_TYPES
        ):
            raise ValueError(
                f"Invalid question type: "
                f"{question_type}"
            )

        timer_seconds = (
            clean_optional_int(
                payload.get(
                    "timer_seconds",
                    row[
                        "timer_seconds"
                    ],
                )
            )
        )

        wager_seconds = (
            clean_optional_int(
                payload.get(
                    "wager_seconds",
                    row[
                        "wager_seconds"
                    ],
                )
            )
        )

        max_points = (
            clean_optional_int(
                payload.get(
                    "max_points",
                    row[
                        "max_points"
                    ],
                )
            )
        )

        min_points = (
            clean_optional_int(
                payload.get(
                    "min_points",
                    row[
                        "min_points"
                    ],
                )
            )
        )

        if not category:
            raise ValueError(
                "Category cannot be blank."
            )

        if not question:
            raise ValueError(
                "Question cannot be blank."
            )

        if not correct_answer:
            raise ValueError(
                "Correct answer cannot be blank."
            )

        game_edit.update(
            {
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

                "review_status":
                    "NEEDS_REVIEW",
            }
        )

        snapshot[
            "game_edit"
        ] = game_edit

        # Any content change invalidates the previous
        # game-specific approval.

        snapshot[
            "game_review"
        ] = {
            "status":
                "NEEDS_REVIEW",
        }

        conn.execute(
            """
            UPDATE game_questions

            SET
                question_type = ?,
                timer_seconds = ?,
                wager_seconds = ?,
                max_points = ?,
                min_points = ?,
                question_snapshot_json = ?

            WHERE id = ?
            """,
            (
                question_type,
                timer_seconds,
                wager_seconds,
                max_points,
                min_points,

                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                ),

                game_question_id,
            ),
        )

        conn.commit()

        return {
            "ok": True,
            "save_scope":
                "content",
            "game_key":
                game_key,
            "slot_id":
                slot_id,
            "question_id":
                question_id,
            "game_question_id":
                game_question_id,
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
                question_type,
            "timer_seconds":
                timer_seconds,
            "wager_seconds":
                wager_seconds,
            "max_points":
                max_points,
            "min_points":
                min_points,
            "review_status":
                "NEEDS_REVIEW",
            "master_question_changed":
                False,
        }

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()