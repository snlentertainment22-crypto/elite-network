from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from .question_bank import connect, initialize_database
except ImportError:
    from question_bank import connect, initialize_database


# ============================================================
# ELITE NETWORK
# AFTER DARK TEST SEED IMPORTER
# Build 1A
#
# Imports:
#   elite_after_dark_seed_questions_32.csv
#
# Into:
#   questions table
#
# IMPORTANT:
# - Test/local Network database only.
# - Does NOT alter Question Checker.
# - Does NOT alter the permanent Fact Checked master.
# - Safe to run more than once.
# - Existing duplicate question text is skipped.
# - Five supplied distractors are saved immediately.
# - No AI calls.
# ============================================================


CSV_FILE = (
    Path(__file__).resolve().parent
    /
    "elite_after_dark_seed_batch2_48.csv"
)


def normalize_text(value: str | None) -> str:

    text = str(
        value or ""
    ).strip().lower()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text


def utc_now() -> str:

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


def load_csv() -> list[dict]:

    if not CSV_FILE.exists():

        raise FileNotFoundError(
            "\nCould not find the After Dark CSV:\n\n"
            f"{CSV_FILE}\n\n"
            "Put elite_after_dark_seed_questions_32.csv "
            "inside the game_builder folder."
        )

    rows = []

    with CSV_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        reader = csv.DictReader(
            file
        )

        for source_row, row in enumerate(
            reader,
            start=2,
        ):

            category = str(
                row.get(
                    "Category",
                    "",
                )
                or ""
            ).strip()

            question = str(
                row.get(
                    "Question",
                    "",
                )
                or ""
            ).strip()

            correct_answer = str(
                row.get(
                    "Correct Answer",
                    "",
                )
                or ""
            ).strip()

            wrong_answers = []

            for number in range(
                1,
                6,
            ):

                answer = str(
                    row.get(
                        f"Wrong Answer {number}",
                        "",
                    )
                    or ""
                ).strip()

                if answer:
                    wrong_answers.append(
                        answer
                    )

            source_url = str(
                row.get(
                    "Source",
                    "",
                )
                or ""
            ).strip()

            if not category:
                raise ValueError(
                    f"CSV row {source_row}: "
                    "Category is blank."
                )

            if not category.lower().startswith(
                "after dark"
            ):
                raise ValueError(
                    f"CSV row {source_row}: "
                    f'Category must start with "After Dark". '
                    f"Found: {category}"
                )

            if not question:
                raise ValueError(
                    f"CSV row {source_row}: "
                    "Question is blank."
                )

            if not correct_answer:
                raise ValueError(
                    f"CSV row {source_row}: "
                    "Correct Answer is blank."
                )

            if len(
                wrong_answers
            ) != 5:

                raise ValueError(
                    f"CSV row {source_row}: "
                    "Exactly 5 wrong answers are required."
                )

            normalized_wrong = [
                normalize_text(
                    answer
                )
                for answer
                in wrong_answers
            ]

            if len(
                set(
                    normalized_wrong
                )
            ) != 5:

                raise ValueError(
                    f"CSV row {source_row}: "
                    "Duplicate wrong answers found."
                )

            if (
                normalize_text(
                    correct_answer
                )
                in
                normalized_wrong
            ):

                raise ValueError(
                    f"CSV row {source_row}: "
                    "Correct answer also appears "
                    "in the wrong answers."
                )

            rows.append(
                {
                    "source_row":
                        source_row,

                    "category":
                        category,

                    "question":
                        question,

                    "correct_answer":
                        correct_answer,

                    "wrong_answers":
                        wrong_answers,

                    "source_url":
                        source_url,
                }
            )

    return rows


# ============================================================
# DATABASE COLUMN HELPERS
#
# We inspect the existing Network questions table instead
# of assuming every optional field exists.
# ============================================================


def get_question_columns(
    conn,
) -> dict:

    rows = conn.execute(
        """
        PRAGMA table_info(questions)
        """
    ).fetchall()

    columns = {}

    for row in rows:

        item = dict(
            row
        )

        columns[
            item["name"]
        ] = item

    return columns


def build_insert_values(
    item: dict,
    columns: dict,
) -> dict:

    now = utc_now()

    wrong_json = json.dumps(
        item["wrong_answers"],
        ensure_ascii=False,
    )

    normalized_question = (
        normalize_text(
            item["question"]
        )
    )

    # --------------------------------------------------------
    # Values we know how to supply.
    #
    # Only fields that actually exist in THIS database
    # will be inserted.
    # --------------------------------------------------------

    possible_values = {

        "category":
            item["category"],

        "question":
            item["question"],

        "correct_answer":
            item["correct_answer"],

        "wrong_answers_json":
            wrong_json,

        # The answers exist already, but Lucas still reviews
        # the question before publication.
        "network_status":
            "NEEDS_REVIEW",

        "freshness_status":
            "NEEDS_REVIEW",

        "roulette_hint":
            "",

        "roulette_hint_status":
            "NEEDS_HINT",

        "roulette_suitable":
            1,

        "fact_check_date":
            "2026-10-04",

        "source_year":
        2026,

        "source_key":
    (
        "after_dark_seed_batch2_2026_10_04_"
        +
        f"{item['source_row'] - 1:03d}"
    ),

        "source_row":
            item["source_row"],

        "source_file":
            CSV_FILE.name,

        "source_name":
            CSV_FILE.name,

        "source_type":
            "AFTER_DARK_TEST_SEED",

        "source_url":
            item["source_url"],

        "normalized_question":
            normalized_question,

        "special_json":
            "{}",

        "metadata_json":
            json.dumps(
                {
                    "test_seed":
                        True,

                    "pool":
                        "AFTER_DARK",

                    "source_url":
                        item["source_url"],
                },
                ensure_ascii=False,
            ),

        "created_at":
            now,

        "updated_at":
            now,

        "use_count":
            0,

        "times_used":
            0,
    }

    result = {}

    for column_name in columns:

        if column_name in possible_values:

            result[
                column_name
            ] = possible_values[
                column_name
            ]

    return result


