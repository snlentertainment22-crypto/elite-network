from __future__ import annotations

import json

try:
    from .question_bank import connect, initialize_database
except ImportError:
    from question_bank import connect, initialize_database


# ============================================================
# ELITE NETWORK GAME BUILDER
# ADMIN DATA BRIDGE
# Build 1C
#
# Reads the saved game from SQLite for the Admin/Game Builder.
#
# Supports:
# - master question data
# - game-specific content edits
# - game-specific presentation overrides
#
# READ ONLY:
# - No AI calls
# - No database changes
# ============================================================


DEFAULT_GAME_KEY = "regular-blitz-test-2022-001"


# ============================================================
# JSON HELPERS
# ============================================================


def parse_json_list(raw_value):

    if not raw_value:
        return []

    try:

        value = json.loads(raw_value)

        if isinstance(value, list):
            return value

    except Exception:
        pass

    return []


def parse_json_object(raw_value):

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
# LOAD GAME BUILDER DATA
# ============================================================


def get_game_builder_payload(
    game_key: str = DEFAULT_GAME_KEY,
) -> dict:

    initialize_database()

    conn = connect()

    try:

        # ----------------------------------------------------
        # GAME HEADER
        # ----------------------------------------------------

        game = conn.execute(
            """
            SELECT
                id,
                game_key,
                title,
                game_type,
                scheduled_for,
                status,
                created_at,
                updated_at

            FROM games

            WHERE game_key = ?
            """,
            (
                game_key,
            ),
        ).fetchone()

        if game is None:

            raise ValueError(
                f'Game not found: "{game_key}"'
            )

        # ----------------------------------------------------
        # QUESTIONS
        # ----------------------------------------------------

        rows = conn.execute(
            """
            SELECT

                gq.id AS game_question_id,
                gq.game_id,
                gq.question_id,

                gq.slot_id,
                gq.round_number,
                gq.question_number,
                gq.display_order,

                gq.question_type,
                gq.scoring_type,

                gq.timer_seconds,
                gq.wager_seconds,

                gq.max_points,
                gq.min_points,

                gq.hint,

                gq.choices_json,
                gq.correct_index,

                gq.question_snapshot_json,
                gq.presentation_overrides_json,

                q.source_system,
                q.source_key,
                q.source_row,

                q.category,
                q.question,
                q.correct_answer,

                q.fact_check_date,
                q.source_year,

                q.wrong_answers_json,

                q.difficulty_score,
                q.difficulty_label,
                q.suggested_round,

                q.freshness_status,
                q.network_status,

                q.review_note,
                q.host_notes,

                q.roulette_hint,
                q.roulette_hint_status,
                q.roulette_suitable,

                q.question_font_override,
                q.answer_font_override,

                q.last_network_used,
                q.times_network_used

            FROM game_questions gq

            JOIN questions q
              ON q.id = gq.question_id

            WHERE gq.game_id = ?

            ORDER BY
                gq.display_order ASC,
                gq.round_number ASC,
                gq.question_number ASC
            """,
            (
                game["id"],
            ),
        ).fetchall()

        questions = []

        for row in rows:

            item = dict(row)

            # ----------------------------------------------
            # PARSE STORED JSON
            # ----------------------------------------------

            item["wrong_answers"] = (
                parse_json_list(
                    item.pop(
                        "wrong_answers_json",
                        None,
                    )
                )
            )

            item["saved_choices"] = (
                parse_json_list(
                    item.pop(
                        "choices_json",
                        None,
                    )
                )
            )

            item["question_snapshot"] = (
                parse_json_object(
                    item.pop(
                        "question_snapshot_json",
                        None,
                    )
                )
            )

            item["presentation_overrides"] = (
                parse_json_object(
                    item.pop(
                        "presentation_overrides_json",
                        None,
                    )
                )
            )

            # ----------------------------------------------
            # APPLY GAME-SPECIFIC CONTENT EDITS
            #
            # These override what the Admin/Game Builder sees,
            # but do NOT overwrite the master question.
            # ----------------------------------------------

            game_edit = (
                item[
                    "question_snapshot"
                ].get(
                    "game_edit",
                    {},
                )
            )

            if isinstance(
                game_edit,
                dict,
            ):

                if game_edit.get(
                    "category"
                ):

                    item["category"] = (
                        game_edit[
                            "category"
                        ]
                    )

                if game_edit.get(
                    "question"
                ):

                    item["question"] = (
                        game_edit[
                            "question"
                        ]
                    )

                if game_edit.get(
                    "correct_answer"
                ):

                    item[
                        "correct_answer"
                    ] = game_edit[
                        "correct_answer"
                    ]

                if isinstance(
                    game_edit.get(
                        "wrong_answers"
                    ),
                    list,
                ):

                    item[
                        "wrong_answers"
                    ] = game_edit[
                        "wrong_answers"
                    ]

                if (
                    "roulette_hint"
                    in game_edit
                ):

                    item[
                        "roulette_hint"
                    ] = game_edit[
                        "roulette_hint"
                    ]

                item[
                    "game_edit_status"
                ] = game_edit.get(
                    "review_status",
                    "",
                )

            else:

                item[
                    "game_edit_status"
                ] = ""

            # ----------------------------------------------
            # GAME-SPECIFIC REVIEW STATUS
            # ----------------------------------------------

            game_review = (
                item[
                    "question_snapshot"
                ].get(
                    "game_review",
                    {},
                )
            )

            if not isinstance(
                game_review,
                dict,
            ):
                game_review = {}

            item[
                "game_review_status"
            ] = game_review.get(
                "status",
                "NEEDS_REVIEW",
            )

            item[
                "game_review_approved_at"
            ] = game_review.get(
                "approved_at",
                "",
            )

            # ----------------------------------------------
            # APPLY GAME-SPECIFIC PRESENTATION OVERRIDES
            # ----------------------------------------------

            presentation = (
                item[
                    "presentation_overrides"
                ]
            )

            if isinstance(
                presentation,
                dict,
            ):

                if (
                    "question_font_override"
                    in presentation
                ):

                    item[
                        "question_font_override"
                    ] = presentation[
                        "question_font_override"
                    ]

                if (
                    "answer_font_override"
                    in presentation
                ):

                    item[
                        "answer_font_override"
                    ] = presentation[
                        "answer_font_override"
                    ]

            # ----------------------------------------------
            # ADMIN WARNING FLAGS
            # ----------------------------------------------

            warnings = []

            if (
                item["question_type"]
                !=
                "final_wager"
            ):

                if len(
                    item["wrong_answers"]
                ) < 5:

                    warnings.append(
                        "NEEDS_DISTRACTORS"
                    )

            if (
                item["question_type"]
                ==
                "roulette"
            ):

                if not item[
                    "roulette_hint"
                ]:

                    warnings.append(
                        "NEEDS_ROULETTE_HINT"
                    )

                if not item[
                    "roulette_suitable"
                ]:

                    warnings.append(
                        "NOT_ROULETTE_READY"
                    )

                if item[
                    "roulette_hint_status"
                ] not in (
                    "READY",
                    "APPROVED",
                ):

                    warnings.append(
                        "HINT_REVIEW"
                    )

            if item[
                "freshness_status"
            ] not in (
                "READY",
                "APPROVED",
                "CURRENT",
            ):

                warnings.append(
                    "FRESHNESS_REVIEW"
                )

            if item[
                "network_status"
            ] not in (
                "READY",
                "APPROVED",
                "NETWORK_READY",
            ):

                warnings.append(
                    "NETWORK_REVIEW"
                )

            if item[
                "game_edit_status"
            ] == "NEEDS_REVIEW":

                warnings.append(
                    "GAME_EDIT_REVIEW"
                )

            item[
                "warnings"
            ] = warnings

            item[
                "admin_ready"
            ] = (
                len(warnings)
                ==
                0
            )

            questions.append(
                item
            )

        # ----------------------------------------------------
        # FINAL PAYLOAD
        # ----------------------------------------------------

        payload = dict(
            game
        )

        payload[
            "question_count"
        ] = len(
            questions
        )

        payload[
            "questions"
        ] = questions

        return payload

    finally:

        conn.close()


