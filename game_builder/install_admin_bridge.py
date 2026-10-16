from pathlib import Path
import shutil


# ============================================================
# ELITE NETWORK GAME BUILDER
# ADMIN WEB BRIDGE INSTALLER
# Build 1A
#
# Safely adds:
#
#   /game-builder
#   /admin/game-builder
#   /api/admin/game-builder
#
# to the existing Elite Network HTTP server.
#
# Creates a backup of main.py before changing it.
# ============================================================


ROOT_DIR = Path(__file__).resolve().parent.parent
MAIN_FILE = ROOT_DIR / "main.py"

BACKUP_FILE = (
    ROOT_DIR
    / "main.py.before_game_builder_admin.py"
)


IMPORT_LINE = (
    "from game_builder.admin_data "
    "import get_game_builder_payload\n"
)


IMPORT_ANCHOR = (
    "from urllib.request import Request, urlopen\n"
)


ROUTE_ANCHOR = """        if path == "/player":
            return self._serve_html(WEB_DIR / "player.html")
        if path == "/api/state":
"""


ROUTE_REPLACEMENT = """        if path == "/player":
            return self._serve_html(WEB_DIR / "player.html")

        # ====================================================
        # ELITE NETWORK GAME BUILDER
        # ====================================================

        if path in (
            "/game-builder",
            "/admin/game-builder",
        ):
            return self._serve_html(
                WEB_DIR / "game_builder.html"
            )

        if path == "/api/admin/game-builder":

            game_key = query.get(
                "game_key",
                ["regular-blitz-test-2022-001"],
            )[0]

            try:

                game = get_game_builder_payload(
                    game_key
                )

                return self._send_json(
                    {
                        "ok": True,
                        "game": game,
                    }
                )

            except ValueError as exc:

                return self._send_json(
                    {
                        "ok": False,
                        "error": str(exc),
                    },
                    HTTPStatus.NOT_FOUND,
                )

            except Exception as exc:

                return self._send_json(
                    {
                        "ok": False,
                        "error": (
                            "Game Builder error: "
                            f"{exc}"
                        ),
                    },
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        if path == "/api/state":
"""


def main():

    if not MAIN_FILE.exists():

        raise FileNotFoundError(
            f"Could not find:\n{MAIN_FILE}"
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

    if IMPORT_LINE not in text:

        if IMPORT_ANCHOR not in text:

            raise RuntimeError(
                "Could not find import anchor "
                "in main.py."
            )

        text = text.replace(
            IMPORT_ANCHOR,
            IMPORT_ANCHOR
            + IMPORT_LINE,
            1,
        )

        changed = True

        print(
            "Installed Game Builder import."
        )

    else:

        print(
            "Game Builder import already installed."
        )

    # --------------------------------------------------------
    # ROUTES
    # --------------------------------------------------------

    if (
        '"/api/admin/game-builder"'
        not in text
    ):

        if ROUTE_ANCHOR not in text:

            raise RuntimeError(
                "Could not find HTTP route anchor "
                "in main.py."
            )

        text = text.replace(
            ROUTE_ANCHOR,
            ROUTE_REPLACEMENT,
            1,
        )

        changed = True

        print(
            "Installed Game Builder routes."
        )

    else:

        print(
            "Game Builder routes already installed."
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
            "No main.py changes were needed."
        )

    print()
    print(
        "Game Builder URL:"
    )

    print(
        "http://localhost:8080/game-builder"
    )

    print()


if __name__ == "__main__":
    main()