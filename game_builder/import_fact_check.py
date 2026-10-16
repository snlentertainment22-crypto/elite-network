import csv
import json
import re
from datetime import date
from pathlib import Path

from question_bank import connect, initialize_database, utc_now


# ============================================================
# ELITE NETWORK GAME BUILDER
# Fact Checked Master Importer
# Permanent Master-ID version
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

CSV_PATH = (
    BASE_DIR
    / "imports"
    / "fact_checked_questions.csv"
)

def clean_text(value: str) -> str:
    return " ".join(
        str(value or "")
        .strip()
        .split()
    )


def parse_fact_check_date(
    raw_value: str,
) -> date | None:

    text = clean_text(
        raw_value
    )

    match = re.match(
        r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})",
        text,
    )

    if not match:
        return None

    month_text, day_text, year_text = (
        match.groups()
    )

    month = int(
        month_text
    )

    day = int(
        day_text
    )

    year = int(
        year_text
    )

    if year < 100:
        year += 2000

    try:
        return date(
            year,
            month,
            day,
        )

    except ValueError:
        return None


def import_master() -> None:

    initialize_database()

    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"\nCould not find:\n{CSV_PATH}\n"
        )

    conn = connect()

    imported_new = 0
    already_present = 0
    refreshed_existing = 0

    invalid_date_rows = 0
    invalid_master_id_rows = 0
    skipped_incomplete = 0

    master_choices_added = 0

    sample_questions = []

    now = utc_now()

    try:
        with CSV_PATH.open(
            "r",
            encoding="utf-8-sig",
            newline="",
            errors="replace",
        ) as csv_file:

            reader = csv.reader(
                csv_file
            )

            for row_number, row in enumerate(
                reader,
                start=1,
            ):

                # =================================================
                # NEW MASTER FORMAT
                #
                # A = Category
                # B = Question
                # C = Wrong 1
                # D = Wrong 2
                # E = Wrong 3
                # F = Wrong 4
                # G = Wrong 5
                # H = Correct Answer
                # I = Fact Checked
                # J = Master ID
                # =================================================

                if len(row) < 10:
                    skipped_incomplete += 1
                    continue

                category = clean_text(
                    row[0]
                )

                question = clean_text(
                    row[1]
                )

                wrong_answers = [
                    clean_text(
                        row[index]
                    )
                    for index
                    in range(
                        2,
                        7,
                    )
                    if clean_text(
                        row[index]
                    )
                ]

                answer = clean_text(
                    row[7]
                )

                raw_date = clean_text(
                    row[8]
                )

                master_id = clean_text(
                    row[9]
                ).upper()

                # Skip headers, warning rows,
                # blank rows, and incomplete data.
                if (
                    not category
                    or not question
                    or not answer
                ):
                    skipped_incomplete += 1
                    continue

                if (
                    category.lower()
                    == "category"
                ):
                    continue

                if not re.fullmatch(
                    r"EQ\d{6}",
                    master_id,
                ):
                    invalid_master_id_rows += 1
                    continue

                parsed_date = (
                    parse_fact_check_date(
                        raw_date
                    )
                )

                if parsed_date is None:
                    invalid_date_rows += 1
                    continue

                source_key = master_id

                existing = conn.execute(
                    """
                    SELECT
                        id,
                        wrong_answers_json
                    FROM questions
                    WHERE source_key = ?
                    """,
                    (
                        source_key,
                    ),
                ).fetchone()

                if existing:
                    already_present += 1
                    refreshed_existing += 1

                else:
                    imported_new += 1

                master_wrong_json = (
                    json.dumps(
                        wrong_answers,
                        ensure_ascii=False,
                    )
                )

                # =================================================
                # INSERT NEW MASTER QUESTION
                #
                # New rows receive verified master distractors
                # immediately when available.
                # =================================================

                if not existing:

                    conn.execute(
                        """
                        INSERT INTO questions (
                            source_system,
                            source_key,
                            source_row,

                            category,
                            question,
                            correct_answer,

                            fact_check_date,
                            source_year,

                            wrong_answers_json,

                            freshness_status,
                            network_status,

                            created_at,
                            updated_at
                        )
                        VALUES (
                            'elite_fact_check',
                            ?,
                            ?,

                            ?,
                            ?,
                            ?,

                            ?,
                            ?,

                            ?,

                            'NEEDS_REVIEW',
                            'NEEDS_CHOICES',

                            ?,
                            ?
                        )
                        """,
                        (
                            source_key,
                            row_number,

                            category,
                            question,
                            answer,

                            parsed_date.isoformat(),
                            parsed_date.year,

                            master_wrong_json,

                            now,
                            now,
                        ),
                    )

                    if wrong_answers:
                        master_choices_added += 1

                # =================================================
                # REFRESH EXISTING QUESTION
                #
                # Only source-owned fields are refreshed.
                #
                # Existing Network choices are preserved.
                # If Network has no choices yet and master does,
                # copy the verified master choices in.
                # =================================================

                else:

                    existing_wrong_raw = (
                        existing[
                            "wrong_answers_json"
                        ]
                        or "[]"
                    )

                    try:
                        existing_wrong = (
                            json.loads(
                                existing_wrong_raw
                            )
                        )

                    except Exception:
                        existing_wrong = []

                    should_add_master_choices = (
                        not existing_wrong
                        and bool(
                            wrong_answers
                        )
                    )

                    if should_add_master_choices:

                        conn.execute(
                            """
                            UPDATE questions
                            SET
                                source_row = ?,
                                category = ?,
                                question = ?,
                                correct_answer = ?,
                                fact_check_date = ?,
                                source_year = ?,
                                wrong_answers_json = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                row_number,
                                category,
                                question,
                                answer,
                                parsed_date.isoformat(),
                                parsed_date.year,
                                master_wrong_json,
                                now,
                                existing["id"],
                            ),
                        )

                        master_choices_added += 1

                    else:

                        conn.execute(
                            """
                            UPDATE questions
                            SET
                                source_row = ?,
                                category = ?,
                                question = ?,
                                correct_answer = ?,
                                fact_check_date = ?,
                                source_year = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                row_number,
                                category,
                                question,
                                answer,
                                parsed_date.isoformat(),
                                parsed_date.year,
                                now,
                                existing["id"],
                            ),
                        )

                if len(
                    sample_questions
                ) < 5:

                    sample_questions.append(
                        {
                            "master_id":
                                master_id,

                            "category":
                                category,

                            "question":
                                question,

                            "answer":
                                answer,

                            "wrong_answers":
                                wrong_answers,

                            "date":
                                parsed_date.isoformat(),
                        }
                    )

        conn.commit()

        total_master = conn.execute(
            """
            SELECT COUNT(*)
            FROM questions
            WHERE source_system = 'elite_fact_check'
              AND source_key LIKE 'EQ%'
            """
        ).fetchone()[0]

        needs_choices = conn.execute(
            """
            SELECT COUNT(*)
            FROM questions
            WHERE source_system = 'elite_fact_check'
              AND source_key LIKE 'EQ%'
              AND network_status = 'NEEDS_CHOICES'
            """
        ).fetchone()[0]

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
        " ELITE NETWORK - FACT CHECK MASTER IMPORT"
    )
    print(
        "======================================================"
    )

    print(
        f"Source file:          {CSV_PATH}"
    )

    print(
        f"New questions:        {imported_new}"
    )

    print(
        f"Already present:      {already_present}"
    )

    print(
        f"Existing refreshed:   {refreshed_existing}"
    )

    print(
        f"Master choices added: {master_choices_added}"
    )

    print(
        f"Bad date rows:        {invalid_date_rows}"
    )

    print(
        f"Bad Master IDs:       {invalid_master_id_rows}"
    )

    print()

    print(
        f"MASTER QUESTIONS IN BANK: {total_master}"
    )

    print(
        f"NEEDS CHOICES:            {needs_choices}"
    )

    print(
        "======================================================"
    )

    if sample_questions:

        print()
        print(
            "SAMPLE MASTER QUESTIONS"
        )

        print(
            "-----------------------"
        )

        for index, item in enumerate(
            sample_questions,
            start=1,
        ):

            print()

            print(
                f"{index}. "
                f"{item['master_id']} "
                f"[{item['category']}]"
            )

            print(
                item[
                    "question"
                ]
            )

            print(
                f"ANSWER: "
                f"{item['answer']}"
            )

            print(
                f"WRONG ANSWERS: "
                f"{item['wrong_answers']}"
            )

            print(
                f"FACT CHECKED: "
                f"{item['date']}"
            )

    print()
    print(
        "Import completed successfully."
    )
    print()


if __name__ == "__main__":
    import_master()
