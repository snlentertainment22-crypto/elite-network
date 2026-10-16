from pathlib import Path
import shutil


# ============================================================
# ELITE NETWORK GAME BUILDER
# ADMIN AI ROUTE INSTALLER
# Build 1A
# ============================================================


ROOT_DIR = Path(
    __file__
).resolve().parent.parent

MAIN_FILE = (
    ROOT_DIR
    /
    "main.py"
)

BACKUP_FILE = (
    ROOT_DIR
    /
    "main.py.before_admin_ai.py"
)


IMPORT_ANCHOR = (
    "from game_builder.admin_review "
    "import review_game_builder_question"
)


IMPORT_REPLACEMENT = """from game_builder.admin_review import review_game_builder_question
from game_builder.admin_ai import prepare_admin_game_slot"""


POST_ANCHOR = """            if parsed.path == "/api/admin/game-builder/review":
"""


POST_REPLACEMENT = """            # ====================================================
            # ELITE NETWORK GAME BUILDER — AI PREP
            # ====================================================

            if parsed.path == "/api/admin/game-builder/ai-prep":

                result = prepare_admin_game_slot(
                    payload
                )

                return self._send_json(
                    {
                        "ok": True,
                        "result": result,
                    }
                )

            if parsed.path == "/api/admin/game-builder/review":
"""


def main():

    if not MAIN_FILE.exists():

        raise FileNotFoundError(
            f"Could not find:\\n"
            f"{MAIN_FILE}"
        )

    text = MAIN_FILE.read_text(
        encoding="utf-8"
    )

    if not BACKUP_FILE.exists():

        shutil.copy2(
            MAIN_FILE,
            BACKUP_FILE,
        )

        print(
            "Backup created:"
        )

        print(
            BACKUP_FILE
        )

    changed = False

    # --------------------------------------------------------
    # IMPORT
    # --------------------------------------------------------

    if (
        "from game_builder.admin_ai "
        "import prepare_admin_game_slot"
        not in text
    ):

        if IMPORT_ANCHOR not in text:

            raise RuntimeError(
                "Could not find "
                "admin_review import."
            )

        text = text.replace(
            IMPORT_ANCHOR,
            IMPORT_REPLACEMENT,
            1,
        )

        changed = True

        print(
            "Installed Admin AI import."
        )

    # --------------------------------------------------------
    # ROUTE
    # --------------------------------------------------------

    if (
        '"/api/admin/game-builder/ai-prep"'
        not in text
    ):

        if POST_ANCHOR not in text:

            raise RuntimeError(
                "Could not find "
                "review POST route."
            )

        text = text.replace(
            POST_ANCHOR,
            POST_REPLACEMENT,
            1,
        )

        changed = True

        print(
            "Installed Admin AI route."
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    if changed:

        MAIN_FILE.write_text(
            text,
            encoding="utf-8",
        )

        print()

        print(
            "MAIN.PY UPDATED SUCCESSFULLY."
        )

    else:

        print()

        print(
            "No changes were needed."
        )

    print()

    print(
        "AI Prep API:"
    )

    print(
        "POST "
        "/api/admin/game-builder/ai-prep"
    )

    print()


if __name__ == "__main__":

    main()