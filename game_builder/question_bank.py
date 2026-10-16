from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# ELITE NETWORK GAME BUILDER
# Network Question Bank
# Build 1B
# ============================================================

import os

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = Path(
    os.environ.get(
        "ELITE_NETWORK_DB_PATH",
        str(BASE_DIR / "question_bank.sqlite3"),
    )
)

SCHEMA_VERSION = "1B"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> set[str]:

    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {
        row["name"]
        for row in rows
    }


def ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:

    columns = get_columns(
        conn,
        table_name,
    )

    if column_name in columns:
        return

    conn.execute(
        f"""
        ALTER TABLE {table_name}
        ADD COLUMN {column_name}
        {column_definition}
        """
    )

    print(
        f"Added database field: "
        f"{table_name}.{column_name}"
    )


def initialize_database() -> None:

    conn = connect()

    try:

        # ====================================================
        # META
        # ====================================================

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        # ====================================================
        # NETWORK QUESTION BANK
        # ====================================================

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source_system TEXT NOT NULL
                    DEFAULT 'elite_fact_check',

                source_key TEXT NOT NULL UNIQUE,
                source_row INTEGER,

                category TEXT NOT NULL,
                question TEXT NOT NULL,
                correct_answer TEXT NOT NULL,

                fact_check_date TEXT,
                source_year INTEGER,

                wrong_answers_json TEXT NOT NULL
                    DEFAULT '[]',

                difficulty_score INTEGER,
                difficulty_label TEXT,
                suggested_round TEXT,

                eligible_sports INTEGER NOT NULL
                    DEFAULT 0,

                eligible_regular INTEGER NOT NULL
                    DEFAULT 1,

                eligible_after_dark INTEGER NOT NULL
                    DEFAULT 0,

                freshness_status TEXT NOT NULL
                    DEFAULT 'UNREVIEWED',

                network_status TEXT NOT NULL
                    DEFAULT 'IMPORTED',

                review_note TEXT DEFAULT '',
                host_notes TEXT DEFAULT '',

                audio_mp3 TEXT DEFAULT '',
                question_image TEXT DEFAULT '',
                reveal_image TEXT DEFAULT '',
                video_clip TEXT DEFAULT '',
                voiceover_audio TEXT DEFAULT '',

                question_font_override INTEGER,
                answer_font_override INTEGER,

                last_network_used TEXT,
                times_network_used INTEGER NOT NULL
                    DEFAULT 0,

                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        # ====================================================
        # BUILD 1B MIGRATION
        #
        # These fields are added safely to existing databases.
        # Existing questions/games are preserved.
        # ====================================================

        ensure_column(
            conn,
            "questions",
            "roulette_hint",
            "TEXT DEFAULT ''",
        )

        ensure_column(
            conn,
            "questions",
            "roulette_hint_status",
            """
            TEXT NOT NULL
            DEFAULT 'NEEDS_HINT'
            """,
        )

        ensure_column(
            conn,
            "questions",
            "roulette_suitable",
            """
            INTEGER NOT NULL
            DEFAULT 1
            """,
        )

        # ====================================================
        # GAMES
        # ====================================================

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                game_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,

                game_type TEXT NOT NULL,

                scheduled_for TEXT,

                status TEXT NOT NULL
                    DEFAULT 'DRAFT',

                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        # ====================================================
        # QUESTIONS INSIDE A GAME
        # ====================================================

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS game_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                game_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,

                slot_id TEXT NOT NULL,

                round_number INTEGER NOT NULL,
                question_number INTEGER NOT NULL,
                display_order INTEGER NOT NULL,

                question_type TEXT NOT NULL
                    DEFAULT 'normal',

                scoring_type TEXT NOT NULL
                    DEFAULT 'fastest',

                timer_seconds INTEGER,
                wager_seconds INTEGER,

                max_points INTEGER,
                min_points INTEGER,

                hint TEXT DEFAULT '',

                choices_json TEXT NOT NULL
                    DEFAULT '[]',

                correct_index INTEGER,

                question_snapshot_json TEXT NOT NULL
                    DEFAULT '{}',

                presentation_overrides_json TEXT NOT NULL
                    DEFAULT '{}',

                FOREIGN KEY (game_id)
                    REFERENCES games(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (question_id)
                    REFERENCES questions(id),

                UNIQUE(game_id, slot_id)
            )
            """
        )

        # ====================================================
        # QUESTION USAGE HISTORY
        # ====================================================

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS question_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                question_id INTEGER NOT NULL,
                game_id INTEGER,

                scheduled_for TEXT,
                used_at TEXT NOT NULL,

                FOREIGN KEY (question_id)
                    REFERENCES questions(id),

                FOREIGN KEY (game_id)
                    REFERENCES games(id)
            )
            """
        )

        # ====================================================
        # INDEXES
        # ====================================================

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_questions_source_year
            ON questions(source_year)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_questions_fact_check_date
            ON questions(fact_check_date)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_questions_network_status
            ON questions(network_status)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_questions_category
            ON questions(category)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_questions_last_used
            ON questions(last_network_used)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_question_usage_question
            ON question_usage(question_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_question_usage_date
            ON question_usage(used_at)
            """
        )

        conn.execute(
            """
            INSERT INTO meta(
                key,
                value
            )
            VALUES(
                'schema_version',
                ?
            )

            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value
            """,
            (
                SCHEMA_VERSION,
            ),
        )

        conn.commit()

    finally:
        conn.close()


def get_database_stats() -> dict:

    conn = connect()

    try:

        question_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM questions
            """
        ).fetchone()[0]

        game_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM games
            """
        ).fetchone()[0]

        ready_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM questions
            WHERE network_status =
                'NETWORK_READY'
            """
        ).fetchone()[0]

        needs_choices = conn.execute(
            """
            SELECT COUNT(*)
            FROM questions
            WHERE network_status =
                'NEEDS_CHOICES'
            """
        ).fetchone()[0]

        return {
            "database": str(DB_PATH),
            "schema_version": SCHEMA_VERSION,
            "questions": question_count,
            "network_ready": ready_count,
            "needs_choices": needs_choices,
            "games": game_count,
        }

    finally:
        conn.close()


if __name__ == "__main__":

    initialize_database()

    stats = get_database_stats()

    print()
    print(
        "=============================================="
    )
    print(
        " ELITE NETWORK QUESTION BANK"
    )
    print(
        "=============================================="
    )

    print(
        f"Database:      "
        f"{stats['database']}"
    )

    print(
        f"Schema:        "
        f"{stats['schema_version']}"
    )

    print(
        f"Questions:     "
        f"{stats['questions']}"
    )

    print(
        f"Needs Choices: "
        f"{stats['needs_choices']}"
    )

    print(
        f"Network Ready: "
        f"{stats['network_ready']}"
    )

    print(
        f"Games:         "
        f"{stats['games']}"
    )

    print(
        "=============================================="
    )

    print()
    print(
        "Question Bank initialized successfully."
    )
    print()