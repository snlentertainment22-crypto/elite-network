from __future__ import annotations

from .question_bank import (
    connect,
    initialize_database,
)


def get_review_games() -> list[dict]:

    initialize_database()

    conn = connect()

    try:

        rows = conn.execute(
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

            WHERE scheduled_for IS NOT NULL

            ORDER BY
                scheduled_for ASC,
                id ASC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()
