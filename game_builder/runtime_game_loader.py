from __future__ import annotations

import json
import random
import re
from pathlib import Path

try:
    from .question_bank import connect, initialize_database
except ImportError:
    from question_bank import connect, initialize_database


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
LEGACY_GAME_FILE = PROJECT_DIR / "game_data.json"


def _json_dict(value):
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _json_list(value):
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _clean_answer(value):
    text = str(value or "").strip()

    # Remove old imported choice prefixes such as:
    # F) Vijay Singh
    # C. Cincinnati Reds
    text = re.sub(
        r"^[A-Fa-f]\s*[\)\.\-:]\s*",
        "",
        text,
    )

    return text.strip()


def _load_runtime_settings():
    try:
        with LEGACY_GAME_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        return dict(
            data.get(
                "settings",
                {},
            )
        )

    except Exception:
        return {}


def _build_choices(
    game_key,
    slot_id,
    correct_answer,
    wrong_answers,
    choice_count,
):
    correct = _clean_answer(
        correct_answer
    )

    cleaned_wrong = []
    seen = {
        correct.casefold()
    }

    for answer in wrong_answers:
        answer = _clean_answer(
            answer
        )

        if not answer:
            continue

        key = answer.casefold()

        if key in seen:
            continue

        seen.add(
            key
        )

        cleaned_wrong.append(
            answer
        )

    wrong_needed = (
        choice_count - 1
    )

    if len(cleaned_wrong) < wrong_needed:
        raise RuntimeError(
            f"{game_key} / {slot_id} "
            f"needs {wrong_needed} wrong answers "
            f"but only has {len(cleaned_wrong)}."
        )

    rng = random.Random(
        f"{game_key}|{slot_id}|choices"
    )

    wrong_pool = list(
        cleaned_wrong
    )

    rng.shuffle(
        wrong_pool
    )

    choices = (
        wrong_pool[:wrong_needed]
        +
        [correct]
    )

    rng.shuffle(
        choices
    )

    correct_index = choices.index(
        correct
    )

    return (
        choices,
        correct_index,
    )


def resolve_scheduled_game_key(
    scheduled_for: str,
    game_type: str,
):
    """
    Resolve the saved Auto Builder game assigned
    to an exact Network date/time slot.

    Returns None when no matching game exists.
    """

    initialize_database()

    conn = connect()

    try:
        row = conn.execute(
            """
            SELECT
                game_key,
                status
            FROM games
            WHERE scheduled_for = ?
              AND game_type = ?
            ORDER BY
                CASE status
                    WHEN 'PUBLISHED' THEN 0
                    WHEN 'READY' THEN 1
                    WHEN 'DRAFT' THEN 2
                    ELSE 3
                END,
                id DESC
            LIMIT 1
            """,
            (
                scheduled_for,
                game_type,
            ),
        ).fetchone()

        if row is None:
            return None

        return str(
            row["game_key"]
        ).strip() or None

    finally:
        conn.close()


