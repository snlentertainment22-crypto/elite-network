from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .auto_block_selector import (
    collect_ids,
    get_pool_questions,
    load_questions,
)
from .save_daily_preview_games import (
    build_selection,
    connect,
    create_game,
    game_exists,
    initialize_database,
    load_template_slots,
)


VALID_DAY_COUNTS = {1, 2, 3, 5, 7}

QUESTIONS_PER_GAME = 24
GAMES_PER_TYPE_PER_DAY = 3
QUESTIONS_PER_TYPE_PER_DAY = (
    QUESTIONS_PER_GAME
    * GAMES_PER_TYPE_PER_DAY
)


GAME_SCHEDULE = (
    (
        "SPORTS_BLITZ",
        "sports-blitz",
        "Sports Blitz",
        14,
        "2pm",
    ),
    (
        "SPORTS_BLITZ",
        "sports-blitz",
        "Sports Blitz",
        15,
        "3pm",
    ),
    (
        "SPORTS_BLITZ",
        "sports-blitz",
        "Sports Blitz",
        16,
        "4pm",
    ),
    (
        "REGULAR_BLITZ",
        "regular-blitz",
        "Regular Blitz",
        18,
        "6pm",
    ),
    (
        "REGULAR_BLITZ",
        "regular-blitz",
        "Regular Blitz",
        19,
        "7pm",
    ),
    (
        "REGULAR_BLITZ",
        "regular-blitz",
        "Regular Blitz",
        20,
        "8pm",
    ),
    (
        "AFTER_DARK_BLITZ",
        "after-dark",
        "After Dark",
        21,
        "9pm",
    ),
    (
        "AFTER_DARK_BLITZ",
        "after-dark",
        "After Dark",
        22,
        "10pm",
    ),
    (
        "AFTER_DARK_BLITZ",
        "after-dark",
        "After Dark",
        23,
        "11pm",
    ),
)


def resolve_start_date(
    value: str | None = None,
) -> date:

    if value:

        try:
            return date.fromisoformat(
                value
            )

        except ValueError as exc:

            raise ValueError(
                "start_date must use YYYY-MM-DD."
            ) from exc

    return (
        date.today()
        + timedelta(days=1)
    )


def scheduled_for_value(
    game_date: date,
    hour: int,
) -> str:

    # Stored as Central/local schedule time.
    # The Network scheduler will interpret this
    # as the configured venue/network timezone.
    return datetime.combine(
        game_date,
        time(
            hour=hour,
            minute=0,
            second=0,
        ),
    ).isoformat()


def capacity_report(
    days: int,
) -> dict:

    all_questions = load_questions()

    sports = len(
        get_pool_questions(
            all_questions,
            "sports",
        )
    )

    regular = len(
        get_pool_questions(
            all_questions,
            "regular",
        )
    )

    after_dark = len(
        get_pool_questions(
            all_questions,
            "after_dark",
        )
    )

    required = (
        QUESTIONS_PER_TYPE_PER_DAY
        * days
    )

    return {
        "days":
            days,

        "required_per_type":
            required,

        "sports_available":
            sports,

        "regular_available":
            regular,

        "after_dark_available":
            after_dark,

        "sports_ok":
            sports >= required,

        "regular_ok":
            regular >= required,

        "after_dark_ok":
            after_dark >= required,
    }


def _capacity_error(
    report: dict,
) -> str | None:

    problems = []

    required = int(
        report[
            "required_per_type"
        ]
    )

    for label, field in (
        (
            "Sports",
            "sports_available",
        ),
        (
            "Regular",
            "regular_available",
        ),
        (
            "After Dark",
            "after_dark_available",
        ),
    ):

        available = int(
            report[field]
        )

        if available < required:

            problems.append(
                f"{label} needs "
                f"{required} approved questions "
                f"for this batch but only "
                f"{available} are available."
            )

    if not problems:
        return None

    return " ".join(
        problems
    )


