from __future__ import annotations

import json
import random
import re

try:
    from .question_bank import connect, initialize_database
    from .auto_block_selector import (
        get_pool_questions,
        select_balanced_questions,
    )
    from .save_daily_preview_games import (
        build_question_snapshot,
    )

except ImportError:
    from question_bank import connect, initialize_database
    from auto_block_selector import (
        get_pool_questions,
        select_balanced_questions,
    )
    from save_daily_preview_games import (
        build_question_snapshot,
    )


def _pool_name_for_game_type(
    game_type: str,
) -> str:

    value = str(
        game_type or ""
    ).upper()

    if "SPORTS" in value:
        return "sports"

    if "AFTER_DARK" in value:
        return "after_dark"

    return "regular"


def _date_token(
    game_key: str,
) -> str | None:

    match = re.search(
        r"\d{8}",
        str(game_key or ""),
    )

    if match:
        return match.group(0)

    return None


def _load_candidate_questions(
    conn,
) -> list[dict]:

    rows = conn.execute(
        """
        SELECT
            id,
            category,
            question,
            correct_answer,
            network_status,
            roulette_suitable
        FROM questions
        ORDER BY id
        """
    ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def _used_question_ids(
    conn,
    game_key: str,
) -> set[int]:

    day_token = _date_token(
        game_key
    )

    if day_token:

        rows = conn.execute(
            """
            SELECT DISTINCT
                gq.question_id

            FROM game_questions gq

            JOIN games g
              ON g.id = gq.game_id

            WHERE g.game_key LIKE ?
            """,
            (
                f"%{day_token}%",
            ),
        ).fetchall()

    else:

        rows = conn.execute(
            """
            SELECT DISTINCT
                gq.question_id

            FROM game_questions gq

            JOIN games g
              ON g.id = gq.game_id

            WHERE g.game_key = ?
            """,
            (
                game_key,
            ),
        ).fetchall()

    return {
        int(row["question_id"])
        for row in rows
    }


def replace_failed_slot(
    game_key: str,
    slot_id: str,
    excluded_ids: set[int] | None = None,
) -> dict:

    initialize_database()

    conn = connect()

    try:

        slot = conn.execute(
            """
            SELECT
                g.id AS game_id,
                g.game_type,
                gq.id AS game_question_id,
                gq.question_id AS old_question_id,
                gq.question_type

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

        if slot is None:
            raise RuntimeError(
                f"Could not find "
                f"{game_key} / {slot_id}"
            )

        slot = dict(
            slot
        )

        pool_name = (
            _pool_name_for_game_type(
                slot["game_type"]
            )
        )

        used_ids = (
            _used_question_ids(
                conn,
                game_key,
            )
        )

        if excluded_ids:

            used_ids.update(
                int(question_id)
                for question_id
                in excluded_ids
            )

        all_questions = (
            _load_candidate_questions(
                conn
            )
        )

        candidates = (
            get_pool_questions(
                all_questions,
                pool_name,
                excluded_ids=used_ids,
            )
        )

        # Roulette questions must remain
        # suitable for Roulette.
        if (
            str(
                slot["question_type"]
                or ""
            ).lower()
            ==
            "roulette"
        ):

            candidates = [
                question
                for question in candidates
                if int(
                    question.get(
                        "roulette_suitable",
                        1,
                    )
                    or 0
                )
                == 1
            ]

        if not candidates:
            raise RuntimeError(
                f"No unused replacement "
                f"questions available for "
                f"{game_key} / {slot_id} "
                f"in pool {pool_name}."
            )

        rng = random.Random(
            f"{game_key}|"
            f"{slot_id}|"
            f"{len(used_ids)}"
        )

        replacement = (
            select_balanced_questions(
                candidates,
                1,
                rng,
            )[0]
        )

        replacement_id = int(
            replacement["id"]
        )

        master = conn.execute(
            """
            SELECT *
            FROM questions
            WHERE id = ?
            """,
            (
                replacement_id,
            ),
        ).fetchone()

        if master is None:
            raise RuntimeError(
                f"Replacement question "
                f"{replacement_id} "
                f"was not found."
            )

        master = dict(
            master
        )

        snapshot = (
            build_question_snapshot(
                master
            )
        )

        conn.execute(
            """
            UPDATE game_questions

            SET
                question_id = ?,
                hint = '',
                choices_json = '[]',
                correct_index = NULL,
                question_snapshot_json = ?,
                presentation_overrides_json = '{}'

            WHERE id = ?
            """,
            (
                replacement_id,

                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                ),

                int(
                    slot[
                        "game_question_id"
                    ]
                ),
            ),
        )

        conn.execute(
            """
            UPDATE games
            SET updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                int(
                    slot["game_id"]
                ),
            ),
        )

        conn.commit()

        return {
            "game_key":
                game_key,

            "slot_id":
                slot_id,

            "pool":
                pool_name,

            "old_question_id":
                int(
                    slot[
                        "old_question_id"
                    ]
                ),

            "new_question_id":
                replacement_id,

            "question":
                master.get(
                    "question",
                    "",
                ),

            "correct_answer":
                master.get(
                    "correct_answer",
                    "",
                ),
        }

    finally:
        conn.close()
