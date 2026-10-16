
import os
import shutil
import sqlite3
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent

SOURCE_DB = (
    PROJECT_DIR
    / "game_builder"
    / "question_bank.sqlite3"
)

TARGET_DB = Path(
    os.environ.get(
        "ELITE_NETWORK_DB_PATH",
        str(SOURCE_DB),
    )
)

EXPECTED_GAME_KEYS = [
    "sports-blitz-20261006-2pm",
    "sports-blitz-20261006-3pm",
    "sports-blitz-20261006-4pm",
    "regular-blitz-20261006-6pm",
    "regular-blitz-20261006-7pm",
    "regular-blitz-20261006-8pm",
    "after-dark-20261006-9pm",
    "after-dark-20261006-10pm",
    "after-dark-20261006-11pm",
]


def verify_database(path):
    # Read-only connection prevents accidental schema changes.
    with sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro",
        uri=True,
    ) as conn:
        integrity = conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            raise RuntimeError(
                f"Database integrity check failed: {integrity}"
            )

        rows = conn.execute(
            "SELECT game_key FROM games"
        ).fetchall()

        found = {row[0] for row in rows}
        missing = set(EXPECTED_GAME_KEYS) - found

        if missing:
            raise RuntimeError(
                "Missing expected games: "
                + ", ".join(sorted(missing))
            )

    print(
        f"Database verified: {len(EXPECTED_GAME_KEYS)} "
        "corrected games present.",
        flush=True,
    )


def main():
    if not SOURCE_DB.is_file():
        raise RuntimeError(
            f"Seed database not found: {SOURCE_DB}"
        )

    verify_database(SOURCE_DB)

    if TARGET_DB.resolve() == SOURCE_DB.resolve():
        print(
            "Local database verified. No copy needed.",
            flush=True,
        )
        return

    TARGET_DB.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if TARGET_DB.exists():
        print(
            "Existing persistent database found. "
            "Leaving it untouched.",
            flush=True,
        )

        verify_database(TARGET_DB)
        return

    # Copy to a temporary file first so a failed copy
    # cannot leave a partial database at the target path.
    temporary = TARGET_DB.with_name(
        TARGET_DB.name + ".initializing"
    )

    if temporary.exists():
        temporary.unlink()

    shutil.copy2(
        SOURCE_DB,
        temporary,
    )

    try:
        verify_database(temporary)

        # Atomic rename on the same filesystem.
        temporary.replace(TARGET_DB)

        print(
            f"Persistent database initialized: {TARGET_DB}",
            flush=True,
        )

    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    main()