def plan_auto_games(
    days: int,
    start_date: str | None = None,
) -> dict:

    if days not in VALID_DAY_COUNTS:

        raise ValueError(
            "Days must be one of: "
            "1, 2, 3, 5, 7."
        )

    first_date = resolve_start_date(
        start_date
    )

    capacity = capacity_report(
        days
    )

    capacity_problem = (
        _capacity_error(
            capacity
        )
    )

    if capacity_problem:

        raise RuntimeError(
            capacity_problem
        )


    excluded_ids: set[int] = set()

    day_plans = []


    for day_index in range(days):

        game_date = (
            first_date
            + timedelta(
                days=day_index
            )
        )

        seed = int(
            game_date.strftime(
                "%Y%m%d"
            )
        )

        (
            sports_games,
            regular_games,
            after_dark_games,
        ) = build_selection(
            seed,
            excluded_ids=
                excluded_ids,
        )


        selected_games = (
            sports_games
            +
            regular_games
            +
            after_dark_games
        )


        selected_ids = collect_ids(
            selected_games
        )

        overlap = (
            excluded_ids
            &
            selected_ids
        )

        if overlap:

            raise RuntimeError(
                "Cross-day duplicate protection failed. "
                f"Duplicate question IDs: "
                f"{sorted(overlap)}"
            )


        excluded_ids.update(
            selected_ids
        )


        day_game_specs = []


        for index, (
            game_type,
            key_prefix,
            title_prefix,
            hour,
            hour_label,
        ) in enumerate(
            GAME_SCHEDULE
        ):

            questions = (
                selected_games[index]
            )

            date_key = (
                game_date.strftime(
                    "%Y%m%d"
                )
            )

            game_key = (
                f"{key_prefix}-"
                f"{date_key}-"
                f"{hour_label}"
            )

            title = (
                f"{title_prefix} - "
                f"{game_date.strftime('%a %b %d')} - "
                f"{hour_label.upper()}"
            )

            scheduled_for = (
                scheduled_for_value(
                    game_date,
                    hour,
                )
            )

            day_game_specs.append(
                {
                    "game_key":
                        game_key,

                    "title":
                        title,

                    "game_type":
                        game_type,

                    "scheduled_for":
                        scheduled_for,

                    "questions":
                        questions,
                }
            )


        day_plans.append(
            {
                "date":
                    game_date.isoformat(),

                "seed":
                    seed,

                "games":
                    day_game_specs,

                "question_count":
                    len(selected_ids),
            }
        )


    expected_questions = (
        days
        * 9
        * 24
    )

    if len(excluded_ids) != expected_questions:

        raise RuntimeError(
            "Batch uniqueness verification failed. "
            f"Expected {expected_questions} unique questions, "
            f"found {len(excluded_ids)}."
        )


    return {
        "days":
            days,

        "start_date":
            first_date.isoformat(),

        "end_date":
            (
                first_date
                + timedelta(
                    days=days - 1
                )
            ).isoformat(),

        "game_count":
            days * 9,

        "question_count":
            expected_questions,

        "capacity":
            capacity,

        "day_plans":
            day_plans,
    }


def build_auto_games(
    days: int,
    start_date: str | None = None,
) -> dict:

    initialize_database()

    plan = plan_auto_games(
        days,
        start_date,
    )


    all_specs = []

    for day_plan in plan[
        "day_plans"
    ]:

        all_specs.extend(
            day_plan[
                "games"
            ]
        )


    conn = connect()

    created = []


    try:

        template_slots = (
            load_template_slots(
                conn
            )
        )


        existing = []

        for spec in all_specs:

            if game_exists(
                conn,
                spec[
                    "game_key"
                ],
            ):

                existing.append(
                    spec[
                        "game_key"
                    ]
                )


        if existing:

            raise RuntimeError(
                "BUILD STOPPED BEFORE CHANGING DATABASE. "
                "These games already exist: "
                +
                ", ".join(
                    existing
                )
            )


        for spec in all_specs:

            game_id = create_game(
                conn,
                template_slots,
                spec[
                    "game_key"
                ],
                spec[
                    "title"
                ],
                spec[
                    "game_type"
                ],
                spec[
                    "questions"
                ],
                scheduled_for=
                    spec[
                        "scheduled_for"
                    ],
            )


            created.append(
                {
                    "id":
                        game_id,

                    "game_key":
                        spec[
                            "game_key"
                        ],

                    "title":
                        spec[
                            "title"
                        ],

                    "game_type":
                        spec[
                            "game_type"
                        ],

                    "scheduled_for":
                        spec[
                            "scheduled_for"
                        ],

                    "question_count":
                        24,
                }
            )


        conn.commit()


    except Exception:

        conn.rollback()

        raise


    finally:

        conn.close()


    return {
        "ok":
            True,

        "days":
            plan[
                "days"
            ],

        "start_date":
            plan[
                "start_date"
            ],

        "end_date":
            plan[
                "end_date"
            ],

        "games_created":
            len(created),

        "questions_assigned":
            len(created) * 24,

        "status":
            "DRAFT",

        "created":
            created,
    }
