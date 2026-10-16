from pathlib import Path
import shutil


# ============================================================
# ELITE NETWORK GAME BUILDER
# ADMIN SAVE ROUTE INSTALLER
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
    "main.py.before_game_builder_save.py"
)


OLD_IMPORT = (
    "from game_builder.admin_data "
    "import get_game_builder_payload"
)


NEW_IMPORT = """from game_builder.admin_data import get_game_builder_payload
from game_builder.admin_save import save_game_builder_question"""


POST_ANCHOR = """            if parsed.path == "/api/tv-heartbeat":
"""


POST_ROUTE = """            # ====================================================
            # ELITE NETWORK GAME BUILDER — SAVE QUESTION
            # ====================================================

            if parsed.path == "/api/admin/game-builder/save":

                result = save_game_builder_question(
                    payload
                )

                return self._send_json(
                    {
                        "ok": True,
                        "result": result,
                    }
                )

            if parsed.path == "/api/tv-heartbeat":
"""


def main():

    if not MAIN_FILE.exists():

        raise FileNotFoundError(
            f"Could not find:\n"
            f"{MAIN_FILE}"
        )

    text = MAIN_FILE.read_text(
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # BACKUP
    # --------------------------------------------------------

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
        "from game_builder.admin_save "
        "import save_game_builder_question"
        not in text
    ):

        if OLD_IMPORT not in text:

            raise RuntimeError(
                "Could not find the existing "
                "Game Builder import in main.py."
            )

        text = text.replace(
            OLD_IMPORT,
            NEW_IMPORT,
            1,
        )

        changed = True

        print(
            "Installed Game Builder "
            "save import."
        )

    else:

        print(
            "Game Builder save import "
            "already installed."
        )

    # --------------------------------------------------------
    # POST ROUTE
    # --------------------------------------------------------

    if (
        '"/api/admin/game-builder/save"'
        not in text
    ):

        if POST_ANCHOR not in text:

            raise RuntimeError(
                "Could not find POST route "
                "anchor in main.py."
            )

        text = text.replace(
            POST_ANCHOR,
            POST_ROUTE,
            1,
        )

        changed = True

        print(
            "Installed Game Builder "
            "save route."
        )

    else:

        print(
            "Game Builder save route "
            "already installed."
        )

    # --------------------------------------------------------
    # WRITE
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
            "No main.py changes were needed."
        )

    print()
    print(
        "Game Builder save API ready:"
    )

    print(
        "POST "
        "/api/admin/game-builder/save"
    )

    print()


if __name__ == "__main__":

    main()