def verify_required_columns(
    columns: dict,
    insert_values: dict,
) -> None:

    ignored = {
        "id",
    }

    missing_required = []

    for name, info in columns.items():

        if name in ignored:
            continue

        not_null = bool(
            info.get(
                "notnull",
                0,
            )
        )

        default_value = info.get(
            "dflt_value"
        )

        primary_key = bool(
            info.get(
                "pk",
                0,
            )
        )

        if primary_key:
            continue

        if (
            not_null
            and
            default_value is None
            and
            name not in insert_values
        ):

            missing_required.append(
                name
            )

    if missing_required:

        raise RuntimeError(
            "\nImporter stopped BEFORE changing the database.\n\n"
            "The questions table has required columns "
            "this importer does not recognize:\n\n"
            +
            "\n".join(
                f"  - {name}"
                for name
                in missing_required
            )
            +
            "\n\nSend me this list and we will add them safely."
        )


def question_already_exists(
    conn,
    question: str,
) -> bool:

    row = conn.execute(
        """
        SELECT id
        FROM questions
        WHERE lower(trim(question))
            = lower(trim(?))
        LIMIT 1
        """,
        (
            question,
        ),
    ).fetchone()

    return row is not None


def insert_question(
    conn,
    item: dict,
    columns: dict,
) -> int:

    values = build_insert_values(
        item,
        columns,
    )

    verify_required_columns(
        columns,
        values,
    )

    # These are absolutely required by our Network system.
    for required in (
        "category",
        "question",
        "correct_answer",
        "wrong_answers_json",
    ):

        if required not in columns:

            raise RuntimeError(
                f'questions table is missing '
                f'required column "{required}".'
            )

    insert_columns = list(
        values.keys()
    )

    placeholders = ", ".join(
        "?"
        for _
        in insert_columns
    )

    column_sql = ", ".join(
        insert_columns
    )

    params = [
        values[
            column
        ]
        for column
        in insert_columns
    ]

    cursor = conn.execute(
        f"""
        INSERT INTO questions (
            {column_sql}
        )
        VALUES (
            {placeholders}
        )
        """,
        params,
    )

    return int(
        cursor.lastrowid
    )


# ============================================================
# IMPORT
# ============================================================


def main():

    initialize_database()

    csv_rows = load_csv()

    conn = connect()

    inserted = 0
    skipped = 0

    inserted_ids = []

    try:

        columns = get_question_columns(
            conn
        )

        print()
        print(
            "======================================================"
        )

        print(
            " ELITE NETWORK — AFTER DARK SEED IMPORT"
        )

        print(
            "======================================================"
        )

        print()

        print(
            f"CSV questions found: "
            f"{len(csv_rows)}"
        )

        print()

        # ----------------------------------------------------
        # Validate schema BEFORE first insert.
        # ----------------------------------------------------

        if csv_rows:

            test_values = (
                build_insert_values(
                    csv_rows[0],
                    columns,
                )
            )

            verify_required_columns(
                columns,
                test_values,
            )

        # ----------------------------------------------------
        # Import
        # ----------------------------------------------------

        for item in csv_rows:

            if question_already_exists(
                conn,
                item["question"],
            ):

                skipped += 1

                print(
                    f"SKIP  "
                    f"{item['question']}"
                )

                continue

            question_id = (
                insert_question(
                    conn,
                    item,
                    columns,
                )
            )

            inserted += 1

            inserted_ids.append(
                question_id
            )

            print(
                f"ADD   "
                f"QID {question_id}  "
                f"{item['category']}  "
                f"— {item['question']}"
            )

        conn.commit()

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


    print()
    print(
        "======================================================"
    )

    print(
        " IMPORT COMPLETE"
    )

    print(
        "======================================================"
    )

    print(
        f"Inserted: {inserted}"
    )

    print(
        f"Skipped:  {skipped}"
    )

    print(
        f"Total CSV: {len(csv_rows)}"
    )

    if inserted_ids:

        print(
            f"New question IDs: "
            f"{min(inserted_ids)}"
            f" through "
            f"{max(inserted_ids)}"
        )

    print()
    print(
        "AI calls made: 0"
    )

    print()
    print(
        "These questions are marked NEEDS_REVIEW "
        "for the local Network test."
    )

    print()


if __name__ == "__main__":

    main()