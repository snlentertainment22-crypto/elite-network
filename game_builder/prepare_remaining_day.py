from __future__ import annotations

import argparse

from game_builder.ai_prepare_full_game import (
    prepare_full_game,
)

from game_builder.runtime_game_loader import (
    load_runtime_game,
)


GAMES = [
    "sports-blitz-test-20261004-02",
    "sports-blitz-test-20261004-03",

    "regular-blitz-test-20261004-6pm",
    "regular-blitz-test-20261004-7pm",
    "regular-blitz-test-20261004-8pm",

    "after-dark-test-20261004-9pm",
    "after-dark-test-20261004-10pm",
    "after-dark-test-20261004-11pm",
]


def verify_game(game_key: str) -> None:

    data = load_runtime_game(
        game_key
    )

    questions = data.get(
        "questions",
        [],
    )

    if len(questions) != 24:
        raise RuntimeError(
            f"{game_key}: expected 24 questions, "
            f"got {len(questions)}."
        )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually prepare all remaining games.",
    )

    args = parser.parse_args()

    ready = []
    failed = []

    for index, game_key in enumerate(
        GAMES,
        start=1,
    ):

        print()
        print(
            "######################################################"
        )
        print(
            f" GAME {index} OF {len(GAMES)}"
        )
        print(
            f" {game_key}"
        )
        print(
            "######################################################"
        )

        try:

            prepare_full_game(
                game_key,
                execute=args.run,
            )

            if args.run:

                verify_game(
                    game_key
                )

                ready.append(
                    game_key
                )

                print()
                print(
                    f"RUNTIME VERIFIED: "
                    f"{game_key} — 24/24"
                )

        except Exception as exc:

            failed.append(
                (
                    game_key,
                    str(exc),
                )
            )

            print()
            print(
                f"FAILED: {game_key}"
            )

            print(
                str(exc)
            )

    print()
    print(
        "======================================================"
    )
    print(
        " REMAINING DAY BATCH COMPLETE"
    )
    print(
        "======================================================"
    )

    if args.run:

        print(
            f"Runtime ready: {len(ready)} / {len(GAMES)}"
        )

        print(
            f"Failed:        {len(failed)}"
        )

        if failed:

            print()

            for game_key, reason in failed:

                print(
                    f"{game_key}"
                )

                print(
                    f"  {reason}"
                )

    else:

        print(
            "PREFLIGHT ONLY — NO AI CALLS MADE."
        )

        print(
            "Run with --run when ready."
        )


if __name__ == "__main__":
    main()