def load_runtime_game(
    game_key: str,
) -> dict:

    initialize_database()

    conn = connect()

    try:
        game = conn.execute(
            """
            SELECT *
            FROM games
            WHERE game_key = ?
            """,
            (
                game_key,
            ),
        ).fetchone()

        if game is None:
            raise RuntimeError(
                f"Saved game not found: {game_key}"
            )

        game = dict(
            game
        )

        rows = conn.execute(
            """
            SELECT
                gq.*,

                q.category AS master_category,
                q.question AS master_question,
                q.correct_answer AS master_correct_answer,
                q.wrong_answers_json,

                q.roulette_hint,
                q.audio_mp3,
                q.question_image,
                q.reveal_image,
                q.video_clip,
                q.voiceover_audio,

                q.question_font_override,
                q.answer_font_override

            FROM game_questions gq

            JOIN questions q
              ON q.id = gq.question_id

            WHERE gq.game_id = ?

            ORDER BY
                gq.display_order
            """,
            (
                int(
                    game["id"]
                ),
            ),
        ).fetchall()

        if len(rows) != 24:
            raise RuntimeError(
                f"{game_key} has "
                f"{len(rows)} questions; expected 24."
            )

        runtime_questions = []

        for raw in rows:
            row = dict(
                raw
            )

            snapshot = _json_dict(
                row[
                    "question_snapshot_json"
                ]
            )

            overrides = _json_dict(
                row[
                    "presentation_overrides_json"
                ]
            )

            slot_id = str(
                row["slot_id"]
            )

            round_number = int(
                row["round_number"]
            )

            question_number = int(
                row["question_number"]
            )

            question_type = str(
                row["question_type"]
                or "normal"
            ).lower()

            scoring_type = str(
                row["scoring_type"]
                or "fastest"
            ).lower()

            category = str(
                snapshot.get(
                    "category"
                )
                or
                row["master_category"]
                or
                ""
            ).strip()

            question_text = str(
                snapshot.get(
                    "question"
                )
                or
                row["master_question"]
                or
                ""
            ).strip()

            correct_answer = _clean_answer(
                snapshot.get(
                    "correct_answer"
                )
                or
                row[
                    "master_correct_answer"
                ]
            )

            if not question_text:
                raise RuntimeError(
                    f"{game_key} / {slot_id} "
                    f"has no question text."
                )

            if not correct_answer:
                raise RuntimeError(
                    f"{game_key} / {slot_id} "
                    f"has no correct answer."
                )

            runtime = {
                "id":
                    slot_id,

                "round":
                    round_number,

                "question_number":
                    question_number,

                "type":
                    question_type,

                "scoring_type":
                    scoring_type,

                "category":
                    category,

                "question":
                    question_text,

                "timer_seconds":
                    int(
                        row[
                            "timer_seconds"
                        ]
                        or
                        45
                    ),

                "timer_audio":
                    str(
                        row["audio_mp3"]
                        or
                        ""
                    ),

                "voiceover_audio":
                    str(
                        row[
                            "voiceover_audio"
                        ]
                        or
                        ""
                    ),

                "question_image":
                    str(
                        row[
                            "question_image"
                        ]
                        or
                        ""
                    ),

                "reveal_image":
                    str(
                        row[
                            "reveal_image"
                        ]
                        or
                        ""
                    ),

                "video_clip":
                    str(
                        row[
                            "video_clip"
                        ]
                        or
                        ""
                    ),
            }

            if (
                row[
                    "question_font_override"
                ]
                is not None
            ):
                runtime[
                    "question_font_override"
                ] = int(
                    row[
                        "question_font_override"
                    ]
                )

            if (
                row[
                    "answer_font_override"
                ]
                is not None
            ):
                runtime[
                    "answer_font_override"
                ] = int(
                    row[
                        "answer_font_override"
                    ]
                )

            if overrides:
                runtime[
                    "presentation_overrides"
                ] = overrides

            # -----------------------------------------------
            # FINAL WAGER
            # -----------------------------------------------

            if (
                question_type
                ==
                "final_wager"
            ):

                runtime[
                    "choices"
                ] = []

                runtime[
                    "answer_display"
                ] = correct_answer

                runtime[
                    "accepted_answers"
                ] = [
                    correct_answer
                ]

                runtime_questions.append(
                    runtime
                )

                continue

            # -----------------------------------------------
            # MULTIPLE CHOICE / ROULETTE
            #
            # R1-R3 = 4 choices
            # R4 = 6 choices
            # -----------------------------------------------

            choice_count = (
                6
                if round_number == 4
                else
                4
            )

            wrong_answers = _json_list(
                row[
                    "wrong_answers_json"
                ]
            )

            choices, correct_index = (
                _build_choices(
                    game_key,
                    slot_id,
                    correct_answer,
                    wrong_answers,
                    choice_count,
                )
            )

            runtime[
                "choices"
            ] = choices

            runtime[
                "correct_index"
            ] = correct_index

            if row["max_points"] is not None:
                runtime[
                    "max_points"
                ] = int(
                    row[
                        "max_points"
                    ]
                )

            if row["min_points"] is not None:
                runtime[
                    "min_points"
                ] = int(
                    row[
                        "min_points"
                    ]
                )

            # -----------------------------------------------
            # ROULETTE
            # -----------------------------------------------

            if (
                question_type
                ==
                "roulette"
            ):

                hint = str(
                    row["hint"]
                    or
                    row[
                        "roulette_hint"
                    ]
                    or
                    ""
                ).strip()

                if not hint:
                    raise RuntimeError(
                        f"{game_key} / {slot_id} "
                        f"is Roulette but has no hint."
                    )

                runtime[
                    "hint"
                ] = hint

                runtime[
                    "wager_seconds"
                ] = int(
                    row[
                        "wager_seconds"
                    ]
                    or
                    30
                )

            runtime_questions.append(
                runtime
            )

        return {
            "game_key":
                game_key,

            "game_title":
                game["title"],

            "game_type":
                game["game_type"],

            "questions":
                runtime_questions,

            "settings":
                _load_runtime_settings(),
        }

    finally:
        conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--game-key",
        required=True,
    )

    args = parser.parse_args()

    data = load_runtime_game(
        args.game_key
    )

    print(
        f"TITLE: {data['game_title']}"
    )

    print(
        f"TYPE: {data['game_type']}"
    )

    print(
        f"QUESTIONS: {len(data['questions'])}"
    )

    print()

    for q in (
        data["questions"][0],
        data["questions"][5],
        data["questions"][23],
    ):
        print(
            json.dumps(
                q,
                indent=2,
                ensure_ascii=False,
            )
        )
        print()


if __name__ == "__main__":
    main()