# ============================================================
# TERMINAL TEST
# ============================================================


def print_game_summary(
    game_key: str = DEFAULT_GAME_KEY,
) -> None:

    payload = get_game_builder_payload(
        game_key
    )

    print()

    print(
        "======================================================"
    )

    print(
        " ELITE NETWORK — ADMIN GAME DATA"
    )

    print(
        "======================================================"
    )

    print(
        f"Game:      {payload['title']}"
    )

    print(
        f"Key:       {payload['game_key']}"
    )

    print(
        f"Type:      {payload['game_type']}"
    )

    print(
        f"Status:    {payload['status']}"
    )

    print(
        f"Questions: {payload['question_count']}"
    )

    print()

    print(
        "------------------------------------------------------"
    )

    for item in payload[
        "questions"
    ]:

        print()

        print(
            f"{item['slot_id']} "
            f"| "
            f"{item['question_type']} "
            f"| "
            f"{item['category']}"
        )

        print(
            item[
                "question"
            ]
        )

        print(
            f"Correct: "
            f"{item['correct_answer']}"
        )

        print(
            f"Wrong answers saved: "
            f"{len(item['wrong_answers'])}"
        )

        if item[
            "wrong_answers"
        ]:

            for (
                number,
                answer,
            ) in enumerate(
                item[
                    "wrong_answers"
                ],
                start=1,
            ):

                print(
                    f"  "
                    f"{number}. "
                    f"{answer}"
                )

        if (
            item[
                "question_type"
            ]
            ==
            "roulette"
        ):

            print(
                f"Roulette hint: "
                f"{item['roulette_hint'] or '[NONE]'}"
            )

            print(
                f"Hint status: "
                f"{item['roulette_hint_status']}"
            )

            print(
                f"Roulette suitable: "
                f"{item['roulette_suitable']}"
            )

        if item[
            "warnings"
        ]:

            print(
                "Admin status: ⚠ "
                +
                ", ".join(
                    item[
                        "warnings"
                    ]
                )
            )

        else:

            print(
                "Admin status: ✓ READY"
            )

        print(
            "------------------------------------------------------"
        )

    print()

    print(
        "======================================================"
    )

    print(
        "READ ONLY — NOTHING WAS CHANGED."
    )

    print(
        "======================================================"
    )

    print()


if __name__ == "__main__":

    print_game_summary()