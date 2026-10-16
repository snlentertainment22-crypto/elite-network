import json
import os
import mimetypes
import math
import re
import secrets
import socket
import threading
import time
import io
import qrcode
if os.environ.get("ELITE_HEADLESS") == "1":
    tk = None
    messagebox = None
    simpledialog = None
    ttk = None
else:
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from game_builder.admin_data import get_game_builder_payload
from game_builder.admin_game_list import get_review_games
from game_builder.admin_save import save_game_builder_question
from game_builder.admin_review import review_game_builder_question
from game_builder.admin_ai import prepare_admin_game_slot
from game_builder.admin_auto_build import build_auto_games

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DATA_FILE = BASE_DIR / "game_data.json"
NETWORK_SCHEDULE_FILE = BASE_DIR / "network_schedule.json"
HEARTBEAT_CONFIG_FILE = BASE_DIR / "heartbeat_config.json"
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))


def get_public_base_url():
    configured = os.environ.get(
        "PUBLIC_BASE_URL", ""
    ).strip().rstrip("/")

    if configured:
        if not configured.startswith(
            ("https://", "http://")
        ):
            raise ValueError(
                "PUBLIC_BASE_URL must start with https:// or http://"
            )

        return configured

    return f"http://{get_local_ip()}:{PORT}"


def get_player_join_url():
    return get_public_base_url() + "/player"
POLL_MS = 250
APP_BUILD = "NETWORK-SHELL-1D-HEARTBEAT"



class NetworkScheduler:
    """Local schedule brain for the Elite Network channel shell."""

    DAY_KEYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

    def __init__(self, schedule_path):
        self.lock = threading.RLock()
        self.schedule_path = Path(schedule_path)
        self.schedule = self._load_schedule()
        timezone_name = self.schedule.get("timezone", "America/Chicago")
        try:
            self.timezone = ZoneInfo(timezone_name)
        except Exception:
            self.timezone = datetime.now().astimezone().tzinfo
        self.simulated = False
        self.sim_anchor_datetime = None
        self.sim_anchor_monotonic = None
        self.clock_revision = 0

        # Channel filler can advance early when media ends
        # without changing the real/simulated Network clock.
        self.channel_content_offset_seconds = 0.0
        self.finished_hourly_funny_slot = None

        self.last_program_id = None
        self.event_log = []

    def _load_schedule(self):
        with self.schedule_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("events", [])
        data.setdefault("channel", {})
        data.setdefault(
            "default_program",
            {"id": "elite_channel", "kind": "channel", "title": "ELITE CHANNEL"},
        )
        return data

    def _now_locked(self):
        if self.simulated and self.sim_anchor_datetime is not None:
            elapsed = max(0.0, time.monotonic() - self.sim_anchor_monotonic)
            return self.sim_anchor_datetime + timedelta(seconds=elapsed)
        return datetime.now(self.timezone)

    def now(self):
        with self.lock:
            return self._now_locked()

    def set_simulated_time(self, clock_text):
        with self.lock:
            raw = str(clock_text or "").strip()
            parsed = None
            for fmt in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
                try:
                    parsed = datetime.strptime(raw.upper(), fmt).time()
                    break
                except ValueError:
                    pass
            if parsed is None:
                raise ValueError("Use simulated time like 5:59:50 PM or 6:00 PM.")
            base = datetime.now(self.timezone)
            self.sim_anchor_datetime = base.replace(
                hour=parsed.hour, minute=parsed.minute, second=parsed.second, microsecond=0
            )
            self.sim_anchor_monotonic = time.monotonic()
            self.simulated = True
            self.finished_hourly_funny_slot = None
            self.clock_revision += 1
            self._record_event_locked(
                f"SIM CLOCK â†’ {self.sim_anchor_datetime.strftime('%I:%M:%S %p').lstrip('0')}"
            )
            self.last_program_id = None

    def return_to_live_time(self):
        with self.lock:
            self.simulated = False
            self.finished_hourly_funny_slot = None
            self.sim_anchor_datetime = None
            self.sim_anchor_monotonic = None
            self.clock_revision += 1
            self._record_event_locked("SIM CLOCK OFF â†’ LIVE TIME")
            self.last_program_id = None

    def _record_event_locked(self, message, now=None):
        now = now or self._now_locked()
        stamp = now.strftime("%I:%M:%S %p").lstrip("0")
        self.event_log.append(f"{stamp}  {message}")
        self.event_log = self.event_log[-18:]

    def advance_channel_content(
        self,
        expected_kind=None,
    ):
        """
        Advance only the filler/content clock to the next
        programmed item. Does not alter Network wall time.
        """

        with self.lock:

            snapshot = self.get_snapshot()

            current_kind = snapshot.get(
                "filler_type"
            )

            if (
                expected_kind
                and
                current_kind != expected_kind
            ):
                return {
                    "advanced": False,
                    "reason":
                        "content already changed",
                    "current_kind":
                        current_kind,
                }

            # A scheduled clip is a single play, not a loop until its
            # fixed wall-clock window closes. When the video ends early,
            # resume ordinary channel programming for the rest of that cue.
            hourly_clip_slot = snapshot.get("hourly_funny_slot")
            if current_kind == "funny_clip" and hourly_clip_slot:
                self.finished_hourly_funny_slot = hourly_clip_slot
                self._record_event_locked(
                    f"CHANNEL CLIP COMPLETE -> {hourly_clip_slot}"
                )
                return {
                    "advanced": True,
                    "kind": "funny_clip",
                    "skipped_seconds": 0.0,
                }

            remaining = float(
                snapshot.get(
                    "filler_remaining_seconds",
                    0,
                )
                or 0
            )

            if remaining <= 0:
                return {
                    "advanced": False,
                    "reason":
                        "no remaining filler time",
                    "current_kind":
                        current_kind,
                }

            self.channel_content_offset_seconds += (
                remaining
            )

            self._record_event_locked(
                f"CHANNEL CONTENT COMPLETE -> "
                f"{current_kind}"
            )

            return {
                "advanced": True,
                "kind":
                    current_kind,
                "skipped_seconds":
                    remaining,
            }


    def record_event(self, message):
        with self.lock:
            self._record_event_locked(message)

    def _event_datetime(self, day, event, key):
        hour, minute = [int(x) for x in event[key].split(":")[:2]]
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _event_applies(self, day, event):
        day_key = self.DAY_KEYS[day.weekday()]
        return day_key in event.get("days", self.DAY_KEYS)

    def _current_program_locked(self, now):
        for event in self.schedule.get("events", []):
            if not self._event_applies(now, event):
                continue
            start = self._event_datetime(now, event, "start")
            end = self._event_datetime(now, event, "end")
            if end <= start:
                end += timedelta(days=1)
            if start <= now < end:
                program = dict(event)
                program["start_iso"] = start.isoformat()
                program["end_iso"] = end.isoformat()
                return program
        program = dict(self.schedule.get("default_program", {}))
        program.setdefault("id", "elite_channel")
        program.setdefault("kind", "channel")
        program.setdefault("title", "ELITE CHANNEL")
        return program

    def current_program(self):
        with self.lock:
            return self._current_program_locked(self._now_locked())

    def _next_event_locked(self, now):
        candidates = []
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for day_offset in range(0, 8):
            day = start_of_today + timedelta(days=day_offset)
            for event in self.schedule.get("events", []):
                if not self._event_applies(day, event):
                    continue
                start = self._event_datetime(day, event, "start")
                if start > now:
                    candidates.append((start, event))
        if not candidates:
            return None
        start, event = min(candidates, key=lambda item: item[0])
        result = dict(event)
        result["start_iso"] = start.isoformat()
        result["seconds_until"] = max(0, int((start - now).total_seconds()))
        return result

    def _today_guide_locked(self, now):
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        guide = []
        for event in self.schedule.get("events", []):
            if not self._event_applies(start_of_today, event):
                continue
            start = self._event_datetime(start_of_today, event, "start")
            end = self._event_datetime(start_of_today, event, "end")
            if end <= start:
                end += timedelta(days=1)
            row = dict(event)
            row["start_iso"] = start.isoformat()
            row["end_iso"] = end.isoformat()
            guide.append(row)
        guide.sort(key=lambda row: row["start_iso"])
        return guide

    def get_snapshot(self):
        with self.lock:
            now = self._now_locked()

            program = self._current_program_locked(now)
            next_event = self._next_event_locked(now)

            # -------------------------------------------------
            # ELITE NETWORK PRE-GAME LEAD-IN
            # QR JOIN -> MINI-GAME -> TEAMS READY -> TRIVIA
            # -------------------------------------------------

            channel_config = self.schedule.get("channel", {})

            lead_in_phase = None
            lead_in_next_event = None

            if (
                bool(channel_config.get("lead_in_enabled", False))
                and next_event
                and next_event.get("kind")
                in {"sports_blitz", "elite_blitz", "after_dark"}
            ):
                seconds_until = int(
                    next_event.get("seconds_until", 999999)
                )

                join_before = int(
                    channel_config.get(
                        "join_before_mini_seconds",
                        600,
                    )
                )

                mini_start = int(
                    channel_config.get(
                        "mini_game_start_seconds",
                        420,
                    )
                )

                teams_ready = int(
                    channel_config.get(
                        "teams_ready_seconds",
                        360,
                    )
                )

                if 0 < seconds_until <= join_before:
                    lead_in_next_event = dict(next_event)

                    if seconds_until > mini_start:
                        lead_in_phase = "join"

                    elif seconds_until > teams_ready:
                        lead_in_phase = "mini_game"

                    else:
                        lead_in_phase = "teams_ready"

            # -------------------------------------------------
            # NORMAL SCHEDULER STATE
            # -------------------------------------------------

            program_id = program.get(
                "id",
                "elite_channel",
            )

            if program_id != self.last_program_id:
                self._record_event_locked(
                    f"SCHEDULE â†’ "
                    f"{program.get('title', program_id)}",
                    now,
                )

                self.last_program_id = program_id

            did_you_know = self.schedule.get(
                "did_you_know",
                [],
            )

            fact_seconds = max(
                8,
                int(
                    self.schedule
                    .get("channel", {})
                    .get("fact_seconds", 18)
                ),
            )

            filler_seconds = max(
                8,
                int(
                    self.schedule
                    .get("channel", {})
                    .get("filler_seconds", 14)
                ),
            )

            # Use a small daily set of facts, not a new fact every
            # few seconds. The broadcast day starts at 11 AM and
            # continues through 2 AM, including across midnight.
            fact_daily_count = max(
                1,
                int(
                    self.schedule.get("channel", {}).get(
                        "fact_daily_count", 3
                    )
                ),
            )
            broadcast_day = (
                now.date()
                if now.hour >= 11
                else (now - timedelta(days=1)).date()
            )
            broadcast_hour = (now.hour - 11) % 24
            if did_you_know:
                daily_start = (
                    broadcast_day.toordinal() * fact_daily_count
                ) % len(did_you_know)
                fact_index = (
                    daily_start + (now.minute // 20) % fact_daily_count
                ) % len(did_you_know)
            else:
                fact_index = 0

            # =================================================
            # ELITE NETWORK CHANNEL CONTENT ENGINE
            # =================================================

            channel_config = (
                self.schedule
                .get(
                    "channel",
                    {},
                )
            )

            content_rotation = (
                channel_config.get(
                    "content_rotation"
                )
                or [
                    "did_you_know",
                    "sponsor",
                    "tv_guide",
                    "coming_up",
                ]
            )

            content_folders = (
                channel_config.get(
                    "content_folders",
                    {},
                )
                or {}
            )

            image_extensions = {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
            }

            video_extensions = {
                ".mp4",
                ".webm",
            }

            media_cache = {}

            def get_media_items(kind):

                if kind in media_cache:
                    return media_cache[kind]

                rel_folder = (
                    content_folders.get(
                        kind
                    )
                )

                if not rel_folder:
                    media_cache[kind] = []
                    return []

                folder = (
                    BASE_DIR
                    / rel_folder
                ).resolve()

                try:
                    safe = (
                        folder == BASE_DIR
                        or
                        BASE_DIR in folder.parents
                    )
                except Exception:
                    safe = False

                if (
                    not safe
                    or
                    not folder.is_dir()
                ):
                    media_cache[kind] = []
                    return []

                allowed = (
                    video_extensions
                    if kind == "funny_clip"
                    else image_extensions
                )

                items = sorted(
                    [
                        item
                        for item
                        in folder.iterdir()
                        if (
                            item.is_file()
                            and
                            item.suffix.lower()
                            in allowed
                        )
                    ],
                    key=lambda p:
                        p.name.lower(),
                )

                media_cache[kind] = items

                return items


            def minute_from_text(value):

                hour, minute = (
                    str(value)
                    .split(":", 1)
                )

                return (
                    int(hour) * 60
                    + int(minute)
                )


            def time_inside_window(
                minute_now,
                start_text,
                end_text,
            ):

                start_minute = (
                    minute_from_text(
                        start_text
                    )
                )

                end_minute = (
                    minute_from_text(
                        end_text
                    )
                )

                if (
                    start_minute
                    <=
                    end_minute
                ):
                    return (
                        start_minute
                        <=
                        minute_now
                        <
                        end_minute
                    )

                return (
                    minute_now
                    >=
                    start_minute
                    or
                    minute_now
                    <
                    end_minute
                )


            minute_now = (
                now.hour * 60
                + now.minute
            )

            network_start = (
                channel_config.get(
                    "network_start",
                    "11:00",
                )
            )

            network_end = (
                channel_config.get(
                    "network_end",
                    "02:00",
                )
            )

            network_on_air = (
                time_inside_window(
                    minute_now,
                    network_start,
                    network_end,
                )
            )


            # Standard between-cue filler is deliberately limited to
            # timeless screens. Facts, clips, sponsors, venue slides,
            # and promotions each get explicit hourly airtime instead
            # of repeating in a 1-2 minute tight loop.
            available_rotation = []
            for kind in content_rotation:
                if kind in {"tv_guide", "coming_up"}:
                    available_rotation.append(kind)
                elif kind in {"live_event", "promo", "sponsor"}:
                    if get_media_items(kind):
                        available_rotation.append(kind)

            if not available_rotation:
                available_rotation = ["tv_guide", "coming_up"]


            # Different content can have
            # different screen durations.
            def content_duration(kind):

                if kind == "tv_guide":
                    return 20

                if kind == "did_you_know":
                    return fact_seconds

                if kind == "funny_clip":
                    return max(
                        8,
                        int(
                            channel_config.get(
                                "funny_clip_seconds",
                                30,
                            )
                        ),
                    )

                return filler_seconds


            durations = [
                content_duration(kind)
                for kind
                in available_rotation
            ]

            total_cycle_seconds = max(
                1,
                sum(durations),
            )

            monotonic_seconds = int(
                time.monotonic()
                + self.channel_content_offset_seconds
            )

            cycle_position = (
                monotonic_seconds
                % total_cycle_seconds
            )

            filler_type = (
                available_rotation[0]
            )

            selected_position = 0

            cursor = 0
            filler_remaining_seconds = 0.0

            for index, kind in enumerate(
                available_rotation
            ):

                duration = durations[index]

                if (
                    cycle_position
                    <
                    cursor + duration
                ):
                    filler_type = kind
                    selected_position = index

                    filler_remaining_seconds = max(
                        0.0,
                        float(
                            cursor
                            + duration
                            - cycle_position
                        ),
                    )

                    break

                cursor += duration


            content_item = None

            selected_items = (
                get_media_items(
                    filler_type
                )
            )

            if selected_items:

                cycle_number = (
                    monotonic_seconds
                    //
                    total_cycle_seconds
                )

                media_index = (
                    cycle_number
                    + selected_position
                ) % len(selected_items)

                media_file = (
                    selected_items[
                        media_index
                    ]
                )

                content_item = {
                    "kind":
                        filler_type,

                    "index":
                        media_index,

                    "filename":
                        media_file.name,

                    "media_type":
                        (
                            "video"
                            if
                            media_file.suffix.lower()
                            in video_extensions
                            else
                            "image"
                        ),

                    "url":
                        (
                            f"/channel-content/"
                            f"{filler_type}/"
                            f"{media_index}"
                        ),
                }


            hourly_funny_slot = None

            if network_on_air:
                # Each slot is a brief cue at a wall-clock minute.
                # When the Network is showing a trivia game or
                # mini-game, those have display priority.
                cues = [
                    (
                        "sponsor",
                        "sponsor_minutes_of_hour",
                        filler_seconds,
                    ),
                    (
                        "live_event",
                        "venue_minutes_of_hour",
                        filler_seconds,
                    ),
                    (
                        "promo",
                        "promo_minutes_of_hour",
                        filler_seconds,
                    ),
                    (
                        "did_you_know",
                        "fact_minutes_of_hour",
                        fact_seconds,
                    ),
                    (
                        "funny_clip",
                        "funny_clip_minutes_of_hour",
                        max(
                            8,
                            int(channel_config.get("funny_clip_seconds", 30)),
                        ),
                    ),
                ]

                for cue_kind, cue_key, cue_length in cues:
                    cue_minutes = channel_config.get(cue_key, [])
                    if (
                        now.minute not in cue_minutes
                        or now.second >= min(60, cue_length)
                    ):
                        continue

                    items = get_media_items(cue_kind)
                    if cue_kind in {"funny_clip", "promo", "live_event"} and not items:
                        continue
                    if cue_kind == "did_you_know" and not did_you_know:
                        continue

                    cue_slot = now.strftime("%Y-%m-%dT%H:%M")
                    if (
                        cue_kind == "funny_clip"
                        and cue_slot == self.finished_hourly_funny_slot
                    ):
                        continue

                    filler_type = cue_kind
                    filler_remaining_seconds = max(
                        0.0,
                        float(cue_length) - now.second - now.microsecond / 1e6,
                    )
                    content_item = None

                    if items:
                        # Choose a different media item at successive
                        # hourly cues, staying stable during that cue.
                        sequence = (
                            broadcast_day.toordinal() * 37
                            + broadcast_hour * max(1, len(cue_minutes))
                            + cue_minutes.index(now.minute)
                        )
                        media_index = sequence % len(items)
                        media_file = items[media_index]
                        content_item = {
                            "kind": cue_kind,
                            "index": media_index,
                            "filename": media_file.name,
                            "media_type": (
                                "video"
                                if media_file.suffix.lower() in video_extensions
                                else "image"
                            ),
                            "url": f"/channel-content/{cue_kind}/{media_index}",
                        }

                    if cue_kind == "funny_clip":
                        hourly_funny_slot = cue_slot

                    break

            else:
                filler_type = "off_air"
                content_item = None

            return {
                "simulated":
                    self.simulated,

                "clock_revision":
                    self.clock_revision,

                "timezone":
                    str(
                        getattr(
                            self.timezone,
                            "key",
                            self.timezone,
                        )
                    ),

                "now_iso":
                    now.isoformat(),

                "now_display":
                    now.strftime(
                        "%A â€¢ %I:%M:%S %p"
                    ).replace(
                        " 0",
                        " ",
                    ),

                "program":
                    program,

                "next_event":
                    next_event,

                "lead_in_phase":
                    lead_in_phase,

                "lead_in_next_event":
                    lead_in_next_event,

                "today_guide":
                    self._today_guide_locked(
                        now
                    ),

                "filler_type":
                    filler_type,

                "content_item":
                    content_item,

                "filler_remaining_seconds":
                    filler_remaining_seconds,

                "hourly_funny_slot":
                    hourly_funny_slot,

                "network_on_air":
                    network_on_air,

                "did_you_know":
                    (
                        did_you_know[
                            fact_index
                        ]
                        if did_you_know
                        else ""
                    ),

                "event_log":
                    list(
                        self.event_log
                    ),
            }


class MiniGameController:
    """
    Server-authoritative Elite Network mini-game controller.

    Supported:
    - quick_3
    - reaction_rush
    """

    def __init__(
        self,
        questions,
        event_callback=None,
        team_provider=None,
    ):

        self.lock = threading.RLock()
        self.event_callback = event_callback
        self.team_provider = team_provider

        eligible = []

        for q in questions:

            choices = list(
                q.get("choices") or []
            )

            if len(choices) < 4:
                continue

            if q.get("type") in (
                "roulette",
                "final_wager",
            ):
                continue

            eligible.append(
                {
                    "category":
                        q.get(
                            "category",
                            "TRIVIA",
                        ),

                    "question":
                        q.get(
                            "question",
                            "",
                        ),

                    "choices":
                        choices[:4],

                    "correct_index":
                        int(
                            q.get(
                                "correct_index",
                                0,
                            )
                        ),

                    "answer_display":
                        q.get(
                            "answer_display",
                            "",
                        ),
                }
            )

            if len(eligible) >= 3:
                break


        self.questions = eligible

        self.active = False
        self.phase = "idle"

        self.game_type = "quick_3"
        self.title = "ELITE QUICK 3"

        self.question_index = 0

        self.deadline = None
        self.started_reason = ""

        self.responses = {}

        self.intro_seconds = 5.0
        self.question_seconds = 12.0
        self.reveal_seconds = 5.0
        self.outro_seconds = 6.0

        # Reaction Rush state.
        self.reaction_go_started = None
        self.reaction_wait_seconds = 3.0
        self.reaction_window_seconds = 4.0

        # Skee-Ball Challenge state.
        self.skee_queue = []
        self.skee_current_index = 0
        self.skee_scores = {}
        self.skee_throws = {}
        self.skee_balls_per_team = 3
        self.skee_turn_timeout_seconds = 20.0

        self.skee_last_result = None

        self.skee_control_seq = 0
        self.skee_control = None


    def _get_skee_teams(self):

        teams = []

        if self.team_provider is None:
            return teams

        raw_teams = (
            self.team_provider()
            or []
        )

        for team in raw_teams:

            if not team.get(
                "active",
                True,
            ):
                continue

            if not team.get(
                "connected",
                True,
            ):
                continue

            teams.append(
                {
                    "id":
                        str(
                            team.get(
                                "id",
                                "",
                            )
                        ),

                    "number":
                        int(
                            team.get(
                                "number",
                                0,
                            )
                            or 0
                        ),

                    "name":
                        str(
                            team.get(
                                "name",
                                "TEAM",
                            )
                        ),
                }
            )

        import random

        random.shuffle(
            teams
        )

        return teams[:6]


    def _log(
        self,
        text,
    ):

        if self.event_callback:
            self.event_callback(
                text
            )


    def start(
        self,
        reason="manual",
        game_type="quick_3",
    ):

        with self.lock:

            game_type = (
                str(
                    game_type or "quick_3"
                )
                .strip()
                .lower()
            )

            if game_type not in (
                "quick_3",
                "reaction_rush",
                "skee_ball",
            ):

                raise ValueError(
                    f"Unknown mini-game type: "
                    f"{game_type}"
                )


            if (
                game_type == "quick_3"
                and
                not self.questions
            ):

                raise ValueError(
                    "No eligible mini-game "
                    "questions were found."
                )


            self.game_type = game_type

            self.active = True
            self.phase = "intro"

            self.question_index = 0

            self.responses = {}

            self.started_reason = reason

            self.reaction_go_started = None


            if game_type == "skee_ball":

                teams = self._get_skee_teams()

                if not teams:
                    raise ValueError(
                        "No active teams are available "
                        "for Skee-Ball."
                    )

                self.title = (
                    "ELITE SKEE-BALL CHALLENGE"
                )

                self.skee_queue = teams
                self.skee_current_index = 0

                self.skee_scores = {
                    team["id"]: 0
                    for team in teams
                }

                self.skee_throws = {
                    team["id"]: []
                    for team in teams
                }

                self.skee_last_result = None
                self.skee_control_seq = 0
                self.skee_control = None

                self.deadline = (
                    time.monotonic()
                    + 4.0
                )

                self._log(
                    "MINI-GAME -> "
                    "ELITE SKEE-BALL CHALLENGE"
                )


            elif game_type == "reaction_rush":

                import random

                self.title = (
                    "ELITE REACTION RUSH"
                )

                self.reaction_wait_seconds = (
                    random.uniform(
                        2.0,
                        5.0,
                    )
                )

                self.deadline = (
                    time.monotonic()
                    + 4.0
                )

                self._log(
                    "MINI-GAME -> "
                    "ELITE REACTION RUSH"
                )

            else:

                self.title = (
                    "ELITE QUICK 3"
                )

                self.deadline = (
                    time.monotonic()
                    + self.intro_seconds
                )

                self._log(
                    "MINI-GAME -> "
                    "ELITE QUICK 3"
                )


    def stop(
        self,
        reason="",
    ):

        with self.lock:

            was_active = (
                self.active
            )

            self.active = False
            self.phase = "idle"

            self.deadline = None
            self.reaction_go_started = None

            if (
                was_active
                and
                reason
            ):

                self._log(
                    "MINI-GAME END -> "
                    + str(reason)
                )


    def tick(self):

        with self.lock:

            if (
                not self.active
                or
                self.deadline is None
            ):
                return


            now = time.monotonic()

            if now < self.deadline:
                return


            # ================================================
            # SKEE-BALL
            # ================================================

            if (
                self.game_type
                == "skee_ball"
            ):

                if self.phase == "intro":

                    self.phase = "turn"
                    self.deadline = (
                        now
                        + self.skee_turn_timeout_seconds
                    )

                    return


                if self.phase == "between_turns":

                    self.phase = "turn"
                    self.deadline = (
                        now
                        + self.skee_turn_timeout_seconds
                    )

                    return


                if self.phase == "turn":

                    current_team = None

                    if (
                        self.skee_queue
                        and
                        self.skee_current_index
                        < len(self.skee_queue)
                    ):
                        current_team = (
                            self.skee_queue[
                                self.skee_current_index
                            ]
                        )

                    if current_team:

                        team_id = current_team["id"]

                        throws = self.skee_throws.get(
                            team_id,
                            [],
                        )

                        self._log(
                            "SKEE-BALL TIMEOUT -> "
                            + current_team["name"]
                        )

                        # Move to the next team if one remains.
                        if (
                            self.skee_current_index
                            <
                            len(self.skee_queue) - 1
                        ):

                            self.skee_current_index += 1
                            self.phase = "between_turns"
                            self.deadline = (
                                now + 3.0
                            )

                        else:

                            self.phase = "outro"
                            self.deadline = (
                                now + 7.0
                            )

                    else:

                        self.phase = "outro"
                        self.deadline = (
                            now + 7.0
                        )

                    return


                if self.phase == "outro":

                    self.active = False
                    self.phase = "idle"
                    self.deadline = None

                    self._log(
                        "MINI-GAME COMPLETE "
                        "-> CHANNEL"
                    )

                    return


                return


            # ================================================
            # REACTION RUSH
            # ================================================

            if (
                self.game_type
                == "reaction_rush"
            ):

                if self.phase == "intro":

                    self.phase = "waiting"

                    self.deadline = (
                        now
                        + self.reaction_wait_seconds
                    )

                    return


                if self.phase == "waiting":

                    self.phase = "question"

                    self.reaction_go_started = (
                        now
                    )

                    self.deadline = (
                        now
                        + self.reaction_window_seconds
                    )

                    return


                if self.phase == "question":

                    self.phase = "reveal"

                    self.deadline = (
                        now
                        + 5.0
                    )

                    return


                if self.phase == "reveal":

                    self.phase = "outro"

                    self.deadline = (
                        now
                        + 5.0
                    )

                    return


                if self.phase == "outro":

                    self.active = False
                    self.phase = "idle"

                    self.deadline = None

                    self._log(
                        "MINI-GAME COMPLETE "
                        "-> CHANNEL"
                    )

                    return


            # ================================================
            # QUICK 3
            # ================================================

            if self.phase == "intro":

                self.phase = "question"

                self.deadline = (
                    now
                    + self.question_seconds
                )

                return


            if self.phase == "question":

                self.phase = "reveal"

                self.deadline = (
                    now
                    + self.reveal_seconds
                )

                return


            if self.phase == "reveal":

                if (
                    self.question_index
                    >=
                    len(self.questions) - 1
                ):

                    self.phase = "outro"

                    self.deadline = (
                        now
                        + self.outro_seconds
                    )

                else:

                    self.question_index += 1

                    self.phase = "question"

                    self.deadline = (
                        now
                        + self.question_seconds
                    )

                return


            if self.phase == "outro":

                self.active = False
                self.phase = "idle"

                self.deadline = None

                self._log(
                    "MINI-GAME COMPLETE "
                    "-> CHANNEL"
                )


    def submit_skee_control(
        self,
        team_id,
        action,
    ):

        with self.lock:

            if (
                not self.active
                or
                self.game_type != "skee_ball"
            ):
                raise ValueError(
                    "Skee-Ball is not active."
                )

            if self.phase != "turn":
                raise ValueError(
                    "Skee-Ball controls are not active yet."
                )

            if (
                not self.skee_queue
                or
                self.skee_current_index
                >= len(self.skee_queue)
            ):
                raise ValueError(
                    "No Skee-Ball shooter is active."
                )

            current_team = (
                self.skee_queue[
                    self.skee_current_index
                ]
            )

            if (
                str(team_id)
                !=
                str(current_team["id"])
            ):
                raise ValueError(
                    "It is not your Skee-Ball turn."
                )

            action = (
                str(action or "")
                .strip()
                .lower()
            )

            if action not in (
                "left",
                "right",
                "charge_start",
                "throw",
            ):
                raise ValueError(
                    "Invalid Skee-Ball control."
                )

            self.skee_control_seq += 1

            self.skee_control = {
                "seq":
                    self.skee_control_seq,

                "team_id":
                    str(team_id),

                "action":
                    action,
            }

            # Any real controller activity keeps
            # this player's turn alive.
            self.deadline = (
                time.monotonic()
                + self.skee_turn_timeout_seconds
            )

            return dict(
                self.skee_control
            )


    def register_skee_result(
        self,
        points,
    ):

        with self.lock:

            if (
                not self.active
                or
                self.game_type != "skee_ball"
            ):
                raise ValueError(
                    "Skee-Ball is not active."
                )


            if self.phase != "turn":
                raise ValueError(
                    "Skee-Ball is not accepting "
                    "a shot result right now."
                )


            try:
                points = int(
                    points
                )

            except Exception:
                raise ValueError(
                    "Invalid Skee-Ball score."
                )


            allowed_scores = {
                0,
                20,
                30,
                40,
                50,
                100,
            }

            if points not in allowed_scores:
                raise ValueError(
                    "Invalid Skee-Ball score."
                )


            if (
                not self.skee_queue
                or
                self.skee_current_index
                >= len(self.skee_queue)
            ):
                raise ValueError(
                    "No Skee-Ball shooter is active."
                )


            team = self.skee_queue[
                self.skee_current_index
            ]

            team_id = team["id"]

            throws = self.skee_throws[
                team_id
            ]


            if (
                len(throws)
                >=
                self.skee_balls_per_team
            ):
                raise ValueError(
                    "That team's Skee-Ball "
                    "turn is already complete."
                )


            throws.append(
                points
            )

            self.skee_scores[
                team_id
            ] += points

            # Successful activity keeps this team's
            # turn alive for the next ball.
            self.deadline = (
                time.monotonic()
                + self.skee_turn_timeout_seconds
            )


            self.skee_last_result = {
                "team_id":
                    team_id,

                "number":
                    team["number"],

                "name":
                    team["name"],

                "points":
                    points,

                "ball_number":
                    len(throws),

                "team_score":
                    self.skee_scores[
                        team_id
                    ],
            }


            turn_complete = (
                len(throws)
                >=
                self.skee_balls_per_team
            )


            game_complete = False


            if turn_complete:

                if (
                    self.skee_current_index
                    <
                    len(self.skee_queue) - 1
                ):

                    self.skee_current_index += 1

                    self.phase = (
                        "between_turns"
                    )

                    self.deadline = (
                        time.monotonic()
                        + 3.0
                    )

                else:

                    game_complete = True

                    self.phase = "outro"

                    self.deadline = (
                        time.monotonic()
                        + 7.0
                    )


            return {
                "ok":
                    True,

                "result":
                    dict(
                        self.skee_last_result
                    ),

                "turn_complete":
                    turn_complete,

                "game_complete":
                    game_complete,

                "next_team":
                    (
                        dict(
                            self.skee_queue[
                                self.skee_current_index
                            ]
                        )
                        if (
                            not game_complete
                            and
                            self.skee_queue
                        )
                        else None
                    ),
            }


    def submit_answer(
        self,
        team_id,
        choice_index,
    ):

        with self.lock:

            if not self.active:

                raise ValueError(
                    "The mini-game is not active."
                )


            # ================================================
            # REACTION RUSH
            # ================================================

            if (
                self.game_type
                == "reaction_rush"
            ):

                if self.phase != "question":

                    raise ValueError(
                        "WAIT FOR GO!"
                    )


                team_key = str(
                    team_id
                )

                response_key = (
                    0,
                    team_key,
                )


                if response_key in self.responses:

                    raise ValueError(
                        "Your reaction is already locked in."
                    )


                if self.reaction_go_started is None:

                    raise ValueError(
                        "Reaction timer is not ready."
                    )


                reaction_seconds = max(
                    0.0,
                    time.monotonic()
                    - self.reaction_go_started,
                )


                prior = [
                    response
                    for response
                    in self.responses.values()
                    if (
                        response.get(
                            "reaction_seconds"
                        )
                        is not None
                    )
                ]


                rank = (
                    len(prior)
                    + 1
                )


                response = {
                    "team_id":
                        team_key,

                    "question_index":
                        0,

                    "choice_index":
                        0,

                    "correct":
                        True,

                    "reaction_seconds":
                        round(
                            reaction_seconds,
                            3,
                        ),

                    "rank":
                        rank,
                }


                self.responses[
                    response_key
                ] = response


                return dict(
                    response
                )


            # ================================================
            # QUICK 3
            # ================================================

            if self.phase != "question":

                raise ValueError(
                    "Mini-game answers are not open."
                )


            if not isinstance(
                choice_index,
                int,
            ):

                raise ValueError(
                    "Invalid mini-game answer."
                )


            question = self.questions[
                self.question_index
            ]


            choices = question.get(
                "choices",
                [],
            )


            if (
                choice_index < 0
                or
                choice_index >= len(choices)
            ):

                raise ValueError(
                    "Invalid mini-game answer."
                )


            response_key = (
                self.question_index,
                str(team_id),
            )


            if response_key in self.responses:

                raise ValueError(
                    "Your mini-game answer "
                    "is already locked in."
                )


            response = {
                "team_id":
                    str(team_id),

                "question_index":
                    self.question_index,

                "choice_index":
                    choice_index,

                "correct":
                    choice_index
                    ==
                    int(
                        question.get(
                            "correct_index",
                            -1,
                        )
                    ),
            }


            self.responses[
                response_key
            ] = response


            return dict(
                response
            )


    def get_team_response(
        self,
        team_id,
    ):

        with self.lock:

            if not team_id:
                return None


            question_index = (
                0
                if (
                    self.game_type
                    == "reaction_rush"
                )
                else
                self.question_index
            )


            response = (
                self.responses.get(
                    (
                        question_index,
                        str(team_id),
                    )
                )
            )


            return (
                dict(response)
                if response
                else None
            )


    def _reaction_leaderboard(
        self,
    ):

        rows = [
            dict(response)
            for response
            in self.responses.values()
            if (
                response.get(
                    "reaction_seconds"
                )
                is not None
            )
        ]


        rows.sort(
            key=lambda row:
                float(
                    row[
                        "reaction_seconds"
                    ]
                )
        )


        for index, row in enumerate(
            rows,
            start=1,
        ):

            row["rank"] = index


        return rows[:5]


    def snapshot(self):

        with self.lock:

            remaining = 0.0

            if (
                self.active
                and
                self.deadline is not None
            ):

                remaining = max(
                    0.0,
                    self.deadline
                    - time.monotonic(),
                )


            # ================================================
            # SKEE-BALL SNAPSHOT
            # ================================================

            if (
                self.game_type
                == "skee_ball"
            ):

                current_team = None

                if (
                    self.active
                    and
                    self.skee_queue
                    and
                    self.skee_current_index
                    <
                    len(self.skee_queue)
                ):

                    current_team = dict(
                        self.skee_queue[
                            self.skee_current_index
                        ]
                    )


                leaderboard = []

                for team in self.skee_queue:

                    team_id = team["id"]

                    leaderboard.append(
                        {
                            "team_id":
                                team_id,

                            "number":
                                team["number"],

                            "name":
                                team["name"],

                            "score":
                                int(
                                    self.skee_scores.get(
                                        team_id,
                                        0,
                                    )
                                ),

                            "throws":
                                list(
                                    self.skee_throws.get(
                                        team_id,
                                        [],
                                    )
                                ),
                        }
                    )


                leaderboard.sort(
                    key=lambda row:
                        (
                            -row["score"],
                            row["number"],
                        )
                )


                balls_used = 0

                if current_team:

                    balls_used = len(
                        self.skee_throws.get(
                            current_team["id"],
                            [],
                        )
                    )


                return {
                    "active":
                        self.active,

                    "game_type":
                        "skee_ball",

                    "title":
                        self.title,

                    "phase":
                        self.phase,

                    "seconds_remaining":
                        round(
                            remaining,
                            2,
                        ),

                    "current_team":
                        current_team,

                    "current_team_index":
                        self.skee_current_index,

                    "team_count":
                        len(
                            self.skee_queue
                        ),

                    "balls_per_team":
                        self.skee_balls_per_team,

                    "ball_number":
                        min(
                            balls_used + 1,
                            self.skee_balls_per_team,
                        ),

                    "balls_remaining":
                        max(
                            0,
                            self.skee_balls_per_team
                            - balls_used,
                        ),

                    "queue":
                        [
                            dict(team)
                            for team
                            in self.skee_queue
                        ],

                    "leaderboard":
                        leaderboard,

                    "control_seq":
                        self.skee_control_seq,

                    "control":
                        (
                            dict(
                                self.skee_control
                            )
                            if self.skee_control
                            else None
                        ),

                    "last_result":
                        (
                            dict(
                                self.skee_last_result
                            )
                            if self.skee_last_result
                            else None
                        ),

                    "started_reason":
                        self.started_reason,
                }


            # ================================================
            # REACTION RUSH SNAPSHOT
            # ================================================

            if (
                self.game_type
                == "reaction_rush"
            ):

                q = None

                if self.active:

                    q = {
                        "category":
                            "REACTION RUSH",

                        "question":
                            (
                                "TAP NOW!"
                                if self.phase
                                == "question"
                                else
                                "WAIT FOR GO"
                            ),

                        "choices":
                            [],

                        "correct_index":
                            0,

                        "answer_display":
                            "",
                    }


                return {
                    "active":
                        self.active,

                    "game_type":
                        "reaction_rush",

                    "title":
                        self.title,

                    "phase":
                        self.phase,

                    "question_index":
                        0,

                    "question_number":
                        1,

                    "question_count":
                        1,

                    "seconds_remaining":
                        round(
                            remaining,
                            2,
                        ),

                    "question":
                        q,

                    "leaderboard":
                        self._reaction_leaderboard(),

                    "response_count":
                        len(
                            self.responses
                        ),

                    "started_reason":
                        self.started_reason,
                }


            # ================================================
            # QUICK 3 SNAPSHOT
            # ================================================

            q = None

            if (
                self.active
                and
                self.questions
            ):

                q = dict(
                    self.questions[
                        self.question_index
                    ]
                )


            return {
                "active":
                    self.active,

                "game_type":
                    "quick_3",

                "title":
                    "ELITE QUICK 3",

                "phase":
                    self.phase,

                "question_index":
                    self.question_index,

                "question_number":
                    self.question_index + 1,

                "question_count":
                    len(
                        self.questions
                    ),

                "seconds_remaining":
                    round(
                        remaining,
                        2,
                    ),

                "question":
                    q,

                "started_reason":
                    self.started_reason,
            }

def load_game_data():
    with DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions", [])
    if not questions:
        raise ValueError("game_data.json contains no questions.")
    return data


def get_local_ip():
    """Best-effort LAN IPv4 address for the local player/TV URLs."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    finally:
        sock.close()

    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for info in infos:
            ip = info[4][0]
            if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except OSError:
        pass

    return "127.0.0.1"


class GameEngine:
    """Server-authoritative local Auto Elite game engine."""

    def __init__(self, game_data):
        self.lock = threading.RLock()
        self.game_title = game_data.get("game_title", "Auto Elite")
        self.questions = game_data["questions"]
        self.current_question_index = 0

        settings = game_data.get("settings", {})
        self.still_playing_prompt_after_misses = max(
            1, int(settings.get("still_playing_prompt_after_misses", 2))
        )
        self.inactive_after_misses = max(
            self.still_playing_prompt_after_misses + 1,
            int(settings.get("inactive_after_misses", 3)),
        )
        self.inactive_after_seconds = max(
            0.0, float(settings.get("inactive_after_seconds", 300))
        )

        auto_settings = settings.get("auto_flow", {})
        self.auto_category_seconds = max(0.5, float(auto_settings.get("category_seconds", 5)))
        self.auto_reveal_seconds = max(0.5, float(auto_settings.get("reveal_seconds", 5)))
        self.auto_scoreboard_seconds = max(0.5, float(auto_settings.get("scoreboard_seconds", 7)))
        self.auto_round_complete_seconds = max(0.5, float(auto_settings.get("round_complete_seconds", 5)))
        self.auto_sociable_seconds = max(0.5, float(auto_settings.get("sociable_seconds", 5)))
        self.sociable_min_teams = max(2, int(settings.get("sociable_min_teams", 2)))

        # TV text sizing stays data-driven so Admin can expose these later.
        display_settings = settings.get("display", {})
        self.display_settings = {
            "category_max_px": int(display_settings.get("category_max_px", 112)),
            "category_min_px": int(display_settings.get("category_min_px", 42)),
            "question_max_px": int(display_settings.get("question_max_px", 58)),
            "question_min_px": int(display_settings.get("question_min_px", 26)),
            "answer_max_px": int(display_settings.get("answer_max_px", 40)),
            "answer_min_px": int(display_settings.get("answer_min_px", 20)),
            "roulette_hint_max_px": int(display_settings.get("roulette_hint_max_px", 54)),
            "roulette_hint_min_px": int(display_settings.get("roulette_hint_min_px", 24)),
            "team_status_max_px": int(display_settings.get("team_status_max_px", 30)),
            "team_status_min_px": int(display_settings.get("team_status_min_px", 16)),
            "timer_px": int(display_settings.get("timer_px", 64)),
            "points_px": int(display_settings.get("points_px", 50)),
        }
        self.rule_slides = [
            {"key": "welcome", "duration": 7.0},
            {"key": "how_to_answer", "duration": 7.0},
            {"key": "roulette", "duration": 7.0},
            {"key": "wager", "duration": 5.0},
            {"key": "tie_breaker", "duration": 7.0},
        ]
        self.rule_slide_index = None
        self.auto_game_running = False
        self.auto_deadline_monotonic = None
        self.auto_last_transition = ""

        # pregame | rules | category | wager | question | reveal | sociable |
        # speed_bonus | scores | round_complete | game_complete
        self.screen = "pregame"
        self.timer_running = False
        self.timer_started_monotonic = None
        self.timer_ends_monotonic = None
        self.timer_phase = None
        self.presentation_started_monotonic = None
        self.presentation_ends_monotonic = None

        self.teams = {}
        self.next_team_number = 1
        self.responses = {}
        self.wagers = {}
        self.adjustments = {}
        self.scoring_finalized = False

        self.status_message = "Waiting for teams"
        self.game_started = False
        self.server_session_id = secrets.token_urlsafe(12)
        self.version = 1

    @property
    def question(self):
        return self.questions[self.current_question_index]

    def _touch(self):
        self.version += 1

    def _is_roulette(self, q=None):
        q = q or self.question
        return q.get("type") == "roulette" or q.get("scoring_type") == "roulette"

    def _is_final_wager(self, q=None):
        q = q or self.question
        return q.get("type") == "final_wager" or q.get("scoring_type") == "final_wager"

    def _scoring_type(self, q=None):
        q = q or self.question
        if self._is_roulette(q):
            return "roulette"
        if self._is_final_wager(q):
            return "final_wager"
        return q.get("scoring_type", "fixed")

    def _timer_duration_for_screen_locked(self):
        if self.screen == "wager":
            return float(self.question.get("wager_seconds", 30))
        return float(self.question.get("timer_seconds", 120))

    def _remaining_locked(self):
        if not self.timer_running or self.timer_ends_monotonic is None:
            return 0.0
        return max(0.0, self.timer_ends_monotonic - time.monotonic())

    def _round_half_up(self, value):
        return int(math.floor(float(value) + 0.5))

    def _fastest_points_for_elapsed_locked(self, elapsed=None):
        q = self.question
        if self._scoring_type(q) != "fastest":
            return None

        max_points = int(q.get("max_points", 10))
        min_points = int(q.get("min_points", 5))
        duration = max(0.001, float(q.get("timer_seconds", 120)))

        if elapsed is None:
            if self.timer_running and self.timer_started_monotonic is not None:
                elapsed = max(0.0, time.monotonic() - self.timer_started_monotonic)
            else:
                elapsed = 0.0

        progress = min(1.0, max(0.0, float(elapsed)) / duration)
        raw_points = max_points - ((max_points - min_points) * progress)
        points = self._round_half_up(raw_points)
        return max(min_points, min(max_points, points))

    def _fastest_display_value_locked(self):
        # Build 4A: Fastest Answer is displayed as whole-number points.
        return self._fastest_points_for_elapsed_locked()

    def _expire_timer_if_needed_locked(self):
        if self.timer_running and self.timer_ends_monotonic is not None:
            if time.monotonic() >= self.timer_ends_monotonic:
                phase = self.timer_phase
                self.timer_running = False
                self.timer_ends_monotonic = None
                self.timer_phase = None
                if phase == "wager":
                    self.status_message = "Wager time is up"
                else:
                    self.status_message = "Time is up"
                self._touch()

    def _stop_timer_locked(self, message=None):
        self.timer_running = False
        self.timer_ends_monotonic = None
        self.timer_started_monotonic = None
        self.timer_phase = None
        if message:
            self.status_message = message

    def _clear_question_state_locked(self):
        self.responses = {}
        self.wagers = {}
        self.adjustments = {}
        self.scoring_finalized = False
        self.presentation_started_monotonic = None
        self.presentation_ends_monotonic = None

    def _current_round_number(self):
        return int(self.question.get("round", 1))

    def _round_question_count(self, round_number=None):
        round_number = round_number or self._current_round_number()
        return sum(1 for q in self.questions if int(q.get("round", 1)) == int(round_number))

    def _current_is_last_in_round(self):
        if self.current_question_index >= len(self.questions) - 1:
            return True
        current_round = int(self.question.get("round", 1))
        next_round = int(self.questions[self.current_question_index + 1].get("round", current_round))
        return next_round != current_round

    def _speed_bonus_phone_seconds_locked(self):
        return max(0.5, float(self.question.get("speed_bonus_phone_seconds", 4)))

    def _speed_bonus_tv_seconds_locked(self):
        return max(0.5, float(self.question.get("speed_bonus_tv_seconds", 5)))

    def _speed_bonus_winners_locked(self):
        """Return only teams that actually earned a positive speed bonus, in finish order."""
        winners = []
        for receipt_order, (team_id, response) in enumerate(self.responses.items()):
            bonus = int(response.get("speed_bonus", 0) or 0)
            if bonus <= 0:
                continue
            team = self.teams.get(team_id)
            if not team:
                continue
            winners.append(
                (
                    int(response.get("response_ms", 0) or 0),
                    receipt_order,
                    team,
                    response,
                    bonus,
                )
            )

        winners.sort(key=lambda item: (item[0], item[1]))
        return [
            {
                "rank": index + 1,
                "team_id": team["id"],
                "number": team["number"],
                "name": team["name"],
                "bonus": bonus,
                "response_ms": response_ms,
                "question_points": int(response.get("score_delta", 0) or 0),
            }
            for index, (response_ms, _, team, response, bonus) in enumerate(winners)
        ]

    def _advance_presentation_if_needed_locked(self):
        if self.screen != "speed_bonus" or self.presentation_ends_monotonic is None:
            return
        if time.monotonic() < self.presentation_ends_monotonic:
            return
        self.presentation_started_monotonic = None
        self.presentation_ends_monotonic = None
        self.screen = "scores"
        self.status_message = "Scores shown"
        self._touch()

    def _current_rule_slide_locked(self):
        if self.rule_slide_index is None:
            return None
        if self.rule_slide_index < 0 or self.rule_slide_index >= len(self.rule_slides):
            return None
        return self.rule_slides[self.rule_slide_index]

    def _all_eligible_active_teams_correct_locked(self):
        if self._is_final_wager():
            return False
        eligible_ids = self._eligible_active_team_ids_locked()
        if len(eligible_ids) < self.sociable_min_teams:
            return False
        for team_id in eligible_ids:
            response = self.responses.get(team_id)
            if not response or not response.get("correct"):
                return False
        return True

    def _start_rules_sequence_locked(self):
        self._stop_timer_locked("Rules sequence")
        self.presentation_started_monotonic = None
        self.presentation_ends_monotonic = None
        self.game_started = True
        self.rule_slide_index = 0
        self.screen = "rules"
        slide = self._current_rule_slide_locked() or {"key": "welcome"}
        self.status_message = f"Rules slide: {slide['key'].replace('_', ' ').title()}"
        self._touch()

    # -----------------------------------------------------
    # FULL-GAME AUTOMATIC FLOW
    # -----------------------------------------------------

    def _set_auto_deadline_locked(self, seconds, label=""):
        self.auto_deadline_monotonic = time.monotonic() + max(0.0, float(seconds))
        self.auto_last_transition = label

    def _auto_seconds_remaining_locked(self):
        if not self.auto_game_running or self.auto_deadline_monotonic is None:
            return 0.0
        return max(0.0, self.auto_deadline_monotonic - time.monotonic())

    def _stop_auto_game_locked(self, message=None):
        self.auto_game_running = False
        self.auto_deadline_monotonic = None
        self.auto_last_transition = ""
        if message:
            self.status_message = message
        self._touch()

    def start_auto_game(self):
        with self.lock:
            if self.screen == "game_complete":
                raise ValueError("Reset the game before starting Full Auto.")

            self.auto_game_running = True
            self.game_started = True

            if self.screen == "pregame":
                self._start_rules_sequence_locked()
                slide = self._current_rule_slide_locked() or {"duration": 5.0}
                self._set_auto_deadline_locked(slide.get("duration", 5.0), "rules")
            elif self.screen == "rules":
                slide = self._current_rule_slide_locked() or {"duration": 5.0}
                self._set_auto_deadline_locked(slide.get("duration", 5.0), "rules")
            elif self.screen == "category":
                self._set_auto_deadline_locked(self.auto_category_seconds, "category")
            elif self.screen == "wager":
                if not self.timer_running:
                    self.show_wager()
                self.auto_deadline_monotonic = self.timer_ends_monotonic
                self.auto_last_transition = "wager"
            elif self.screen == "question":
                if not self.timer_running:
                    self.start_timer()
                self.auto_deadline_monotonic = self.timer_ends_monotonic
                self.auto_last_transition = "question"
            elif self.screen == "reveal":
                self._set_auto_deadline_locked(self.auto_reveal_seconds, "reveal")
            elif self.screen == "sociable":
                self._set_auto_deadline_locked(self.auto_sociable_seconds, "sociable")
            elif self.screen == "speed_bonus":
                self.auto_deadline_monotonic = self.presentation_ends_monotonic
                self.auto_last_transition = "speed_bonus"
            elif self.screen == "scores":
                self._set_auto_deadline_locked(self.auto_scoreboard_seconds, "scores")
            elif self.screen == "round_complete":
                self._set_auto_deadline_locked(self.auto_round_complete_seconds, "round_complete")

            self.status_message = "Full Auto game running"
            self._touch()

    def stop_auto_game(self):
        with self.lock:
            self._stop_auto_game_locked("Full Auto stopped - host control restored")

    def toggle_auto_game(self):
        with self.lock:
            if self.auto_game_running:
                self._stop_auto_game_locked("Full Auto stopped - host control restored")
                return False
        self.start_auto_game()
        return True

    def _auto_tick_locked(self):
        # Player activity can never hold the clock. Inactivity is refreshed here
        # even if no phone or TV is polling the server.
        self._refresh_inactivity_locked()
        self._expire_timer_if_needed_locked()
        self._advance_presentation_if_needed_locked()

        if not self.auto_game_running:
            return

        if self.screen == "game_complete":
            self._stop_auto_game_locked("Full Auto complete - game finished")
            return

        now = time.monotonic()

        if self.screen == "rules":
            slide = self._current_rule_slide_locked() or {"duration": 5.0}
            if self.auto_deadline_monotonic is None or self.auto_last_transition != "rules":
                self._set_auto_deadline_locked(slide.get("duration", 5.0), "rules")
                return
            if now < self.auto_deadline_monotonic:
                return

            if self.rule_slide_index is None:
                self.rule_slide_index = 0
            else:
                self.rule_slide_index += 1

            if self.rule_slide_index >= len(self.rule_slides):
                self.rule_slide_index = None
                self.show_category()
                self._set_auto_deadline_locked(self.auto_category_seconds, "category")
            else:
                slide = self._current_rule_slide_locked() or {"duration": 5.0}
                self.status_message = f"Rules slide: {slide['key'].replace('_', ' ').title()}"
                self._set_auto_deadline_locked(slide.get("duration", 5.0), "rules")
                self._touch()
            return

        if self.screen == "category":
            if self.auto_deadline_monotonic is None or self.auto_last_transition != "category":
                self._set_auto_deadline_locked(self.auto_category_seconds, "category")
                return
            if now < self.auto_deadline_monotonic:
                return

            if self._is_roulette():
                self.show_wager()
                self.auto_deadline_monotonic = self.timer_ends_monotonic
                self.auto_last_transition = "wager"
            else:
                self.show_question()
                self.start_timer()
                self.auto_deadline_monotonic = self.timer_ends_monotonic
                self.auto_last_transition = "question"
            return

        if self.screen == "wager":
            if self.timer_running:
                self.auto_deadline_monotonic = self.timer_ends_monotonic
                return
            # Missing wagers default to 0%. Inactive/missing phones never block play.
            self.show_question()
            self.start_timer()
            self.auto_deadline_monotonic = self.timer_ends_monotonic
            self.auto_last_transition = "question"
            return

        if self.screen == "question":
            if self.timer_running:
                self.auto_deadline_monotonic = self.timer_ends_monotonic
                return
            # Missing normal answers score 0. Missing Final Wager submissions keep
            # the team's points (SAVE default). The official timer is authoritative.
            self.reveal_answer()
            self._set_auto_deadline_locked(self.auto_reveal_seconds, "reveal")
            return

        if self.screen == "reveal":
            if self.auto_deadline_monotonic is None or self.auto_last_transition != "reveal":
                self._set_auto_deadline_locked(self.auto_reveal_seconds, "reveal")
                return
            if now < self.auto_deadline_monotonic:
                return

            if self._all_eligible_active_teams_correct_locked():
                self.screen = "sociable"
                self.status_message = "Blitz Sociable"
                self._set_auto_deadline_locked(self.auto_sociable_seconds, "sociable")
                self._touch()
            elif self.question.get("speed_bonus_points") and self._speed_bonus_winners_locked():
                self.show_speed_bonus()
                self.auto_deadline_monotonic = self.presentation_ends_monotonic
                self.auto_last_transition = "speed_bonus"
            else:
                self.show_scores()
                self._set_auto_deadline_locked(self.auto_scoreboard_seconds, "scores")
            return

        if self.screen == "sociable":
            if self.auto_last_transition != "sociable" or self.auto_deadline_monotonic is None:
                self._set_auto_deadline_locked(self.auto_sociable_seconds, "sociable")
                return
            if now < self.auto_deadline_monotonic:
                return

            if self.question.get("speed_bonus_points") and self._speed_bonus_winners_locked():
                self.show_speed_bonus()
                self.auto_deadline_monotonic = self.presentation_ends_monotonic
                self.auto_last_transition = "speed_bonus"
            else:
                self.show_scores()
                self._set_auto_deadline_locked(self.auto_scoreboard_seconds, "scores")
            return

        if self.screen == "speed_bonus":
            # Speed Bonus owns its own presentation timer. When it expires,
            # _advance_presentation_if_needed_locked() changes the state to scores.
            if self.presentation_ends_monotonic is not None:
                self.auto_deadline_monotonic = self.presentation_ends_monotonic
                return

        if self.screen == "scores":
            if self.auto_last_transition != "scores" or self.auto_deadline_monotonic is None:
                self._set_auto_deadline_locked(self.auto_scoreboard_seconds, "scores")
                return
            if now < self.auto_deadline_monotonic:
                return

            self.next_question()
            if self.screen == "round_complete":
                self._set_auto_deadline_locked(self.auto_round_complete_seconds, "round_complete")
            elif self.screen == "game_complete":
                self._stop_auto_game_locked("Full Auto complete - game finished")
            else:
                self._set_auto_deadline_locked(self.auto_category_seconds, "category")
            return

        if self.screen == "round_complete":
            if self.auto_last_transition != "round_complete" or self.auto_deadline_monotonic is None:
                self._set_auto_deadline_locked(self.auto_round_complete_seconds, "round_complete")
                return
            if now < self.auto_deadline_monotonic:
                return

            # A second Next Question call advances from the round-complete screen
            # to the first category of the next round.
            self.next_question()
            if self.screen == "game_complete":
                self._stop_auto_game_locked("Full Auto complete - game finished")
            else:
                self._set_auto_deadline_locked(self.auto_category_seconds, "category")
            return

    def automation_worker(self):
        while True:
            try:
                with self.lock:
                    self._auto_tick_locked()
            except Exception as exc:
                with self.lock:
                    self.auto_game_running = False
                    self.auto_deadline_monotonic = None
                    self.auto_last_transition = ""
                    self.status_message = f"AUTO FLOW ERROR: {exc}"
                    self._touch()
            time.sleep(0.05)

    def _normalize_typed_answer(self, text):
        value = str(text or "").strip().casefold()
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return " ".join(value.split())

    def _typed_answer_is_correct(self, q, answer_text):
        normalized = self._normalize_typed_answer(answer_text)
        accepted = q.get("accepted_answers", [])
        if not accepted and q.get("answer_display"):
            accepted = [q.get("answer_display")]
        normalized_accepted = {self._normalize_typed_answer(x) for x in accepted if str(x).strip()}
        return bool(normalized and normalized in normalized_accepted)

    def _wager_amount(self, base_score, percent):
        if percent == 0:
            return 0
        if percent == 50:
            return self._round_half_up(base_score * 0.5)
        if percent == 100:
            return int(base_score)
        raise ValueError("Wager must be 0%, 50%, or 100%.")

    def _team_eligible_for_current_question_locked(self, team):
        return bool(
            team.get("active", True)
            and int(team.get("eligible_from_question_index", 0))
            <= self.current_question_index
        )

    def _eligible_active_teams_locked(self):
        return [
            team
            for team in self.teams.values()
            if self._team_eligible_for_current_question_locked(team)
        ]

    def _eligible_active_team_ids_locked(self):
        return {team["id"] for team in self._eligible_active_teams_locked()}

    def _next_eligible_question_index_locked(self):
        if not self.game_started or self.screen in ("pregame", "category"):
            return self.current_question_index
        return min(self.current_question_index + 1, len(self.questions))

    def _record_real_interaction_locked(self, team):
        team["last_real_interaction_monotonic"] = time.monotonic()
        team["last_interaction_question_index"] = self.current_question_index
        team["consecutive_missed_questions"] = 0
        team["needs_still_playing"] = False

    def _refresh_inactivity_locked(self):
        now = time.monotonic()
        changed = False
        for team in self.teams.values():
            if not team.get("active", True):
                continue
            misses = int(team.get("consecutive_missed_questions", 0))
            if misses < self.inactive_after_misses:
                continue
            last_interaction = float(team.get("last_real_interaction_monotonic", now))
            if max(0.0, now - last_interaction) >= self.inactive_after_seconds:
                team["active"] = False
                team["needs_still_playing"] = True
                team["inactive_since_monotonic"] = now
                changed = True
        if changed:
            self.status_message = "Inactive teams removed from answer waiting"
            self._touch()

    def _require_team_can_play_current_locked(self, team):
        self._refresh_inactivity_locked()
        if not team.get("active", True):
            raise ValueError("Your team is paused for inactivity. Tap STILL PLAYING to return.")
        if not self._team_eligible_for_current_question_locked(team):
            raise ValueError("You're back in the game. You can answer starting with the next question.")

    def still_playing(self, team_id, device_token=None, server_session_id=None):
        with self.lock:
            team = self._authorized_team_locked(team_id, device_token, server_session_id)
            if team is None:
                raise ValueError("This phone is not attached to that team in the current game. Rejoin first.")
            was_inactive = not team.get("active", True)
            if was_inactive:
                team["active"] = True
                team["inactive_since_monotonic"] = None
                team["eligible_from_question_index"] = self._next_eligible_question_index_locked()
            self._record_real_interaction_locked(team)
            if was_inactive:
                if self._team_eligible_for_current_question_locked(team):
                    self.status_message = f"{team['name']} returned to the game"
                else:
                    self.status_message = f"{team['name']} returned - eligible next question"
            else:
                self.status_message = f"{team['name']} confirmed still playing"
            self._touch()
            return dict(team)

    # -----------------------------------------------------
    # TEAM MANAGEMENT
    # -----------------------------------------------------

    def join_team(self, team_name, client_id=None):
        team_name = " ".join((team_name or "").strip().split())
        client_id = (client_id or "").strip()

        if not team_name:
            raise ValueError("Enter a team name.")
        if len(team_name) > 40:
            raise ValueError("Team name must be 40 characters or less.")
        if len(client_id) > 120:
            raise ValueError("Invalid player device id.")

        with self.lock:
            now = time.monotonic()
            if client_id:
                for team in self.teams.values():
                    if team.get("client_id") == client_id:
                        if team["name"].casefold() == team_name.casefold():
                            team["connected"] = True
                            if not team.get("active", True):
                                team["active"] = True
                                team["inactive_since_monotonic"] = None
                                team["eligible_from_question_index"] = self._next_eligible_question_index_locked()
                            self._record_real_interaction_locked(team)
                            self._touch()
                            return dict(team)
                        raise ValueError(
                            f"This phone is already joined as {team['name']}. "
                            "Use Change Team Name before the game starts."
                        )

            for team in self.teams.values():
                if team["name"].casefold() == team_name.casefold():
                    raise ValueError("That team name is already in use.")

            team_number = self.next_team_number
            self.next_team_number += 1
            team_id = f"team-{secrets.token_urlsafe(9)}"
            eligible_from = self._next_eligible_question_index_locked()
            self.teams[team_id] = {
                "id": team_id,
                "number": team_number,
                "name": team_name,
                "score": 0,
                "connected": True,
                "joined_at": time.time(),
                "correct_count": 0,
                "correct_response_ms": 0,
                "client_id": client_id,
                "device_token": secrets.token_urlsafe(24),
                "active": True,
                "consecutive_missed_questions": 0,
                "needs_still_playing": False,
                "last_real_interaction_monotonic": now,
                "last_interaction_question_index": eligible_from - 1,
                "inactive_since_monotonic": None,
                "eligible_from_question_index": eligible_from,
            }
            self.status_message = f"{team_name} joined"
            self._touch()
            return dict(self.teams[team_id])

    def rename_team(self, team_id, team_name, actor="player", device_token=None, server_session_id=None):
        team_name = " ".join((team_name or "").strip().split())

        if not team_name:
            raise ValueError("Enter a team name.")
        if len(team_name) > 40:
            raise ValueError("Team name must be 40 characters or less.")

        with self.lock:
            if team_id not in self.teams:
                raise ValueError("That team session is no longer active. Join again.")

            if actor == "player":
                if (
                    server_session_id != self.server_session_id
                    or device_token != self.teams[team_id].get("device_token")
                ):
                    raise ValueError("That phone is not attached to this team in the current game. Rejoin first.")
                if self.game_started:
                    raise ValueError("Team names are locked once the game starts. Ask the host to make a correction.")

            for other_id, team in self.teams.items():
                if other_id != team_id and team["name"].casefold() == team_name.casefold():
                    raise ValueError("That team name is already in use.")

            old_name = self.teams[team_id]["name"]
            self.teams[team_id]["name"] = team_name
            self.status_message = f"{old_name} renamed to {team_name}"
            self._touch()
            return dict(self.teams[team_id])

    def _authorized_team_locked(self, team_id, device_token, server_session_id):
        if not team_id or team_id not in self.teams:
            return None
        candidate = self.teams[team_id]
        if server_session_id == self.server_session_id and device_token == candidate.get("device_token"):
            return candidate
        return None

    # -----------------------------------------------------
    # HOST GAME FLOW
    # -----------------------------------------------------

    def show_category(self):
        with self.lock:
            self._stop_timer_locked("Category screen")
            self.game_started = True
            self.screen = "category"
            self.status_message = f"Round {self._current_round_number()} category shown"
            self._touch()

    def show_wager(self):
        with self.lock:
            if not self._is_roulette():
                raise ValueError("The current question is not an Elite Roulette question.")
            if self.screen not in ("category", "wager"):
                raise ValueError("Show the Roulette category before the wager screen.")

            self._stop_timer_locked()
            self.screen = "wager"
            duration = max(1.0, float(self.question.get("wager_seconds", 30)))
            now = time.monotonic()
            self.timer_started_monotonic = now
            self.timer_ends_monotonic = now + duration
            self.timer_running = True
            self.timer_phase = "wager"
            self.status_message = "Roulette hint shown - wagers open"
            self._touch()

    def show_question(self):
        with self.lock:
            self._expire_timer_if_needed_locked()

            if self._is_roulette():
                if self.screen != "wager":
                    raise ValueError("Show the Roulette hint/wager screen before the question.")
                eligible_ids = self._eligible_active_team_ids_locked()
                all_wagers_in = not eligible_ids or all(
                    team_id in self.wagers for team_id in eligible_ids
                )
                if self.timer_running and not all_wagers_in:
                    raise ValueError(
                        "Waiting for remaining wagers. Stop the wager timer to force 0% for teams that did not wager."
                    )
                self._stop_timer_locked()
            else:
                if self.screen != "category":
                    raise ValueError("Show the category before the question.")
                self._stop_timer_locked()

            self.screen = "question"
            if self._is_final_wager():
                self.status_message = "Final Wager shown - timer not started"
            else:
                self.status_message = "Question shown - answer timer not started"
            self._touch()

    def start_timer(self):
        with self.lock:
            if self.screen not in ("wager", "question"):
                raise ValueError("Show the wager/question screen before starting the timer.")
            if self.timer_running:
                return

            duration = max(1.0, self._timer_duration_for_screen_locked())
            self.game_started = True
            now = time.monotonic()
            self.timer_started_monotonic = now
            self.timer_ends_monotonic = now + duration
            self.timer_running = True
            self.timer_phase = self.screen

            if self.screen == "wager":
                self.status_message = "Wagers open"
            elif self._is_final_wager():
                self.status_message = "Final Wager submissions open"
            else:
                self.status_message = "Answers open"
            self._touch()

    def stop_timer(self):
        with self.lock:
            self._stop_timer_locked("Timer stopped")
            self._touch()

    def reset_question(self):
        with self.lock:
            self.auto_game_running = False
            self.auto_deadline_monotonic = None
            self.auto_last_transition = ""
            self._stop_timer_locked("Question reset")
            self._rollback_current_question_locked()
            self._clear_question_state_locked()
            self.screen = "category"
            self.status_message = "Current question reset"
            self._touch()

    def next_question(self):
        with self.lock:
            self._stop_timer_locked()

            if self.screen == "game_complete":
                return

            if self.screen == "round_complete":
                if self.current_question_index >= len(self.questions) - 1:
                    self.screen = "game_complete"
                    self.status_message = "Game complete"
                    self._touch()
                    return

                self.current_question_index += 1
                self._clear_question_state_locked()
                self.screen = "category"
                self.status_message = f"Round {self._current_round_number()} ready"
                self._touch()
                return

            if self._current_is_last_in_round():
                if self.current_question_index >= len(self.questions) - 1:
                    self.screen = "game_complete"
                    self.status_message = "Game complete"
                else:
                    self.screen = "round_complete"
                    self.status_message = f"Round {self._current_round_number()} complete"
                self._touch()
                return

            self.current_question_index += 1
            self._clear_question_state_locked()
            self.screen = "category"
            self.status_message = (
                f"Ready for Round {self._current_round_number()} "
                f"Question {self.question.get('question_number', 1)}"
            )
            self._touch()

    def load_game_data(self, game_data):
        with self.lock:
            questions = list(
                game_data.get(
                    "questions",
                    [],
                )
            )

            if not questions:
                raise ValueError(
                    "Cannot load a game with no questions."
                )

            self.game_title = game_data.get(
                "game_title",
                "Auto Elite",
            )

            self.questions = questions

            self.status_message = (
                f"Loaded game: {self.game_title}"
            )

            self._touch()

    def reset_game(self):
        with self.lock:
            self.auto_game_running = False
            self.auto_deadline_monotonic = None
            self.auto_last_transition = ""
            self._stop_timer_locked()
            self.current_question_index = 0
            self._clear_question_state_locked()
            self.rule_slide_index = None
            self.screen = "pregame"
            self.game_started = False
            now = time.monotonic()
            for team in self.teams.values():
                team["score"] = 0
                team["correct_count"] = 0
                team["correct_response_ms"] = 0
                team["active"] = True
                team["consecutive_missed_questions"] = 0
                team["needs_still_playing"] = False
                team["last_real_interaction_monotonic"] = now
                team["last_interaction_question_index"] = 0
                team["inactive_since_monotonic"] = None
                team["eligible_from_question_index"] = 0
            self.status_message = "Full game reset - teams kept"
            self._touch()

    # -----------------------------------------------------
    # PLAYER SUBMISSIONS
    # -----------------------------------------------------

    def submit_wager(self, team_id, percent, device_token=None, server_session_id=None):
        with self.lock:
            self._expire_timer_if_needed_locked()

            if team_id not in self.teams:
                raise ValueError("Unknown team. Please rejoin.")
            team = self.teams[team_id]
            if server_session_id != self.server_session_id or device_token != team.get("device_token"):
                raise ValueError("This phone is not attached to that team in the current game. Rejoin first.")
            self._require_team_can_play_current_locked(team)
            if not self._is_roulette() or self.screen != "wager" or not self.timer_running:
                raise ValueError("Roulette wagers are not open.")
            if team_id in self.wagers:
                raise ValueError("Your wager is already locked in.")

            try:
                percent = int(percent)
            except Exception:
                raise ValueError("Invalid wager.")
            if percent not in (0, 50, 100):
                raise ValueError("Wager must be 0%, 50%, or 100%.")

            base_score = int(team["score"])
            amount = self._wager_amount(base_score, percent)
            wager = {
                "team_id": team_id,
                "percent": percent,
                "base_score": base_score,
                "amount": amount,
            }
            self.wagers[team_id] = wager
            self._record_real_interaction_locked(team)
            eligible_ids = self._eligible_active_team_ids_locked()
            wager_count = sum(1 for team_key in eligible_ids if team_key in self.wagers)
            if eligible_ids and wager_count >= len(eligible_ids):
                self.status_message = "All active wagers received - ready for question"
            else:
                self.status_message = f"{wager_count} of {len(eligible_ids)} active wager(s) received"
            self._touch()
            return dict(wager)

    def submit_answer(self, team_id, choice_index, device_token=None, server_session_id=None):
        now = time.monotonic()
        with self.lock:
            self._expire_timer_if_needed_locked()

            if team_id not in self.teams:
                raise ValueError("Unknown team. Please rejoin.")
            team = self.teams[team_id]
            if server_session_id != self.server_session_id or device_token != team.get("device_token"):
                raise ValueError("This phone is not attached to that team in the current game. Rejoin first.")
            self._require_team_can_play_current_locked(team)
            if self._is_final_wager():
                raise ValueError("Use the Final Wager controls for this question.")
            if self.screen != "question" or not self.timer_running:
                raise ValueError("Answers are not open.")
            if self.timer_ends_monotonic is None or now > self.timer_ends_monotonic:
                self._expire_timer_if_needed_locked()
                raise ValueError("Time is up.")
            if team_id in self.responses:
                raise ValueError("Your answer is already locked in.")

            q = self.question
            choices = q.get("choices", [])
            if not isinstance(choice_index, int) or choice_index < 0 or choice_index >= len(choices):
                raise ValueError("Invalid answer choice.")

            start = self.timer_started_monotonic or now
            elapsed = max(0.0, now - start)
            response_ms = int(round(elapsed * 1000))
            correct = choice_index == int(q.get("correct_index", -1))
            scoring_type = self._scoring_type(q)
            points = 0

            if correct and scoring_type == "fixed":
                points = int(q.get("fixed_points", q.get("max_points", 10)))
            elif correct and scoring_type == "fastest":
                points = int(self._fastest_points_for_elapsed_locked(elapsed) or 0)

            response = {
                "team_id": team_id,
                "choice_index": choice_index,
                "correct": correct,
                "points": points,
                "response_ms": response_ms,
                "score_delta": None,
            }
            self.responses[team_id] = response
            self._record_real_interaction_locked(team)
            eligible_ids = self._eligible_active_team_ids_locked()
            answer_count = sum(1 for team_key in eligible_ids if team_key in self.responses)
            self.status_message = f"{answer_count} of {len(eligible_ids)} active answer(s) received"
            self._touch()
            return dict(response)

    def submit_final_wager(self, team_id, decision, answer_text, device_token=None, server_session_id=None):
        now = time.monotonic()
        with self.lock:
            self._expire_timer_if_needed_locked()

            if team_id not in self.teams:
                raise ValueError("Unknown team. Please rejoin.")
            team = self.teams[team_id]
            if server_session_id != self.server_session_id or device_token != team.get("device_token"):
                raise ValueError("This phone is not attached to that team in the current game. Rejoin first.")
            self._require_team_can_play_current_locked(team)
            if not self._is_final_wager() or self.screen != "question" or not self.timer_running:
                raise ValueError("Final Wager submissions are not open.")
            if self.timer_ends_monotonic is None or now > self.timer_ends_monotonic:
                self._expire_timer_if_needed_locked()
                raise ValueError("Time is up.")
            if team_id in self.responses:
                raise ValueError("Your Final Wager is already locked in.")

            decision = str(decision or "").strip().lower()
            if decision not in ("save", "all_in"):
                raise ValueError("Choose SAVE MY POINTS or ALL IN.")

            answer_text = str(answer_text or "").strip()
            if decision == "all_in" and not answer_text:
                raise ValueError("ALL IN requires an answer.")

            start = self.timer_started_monotonic or now
            elapsed = max(0.0, now - start)
            response_ms = int(round(elapsed * 1000))
            correct = self._typed_answer_is_correct(self.question, answer_text) if answer_text else False

            response = {
                "team_id": team_id,
                "decision": decision,
                "answer_text": answer_text,
                "correct": correct,
                "points": 0,
                "response_ms": response_ms,
                "score_delta": None,
                "base_score": int(team["score"]),
            }
            self.responses[team_id] = response
            self._record_real_interaction_locked(team)
            eligible_ids = self._eligible_active_team_ids_locked()
            submission_count = sum(1 for team_key in eligible_ids if team_key in self.responses)
            self.status_message = f"{submission_count} of {len(eligible_ids)} active Final Wager submission(s) received"
            self._touch()
            return dict(response)

    # -----------------------------------------------------
    # SCORING / REVEAL
    # -----------------------------------------------------

    def _finalize_current_question_locked(self):
        if self.scoring_finalized:
            return

        self._refresh_inactivity_locked()
        scoring_type = self._scoring_type()
        self.adjustments = {}
        now = time.monotonic()

        # Optional Blitz speed bonus.  The values live in game_data.json so
        # Admin can change them later without rewriting the engine.
        # Python's sort is stable, so equal millisecond times preserve actual
        # server receipt order from self.responses.
        speed_bonus_by_team = {}
        raw_speed_bonuses = self.question.get("speed_bonus_points", [])
        speed_bonus_values = []
        if isinstance(raw_speed_bonuses, (list, tuple)):
            for value in raw_speed_bonuses:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    speed_bonus_values.append(value)

        if scoring_type == "fastest" and speed_bonus_values:
            correct_responses = []
            for receipt_order, (response_team_id, response) in enumerate(self.responses.items()):
                team = self.teams.get(response_team_id)
                if not team or not self._team_eligible_for_current_question_locked(team):
                    continue
                if not response.get("correct"):
                    continue
                response_ms = int(response.get("response_ms", 0) or 0)
                correct_responses.append((response_ms, receipt_order, response_team_id))

            correct_responses.sort(key=lambda item: (item[0], item[1]))
            for bonus_index, (_, _, response_team_id) in enumerate(
                correct_responses[:len(speed_bonus_values)]
            ):
                speed_bonus_by_team[response_team_id] = speed_bonus_values[bonus_index]

        for team_id, team in self.teams.items():
            participating = self._team_eligible_for_current_question_locked(team)
            response = self.responses.get(team_id) if participating else None
            correct = bool(response and response.get("correct"))
            response_ms = int(response.get("response_ms", 0) or 0) if response else 0
            delta = 0
            activity_before = {
                "active": bool(team.get("active", True)),
                "consecutive_missed_questions": int(team.get("consecutive_missed_questions", 0)),
                "needs_still_playing": bool(team.get("needs_still_playing", False)),
                "inactive_since_monotonic": team.get("inactive_since_monotonic"),
            }

            if participating:
                if scoring_type in ("fixed", "fastest"):
                    delta = int(response.get("points", 0) or 0) if response else 0
                    if scoring_type == "fastest" and response is not None:
                        speed_bonus = int(speed_bonus_by_team.get(team_id, 0) or 0)
                        response["speed_bonus"] = speed_bonus
                        delta += speed_bonus
                elif scoring_type == "roulette":
                    wager = self.wagers.get(team_id)
                    if wager is None:
                        base_score = int(team["score"])
                        wager = {"team_id": team_id, "percent": 0, "base_score": base_score, "amount": 0}
                        self.wagers[team_id] = wager
                    amount = int(wager.get("amount", 0) or 0)
                    percent = int(wager.get("percent", 0) or 0)
                    delta = 0 if percent == 0 else (amount if correct else -amount)
                elif scoring_type == "final_wager":
                    if response is None:
                        delta = 0
                    else:
                        decision = response.get("decision", "save")
                        base_score = int(response.get("base_score", team["score"]) or 0)
                        delta = (base_score if correct else -base_score) if decision == "all_in" else 0

            original_score = int(team["score"])
            new_score = max(0, original_score + delta)
            actual_delta = new_score - original_score
            team["score"] = new_score

            correct_added = False
            if participating and correct:
                team["correct_count"] += 1
                team["correct_response_ms"] += response_ms
                correct_added = True

            if participating:
                interacted_this_question = int(team.get("last_interaction_question_index", -1)) == self.current_question_index
                if interacted_this_question:
                    team["consecutive_missed_questions"] = 0
                    team["needs_still_playing"] = False
                else:
                    misses = int(team.get("consecutive_missed_questions", 0)) + 1
                    team["consecutive_missed_questions"] = misses
                    team["needs_still_playing"] = misses >= self.still_playing_prompt_after_misses
                    last_interaction = float(team.get("last_real_interaction_monotonic", now))
                    inactive_seconds = max(0.0, now - last_interaction)
                    if misses >= self.inactive_after_misses and inactive_seconds >= self.inactive_after_seconds:
                        team["active"] = False
                        team["needs_still_playing"] = True
                        team["inactive_since_monotonic"] = now

            self.adjustments[team_id] = {
                "score_delta": actual_delta,
                "correct_added": correct_added,
                "response_ms": response_ms,
                "activity_before": activity_before,
            }
            if response is not None:
                response["score_delta"] = actual_delta
            if participating and scoring_type == "roulette" and team_id in self.wagers:
                self.wagers[team_id]["score_delta"] = actual_delta

        self.scoring_finalized = True

    def reveal_answer(self):
        with self.lock:
            if self.screen != "question":
                raise ValueError("Show the question before revealing the answer.")
            self._stop_timer_locked("Answer revealed")
            self._finalize_current_question_locked()
            self.screen = "reveal"
            self._touch()

    def show_speed_bonus(self):
        with self.lock:
            if self.screen != "reveal":
                raise ValueError("Reveal the answer before showing the Speed Bonus.")

            winners = self._speed_bonus_winners_locked()
            if not winners:
                self.presentation_started_monotonic = None
                self.presentation_ends_monotonic = None
                self.screen = "scores"
                self.status_message = "No Speed Bonus winners - scores shown"
                self._touch()
                return

            duration = self._speed_bonus_tv_seconds_locked()
            now = time.monotonic()
            self.presentation_started_monotonic = now
            self.presentation_ends_monotonic = now + duration
            self.screen = "speed_bonus"
            self.status_message = "Speed Bonus winners"
            self._touch()

    def show_scores(self):
        with self.lock:
            if self.screen not in ("reveal", "sociable", "speed_bonus", "scores"):
                raise ValueError("Reveal the answer before showing scores.")
            self._stop_timer_locked("Scores shown")
            self.presentation_started_monotonic = None
            self.presentation_ends_monotonic = None
            self.screen = "scores"
            self._touch()

    def _rollback_current_question_locked(self):
        if not self.scoring_finalized:
            return

        for team_id, adjustment in self.adjustments.items():
            team = self.teams.get(team_id)
            if not team:
                continue

            team["score"] = max(
                0,
                int(team["score"]) - int(adjustment.get("score_delta", 0) or 0),
            )

            if adjustment.get("correct_added"):
                response_ms = int(adjustment.get("response_ms", 0) or 0)
                team["correct_count"] = max(0, team["correct_count"] - 1)
                team["correct_response_ms"] = max(0, team["correct_response_ms"] - response_ms)
            activity_before = adjustment.get("activity_before")
            if activity_before:
                team["active"] = activity_before["active"]
                team["consecutive_missed_questions"] = activity_before["consecutive_missed_questions"]
                team["needs_still_playing"] = activity_before["needs_still_playing"]
                team["inactive_since_monotonic"] = activity_before["inactive_since_monotonic"]

    # -----------------------------------------------------
    # STATE
    # -----------------------------------------------------

    def _scoreboard_locked(self):
        teams_sorted = sorted(
            self.teams.values(),
            key=lambda t: (-t["score"], t["correct_response_ms"], t["number"]),
        )
        return [
            {
                "rank": rank,
                "number": team["number"],
                "name": team["name"],
                "score": team["score"],
            }
            for rank, team in enumerate(teams_sorted, start=1)
        ]

    def get_public_state(self, team_id=None, device_token=None, server_session_id=None):
        with self.lock:
            self._expire_timer_if_needed_locked()
            self._advance_presentation_if_needed_locked()
            self._refresh_inactivity_locked()
            q = self.question
            remaining = self._remaining_locked()
            scoreboard = self._scoreboard_locked()

            show_correct = self.screen in ("reveal", "sociable", "speed_bonus", "scores", "round_complete", "game_complete")
            correct_index = int(q.get("correct_index", -1)) if show_correct and q.get("choices") else None
            answer_display = str(q.get("answer_display", "")) if show_correct else ""

            team = self._authorized_team_locked(team_id, device_token, server_session_id)
            team_response = self.responses.get(team_id) if team else None
            team_wager = self.wagers.get(team_id) if team else None

            teams_by_number = sorted(self.teams.values(), key=lambda t: t["number"])
            eligible_active_teams = [t for t in teams_by_number if self._team_eligible_for_current_question_locked(t)]
            eligible_ids = {t["id"] for t in eligible_active_teams}
            outstanding_answer_teams = [
                {"number": t["number"], "name": t["name"]}
                for t in eligible_active_teams
                if t["id"] not in self.responses
            ]
            outstanding_wager_teams = [
                {"number": t["number"], "name": t["name"]}
                for t in eligible_active_teams
                if t["id"] not in self.wagers
            ]
            active_team_count = sum(1 for t in teams_by_number if t.get("active", True))
            eligible_team_count = len(eligible_active_teams)
            eligible_answer_count = sum(1 for team_key in eligible_ids if team_key in self.responses)
            eligible_wager_count = sum(1 for team_key in eligible_ids if team_key in self.wagers)

            current_round = int(q.get("round", 1))
            round_question_count = self._round_question_count(current_round)
            speed_bonus_winners = self._speed_bonus_winners_locked()
            speed_bonus_remaining = 0.0
            if self.screen == "speed_bonus" and self.presentation_ends_monotonic is not None:
                speed_bonus_remaining = max(0.0, self.presentation_ends_monotonic - time.monotonic())

            current_rule_slide = self._current_rule_slide_locked()

            return {
                "version": self.version,
                "app_build": APP_BUILD,
                "server_session_id": self.server_session_id,
                "game_title": self.game_title,
                "screen": self.screen,
                "question_index": self.current_question_index,
                "question_count": len(self.questions),
                "round_question_count": round_question_count,
                "has_next_question": self.current_question_index < len(self.questions) - 1,
                "status": self.status_message,
                "game_started": self.game_started,
                "auto_game_running": self.auto_game_running,
                "auto_next_transition_in": round(self._auto_seconds_remaining_locked(), 2),
                "auto_last_transition": self.auto_last_transition,
                "auto_flow_settings": {
                    "category_seconds": self.auto_category_seconds,
                    "reveal_seconds": self.auto_reveal_seconds,
                    "scoreboard_seconds": self.auto_scoreboard_seconds,
                    "round_complete_seconds": self.auto_round_complete_seconds,
                    "sociable_seconds": self.auto_sociable_seconds,
                },
                "sociable_min_teams": self.sociable_min_teams,
                "display_settings": dict(self.display_settings),
                "rule_slide_index": self.rule_slide_index,
                "rule_slide_count": len(self.rule_slides),
                "rule_slide_key": current_rule_slide.get("key") if current_rule_slide else None,
                "speed_bonus_winners": speed_bonus_winners,
                "speed_bonus_remaining": round(speed_bonus_remaining, 2),
                "player_can_rename": not self.game_started,
                "timer_running": self.timer_running,
                "timer_phase": self.timer_phase,
                "timer_remaining": round(remaining, 2),
                "timer_display_seconds": (
                    self._timer_duration_for_screen_locked()
                    if self.screen in ("wager", "question")
                    else 0
                ),
                "current_fastest_points": (
                    self._fastest_points_for_elapsed_locked()
                    if self.screen == "question"
                    else None
                ),
                "current_fastest_display": (
                    self._fastest_display_value_locked()
                    if self.screen == "question"
                    else None
                ),
                "all_answers_in": bool(eligible_ids) and eligible_answer_count >= eligible_team_count,
                "outstanding_answer_teams": outstanding_answer_teams,
                "all_wagers_in": bool(eligible_ids) and eligible_wager_count >= eligible_team_count,
                "outstanding_wager_teams": outstanding_wager_teams,
                "wagers_remaining": max(0, eligible_team_count - eligible_wager_count),
                "question": {
                    "id": q.get("id", ""),
                    "round": current_round,
                    "question_number": int(q.get("question_number", 1)),
                    "type": q.get("type", "normal"),
                    "scoring_type": self._scoring_type(q),
                    "category": q.get("category", ""),
                    "hint": q.get("hint", ""),
                    "question": q.get("question", ""),
                    "choices": q.get("choices", []),
                    "correct_index": correct_index,
                    "answer_display": answer_display,
                    "timer_seconds": int(q.get("timer_seconds", 120)),
                    "wager_seconds": int(q.get("wager_seconds", 30)),
                    # Final Wager is score-based, not a 10/20/30/40 point question.
                    # Return zero point fields so any client that reads these values
                    # never falls back to the old 10-point default.
                    "fixed_points": (
                        0
                        if self._scoring_type(q) == "final_wager"
                        else int(q.get("fixed_points", q.get("max_points", 10)))
                    ),
                    "max_points": (
                        0
                        if self._scoring_type(q) == "final_wager"
                        else int(q.get("max_points", 10))
                    ),
                    "min_points": (
                        0
                        if self._scoring_type(q) == "final_wager"
                        else int(q.get("min_points", 5))
                    ),
                    "speed_bonus_points": [
                        int(value)
                        for value in q.get("speed_bonus_points", [])
                        if isinstance(value, (int, float)) and int(value) > 0
                    ],
                    "speed_bonus_phone_seconds": self._speed_bonus_phone_seconds_locked(),
                    "speed_bonus_tv_seconds": self._speed_bonus_tv_seconds_locked(),
                },
                "team_count": len(self.teams),
                "active_team_count": active_team_count,
                "eligible_team_count": eligible_team_count,
                "answer_count": eligible_answer_count,
                "wager_count": eligible_wager_count,
                "inactivity_settings": {
                    "still_playing_prompt_after_misses": self.still_playing_prompt_after_misses,
                    "inactive_after_misses": self.inactive_after_misses,
                    "inactive_after_seconds": self.inactive_after_seconds,
                },
                "scoreboard": scoreboard,
                "team": (
                    {
                        "id": team["id"],
                        "number": team["number"],
                        "name": team["name"],
                        "score": team["score"],
                        "active": bool(team.get("active", True)),
                        "consecutive_missed_questions": int(team.get("consecutive_missed_questions", 0)),
                        "needs_still_playing": bool(team.get("needs_still_playing", False)),
                        "eligible_for_current_question": self._team_eligible_for_current_question_locked(team),
                        "eligible_from_question_index": int(team.get("eligible_from_question_index", 0)),
                    }
                    if team
                    else None
                ),
                "team_response": team_response,
                "team_wager": team_wager,
            }

    def get_host_snapshot(self):
        with self.lock:
            self._expire_timer_if_needed_locked()
            state = self.get_public_state()
            rows = []
            scoring_type = self._scoring_type()

            for team in sorted(self.teams.values(), key=lambda t: t["number"]):
                response = self.responses.get(team["id"])
                wager = self.wagers.get(team["id"])
                answer_text = ""
                response_time = ""
                points = ""
                wager_text = ""
                if not team.get("active", True):
                    activity_status = "INACTIVE"
                elif not self._team_eligible_for_current_question_locked(team):
                    activity_status = "NEXT Q"
                elif team.get("needs_still_playing", False):
                    activity_status = f"CHECK-IN {int(team.get('consecutive_missed_questions', 0))}"
                else:
                    activity_status = "ACTIVE"

                if scoring_type == "roulette":
                    if wager:
                        wager_text = f"{wager['percent']}% ({wager['amount']})"
                    elif self.screen in ("wager", "question", "reveal", "scores"):
                        wager_text = "0% default"

                if scoring_type == "final_wager":
                    if response:
                        wager_text = "ALL IN" if response.get("decision") == "all_in" else "SAVE"
                        answer_text = response.get("answer_text", "")
                    elif self.screen in ("question", "reveal", "scores", "game_complete"):
                        wager_text = "SAVE default"

                elif response:
                    idx = response.get("choice_index")
                    choices = self.question.get("choices", [])
                    if isinstance(idx, int) and 0 <= idx < len(choices):
                        answer_text = choices[idx]
                    else:
                        answer_text = str(idx)

                if response:
                    response_time = f"{response.get('response_ms', 0) / 1000:.2f}s"
                    if response.get("score_delta") is not None:
                        points = f"{int(response['score_delta']):+d}"
                    elif scoring_type in ("fixed", "fastest"):
                        points = str(response.get("points", 0))

                rows.append(
                    {
                        "id": team["id"],
                        "number": team["number"],
                        "name": team["name"],
                        "score": team["score"],
                        "status": activity_status,
                        "wager": wager_text,
                        "answer": answer_text,
                        "time": response_time,
                        "points": points,
                    }
                )

            state["host_rows"] = rows
            return state



class NetworkController:
    """Connects the schedule, the reusable Blitz engine, and channel mini-games."""

    SHOW_KINDS = {"sports_blitz", "elite_blitz", "after_dark"}

    def __init__(self, scheduler, engine, game_data):
        self.lock = threading.RLock()
        self.scheduler = scheduler
        self.engine = engine
        self.game_data = game_data

        self.mini_game = MiniGameController(
            game_data.get(
                "questions",
                [],
            ),
            event_callback=
                self.scheduler.record_event,
            team_provider=
                self._mini_game_team_snapshot,
        )
        self.active_event_instance = None
        self.active_event = None
        self.active_profile = None
        self.completed_event_instances = set()
        self.last_clock_revision = scheduler.clock_revision
        self.last_auto_mini_slot = None

    def _mini_game_team_snapshot(self):

        with self.engine.lock:

            return [
                dict(team)
                for team
                in self.engine.teams.values()
            ]


    @staticmethod
    def _event_instance(program):
        return f"{program.get('id', '')}|{program.get('start_iso', '')}"

    @staticmethod
    def _profile_for_kind(kind):
        if kind == "sports_blitz":
            return "sports"
        if kind == "after_dark":
            return "after_dark"
        return "standard"

    def _reset_for_clock_jump_locked(self):
        if self.active_event_instance is not None:
            try:
                self.engine.stop_auto_game()
            except Exception:
                pass
            try:
                self.engine.reset_game()
            except Exception:
                pass
        self.active_event_instance = None
        self.active_event = None
        self.active_profile = None
        self.completed_event_instances.clear()
        self.last_auto_mini_slot = None
        self.mini_game.stop("clock jump")

    def _start_show_locked(self, program):
        instance = self._event_instance(program)

        if instance in self.completed_event_instances:
            return

        self.mini_game.stop(
            "scheduled show starting"
        )

        fallback_game_key = str(
            program.get(
                "game_key",
                "",
            )
            or
            ""
        ).strip()

        game_key = None

        from game_builder.runtime_game_loader import (
            load_runtime_game,
            resolve_scheduled_game_key,
        )

        # -------------------------------------------------
        # Resolve the Auto Builder game for this exact
        # Network date/time slot.
        # -------------------------------------------------

        kind_to_game_type = {
            "sports_blitz":
                "SPORTS_BLITZ",

            "elite_blitz":
                "REGULAR_BLITZ",

            "after_dark":
                "AFTER_DARK_BLITZ",
        }

        expected_game_type = (
            kind_to_game_type.get(
                program.get("kind")
            )
        )

        start_iso = str(
            program.get(
                "start_iso",
                "",
            )
            or
            ""
        ).strip()

        if (
            expected_game_type
            and
            start_iso
        ):
            try:
                scheduled_dt = (
                    datetime.fromisoformat(
                        start_iso
                    )
                )

                # Database scheduled_for values are stored
                # as local wall-clock datetimes without the
                # timezone suffix.
                scheduled_for = (
                    scheduled_dt
                    .replace(
                        tzinfo=None
                    )
                    .isoformat(
                        timespec="seconds"
                    )
                )

                game_key = (
                    resolve_scheduled_game_key(
                        scheduled_for,
                        expected_game_type,
                    )
                )

            except Exception as exc:
                self.scheduler.record_event(
                    "SCHEDULED GAME LOOKUP ERROR -> "
                    f"{exc}"
                )

        # -------------------------------------------------
        # GAME LOAD FAILSAFE
        #
        # Primary:
        #   exact dated Auto Builder game
        #
        # Emergency backup:
        #   fixed game_key from network_schedule.json
        #
        # A bad question/game must never crash the Network.
        # -------------------------------------------------

        primary_game_key = game_key

        emergency_game_key = (
            fallback_game_key
            if fallback_game_key
            and fallback_game_key != primary_game_key
            else None
        )

        # If no dated game exists, use the fixed backup
        # immediately.
        if not primary_game_key:
            primary_game_key = emergency_game_key
            emergency_game_key = None

            if primary_game_key:
                self.scheduler.record_event(
                    "GAME LOOKUP FALLBACK -> "
                    f"{primary_game_key}"
                )

        runtime_game = None
        loaded_game_key = None
        primary_error = None
        backup_error = None
        backup_used = False

        if primary_game_key:
            try:
                runtime_game = load_runtime_game(
                    primary_game_key
                )

                loaded_game_key = (
                    primary_game_key
                )

            except Exception as exc:
                primary_error = str(exc)

                self.scheduler.record_event(
                    "PRIMARY GAME FAILED -> "
                    f"{primary_game_key} -> "
                    f"{primary_error}"
                )

        # Primary failed: immediately try the fixed
        # same-slot emergency game.
        if (
            runtime_game is None
            and
            emergency_game_key
        ):
            try:
                runtime_game = load_runtime_game(
                    emergency_game_key
                )

                loaded_game_key = (
                    emergency_game_key
                )

                backup_used = True

                self.scheduler.record_event(
                    "BACKUP GAME USED -> "
                    f"{emergency_game_key}"
                )

            except Exception as exc:
                backup_error = str(exc)

                self.scheduler.record_event(
                    "BACKUP GAME FAILED -> "
                    f"{emergency_game_key} -> "
                    f"{backup_error}"
                )

        # Permanent incident history.
        if primary_error or backup_used or backup_error:
            try:
                incident_path = (
                    BASE_DIR
                    / "network_incidents.jsonl"
                )

                incident = {
                    "timestamp":
                        datetime.now().isoformat(
                            timespec="seconds"
                        ),

                    "event_instance":
                        instance,

                    "event_title":
                        program.get(
                            "title",
                            "ELITE BLITZ",
                        ),

                    "event_kind":
                        program.get("kind"),

                    "scheduled_start":
                        program.get("start_iso"),

                    "primary_game_key":
                        primary_game_key,

                    "primary_error":
                        primary_error,

                    "backup_game_key":
                        emergency_game_key,

                    "backup_used":
                        backup_used,

                    "backup_error":
                        backup_error,

                    "loaded_game_key":
                        loaded_game_key,
                }

                with incident_path.open(
                    "a",
                    encoding="utf-8",
                ) as fh:
                    fh.write(
                        json.dumps(
                            incident,
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

            except Exception as exc:
                self.scheduler.record_event(
                    "INCIDENT LOG ERROR -> "
                    f"{exc}"
                )

        # If BOTH games fail, do not allow the exception
        # to destroy /api/state and freeze the TV.
        if runtime_game is None:

            self.scheduler.record_event(
                "NO PLAYABLE GAME -> "
                f"{program.get('title', 'ELITE BLITZ')}"
            )

            self.completed_event_instances.add(
                instance
            )

            return

        self.engine.load_game_data(
            runtime_game
        )

        self.game_data = runtime_game

        self.scheduler.record_event(
            f"LOAD GAME -> {loaded_game_key}"
        )

        if backup_used:
            self.scheduler.record_event(
                "!!! REVIEW REQUIRED: "
                "SCHEDULED GAME USED BACKUP !!!"
            )

        self.engine.reset_game()

        self.active_event_instance = instance
        self.active_event = dict(program)

        self.active_profile = (
            self._profile_for_kind(
                program.get("kind")
            )
        )

        self.engine.start_auto_game()

        self.scheduler.record_event(
            f"LAUNCH -> "
            f"{program.get('title', 'ELITE BLITZ')}"
        )

    def _finish_show_if_needed_locked(self):
        if self.active_event_instance is None:
            return
        with self.engine.lock:
            finished = self.engine.screen == "game_complete"
        if not finished:
            return
        self.completed_event_instances.add(self.active_event_instance)
        title = (self.active_event or {}).get("title", "ELITE BLITZ")
        self.scheduler.record_event(f"COMPLETE â†’ {title} â€¢ RETURN TO CHANNEL")
        self.active_event_instance = None
        self.active_event = None
        self.active_profile = None

    def _maybe_start_auto_mini_locked(
        self,
        base_snapshot,
    ):
        if (
            self.mini_game.active
            or
            self.active_event_instance is not None
        ):
            return

        config = (
            self.scheduler
            .schedule
            .get("channel", {})
        )

        if not bool(
            config.get(
                "auto_mini_enabled",
                True,
            )
        ):
            return

        now = datetime.fromisoformat(
            base_snapshot["now_iso"]
        )

        # -------------------------------------------------
        # TIME HELPERS
        # -------------------------------------------------

        def minute_of_day(value):
            hour, minute = str(
                value
            ).split(":", 1)

            return (
                int(hour) * 60
                + int(minute)
            )

        def inside_window(
            current_minute,
            start_text,
            end_text,
        ):
            start_minute = minute_of_day(
                start_text
            )

            end_minute = minute_of_day(
                end_text
            )

            if start_minute <= end_minute:
                return (
                    start_minute
                    <= current_minute
                    < end_minute
                )

            # Window crosses midnight.
            return (
                current_minute >= start_minute
                or
                current_minute < end_minute
            )

        def start_programmed_mini(
            game_type,
            reason,
        ):
            try:
                self.mini_game.start(
                    reason,
                    game_type=game_type,
                )

            except ValueError:

                # Skee-Ball needs an active
                # connected team. If nobody
                # can play, use Quick 3.
                if game_type == "skee_ball":

                    fallback = config.get(
                        "skee_ball_fallback",
                        "quick_3",
                    )

                    self.mini_game.start(
                        reason
                        + " â€¢ Skee fallback",
                        game_type=fallback,
                    )

                else:
                    raise

        # =================================================
        # MINI IMMEDIATELY BEFORE A BLITZ
        # =================================================

        lead_in_phase = (
            base_snapshot.get(
                "lead_in_phase"
            )
        )

        if lead_in_phase == "mini_game":

            next_event = (
                base_snapshot.get(
                    "lead_in_next_event"
                )
                or {}
            )

            slot = (
                "lead-in|"
                + str(
                    next_event.get(
                        "id",
                        "",
                    )
                )
                + "|"
                + str(
                    next_event.get(
                        "start_iso",
                        "",
                    )
                )
            )

            if (
                slot
                != self.last_auto_mini_slot
            ):
                self.last_auto_mini_slot = slot

                rotation = (
                    config.get(
                        "pre_blitz_mini_rotation"
                    )
                    or [
                        "quick_3",
                        "reaction_rush",
                        "skee_ball",
                    ]
                )

                start_iso = (
                    next_event.get(
                        "start_iso",
                        ""
                    )
                )

                try:
                    event_dt = (
                        datetime.fromisoformat(
                            start_iso
                        )
                    )

                    rotation_index = (
                        event_dt.hour
                        % len(rotation)
                    )

                except Exception:
                    rotation_index = 0

                game_type = rotation[
                    rotation_index
                ]

                start_programmed_mini(
                    game_type,
                    "scheduled lead-in",
                )

            return

        # =================================================
        # LONG-BREAK PROGRAMMED MINI WINDOWS
        # =================================================

        current_minute = (
            now.hour * 60
            + now.minute
        )

        windows = (
            config.get(
                "mini_windows",
                [],
            )
            or []
        )

        active_window = None

        for window in windows:

            if inside_window(
                current_minute,
                window.get(
                    "start",
                    "00:00",
                ),
                window.get(
                    "end",
                    "00:00",
                ),
            ):
                active_window = window
                break

        if active_window is None:
            return

        every = max(
            5,
            int(
                active_window.get(
                    "every_minutes",
                    20,
                )
            ),
        )

        window_start = minute_of_day(
            active_window.get(
                "start",
                "00:00",
            )
        )

        elapsed = (
            current_minute
            - window_start
        )

        if elapsed < 0:
            elapsed += 1440

        if elapsed % every != 0:
            return

        # Polling happens several times a
        # second. Only start once per slot.
        slot = now.strftime(
            "%Y-%m-%d-%H-%M"
        )

        if (
            slot
            == self.last_auto_mini_slot
        ):
            return

        # Don't start a normal filler mini
        # right before a scheduled Blitz.
        min_gap = max(
            0,
            int(
                config.get(
                    "mini_game_min_gap_before_show_seconds",
                    180,
                )
            ),
        )

        next_event = (
            base_snapshot.get(
                "next_event"
            )
            or {}
        )

        seconds_until = (
            next_event.get(
                "seconds_until"
            )
        )

        if (
            seconds_until is not None
            and
            int(seconds_until) < min_gap
        ):
            return

        rotation = (
            active_window.get(
                "rotation"
            )
            or [
                "quick_3",
            ]
        )

        slot_number = (
            elapsed // every
        )

        game_type = rotation[
            slot_number
            % len(rotation)
        ]

        self.last_auto_mini_slot = slot

        start_programmed_mini(
            game_type,
            "automatic programmed mini",
        )


    def tick(self):
        with self.lock:
            if self.scheduler.clock_revision != self.last_clock_revision:
                self.last_clock_revision = self.scheduler.clock_revision
                self._reset_for_clock_jump_locked()

            self.mini_game.tick()
            self._finish_show_if_needed_locked()

            base = self.scheduler.get_snapshot()
            raw_program = base.get("program", {})
            raw_kind = raw_program.get("kind", "channel")

            if self.active_event_instance is None and raw_kind in self.SHOW_KINDS:
                instance = self._event_instance(raw_program)
                if instance not in self.completed_event_instances:
                    self._start_show_locked(raw_program)

            # Once a scheduled game starts, it owns the screen until the game engine
            # completes. The schedule end time is a programming slot, not a hard kill.
            if self.active_event_instance is None:
                self._maybe_start_auto_mini_locked(base)

    def run_mini_game_now(self):
        with self.lock:
            self.tick()
            if self.active_event_instance is not None:
                raise ValueError("A scheduled Elite Blitz game is running right now.")
            self.mini_game.start(
                "host test",
                game_type="quick_3",
            )

    def run_reaction_rush_now(self):
        with self.lock:
            self.tick()
            if self.active_event_instance is not None:
                raise ValueError("A scheduled Elite Blitz game is running right now.")
            self.mini_game.start(
                "host test",
                game_type="reaction_rush",
            )

    def run_skee_ball_now(self):
        with self.lock:
            self.tick()

            if self.active_event_instance is not None:
                raise ValueError(
                    "A scheduled Elite Blitz game is running right now."
                )

            if self.mini_game.active:
                self.mini_game.stop(
                    "host override"
                )

            self.mini_game.start(
                "host test",
                game_type="skee_ball",
            )

    def get_snapshot(self):
        self.tick()
        with self.lock:
            base = self.scheduler.get_snapshot()
            raw_program = dict(base.get("program", {}))
            raw_kind = raw_program.get("kind", "channel")
            mini = self.mini_game.snapshot()

            game_active = self.active_event_instance is not None
            if game_active:
                program = dict(self.active_event or raw_program)
            elif mini.get("active"):
                mini_type = mini.get(
                    "game_type",
                    "quick_3",
                )

                program = {
                    "id": f"elite_{mini_type}",
                    "kind": "mini_game",
                    "title": mini.get(
                        "title",
                        "ELITE MINI-GAME",
                    ),
                }
            elif raw_kind in self.SHOW_KINDS:
                # The game already completed inside its schedule window. Channel filler
                # resumes immediately instead of leaving a dead/placeholder screen.
                program = dict(self.scheduler.schedule.get("default_program", {}))
                program.setdefault("id", "elite_channel")
                program.setdefault("kind", "channel")
                program.setdefault("title", "ELITE CHANNEL")
            else:
                program = raw_program

            base["scheduled_program"] = raw_program
            base["program"] = program
            base["game_active"] = game_active
            base["show_profile"] = self.active_profile if game_active else None
            base["show_title"] = (
                (self.active_event or {}).get("title", "ELITE BLITZ") if game_active else None
            )
            base["mini_game"] = mini
            return base

    def worker(self):
        while True:
            try:
                self.tick()
            except Exception as exc:
                self.scheduler.record_event(f"NETWORK ERROR â†’ {exc}")
            time.sleep(0.10)


class EliteHeartbeatMonitor:
    """End-to-end heartbeat for the local server + TV browser client.

    The cloud check receives success pings only while the TV page is actively
    checking in with this local server. If the TV browser disappears while the
    Python server is still alive, we send a failure signal. If the whole PC,
    Python process, router, or internet connection goes down, success pings stop
    and the cloud service's missed-heartbeat timer triggers the alert.
    """

    def __init__(self, config_path):
        self.lock = threading.RLock()
        self.config_path = Path(config_path)
        self.last_tv_seen_monotonic = None
        self.last_tv_seen_wall = None
        self.last_tv_client = None
        self.fail_sent = False
        self.last_cloud_ping_wall = None
        self.last_cloud_error = None

    def _load_config(self):
        defaults = {
            "enabled": False,
            "ping_url": "",
            "ping_interval_seconds": 60,
            "tv_stale_seconds": 90,
        }
        try:
            if self.config_path.is_file():
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    defaults.update(data)
        except Exception as exc:
            self.last_cloud_error = f"Heartbeat config error: {exc}"
        return defaults

    def note_tv_client(self, payload=None, client_ip=None):
        payload = payload if isinstance(payload, dict) else {}
        with self.lock:
            self.last_tv_seen_monotonic = time.monotonic()
            self.last_tv_seen_wall = datetime.now().astimezone().isoformat(timespec="seconds")
            self.last_tv_client = {
                "client_id": str(payload.get("client_id") or ""),
                "visibility": str(payload.get("visibility") or ""),
                "path": str(payload.get("path") or ""),
                "client_ip": str(client_ip or ""),
            }

    def snapshot(self):
        with self.lock:
            age = None
            if self.last_tv_seen_monotonic is not None:
                age = max(0.0, time.monotonic() - self.last_tv_seen_monotonic)
            cfg = self._load_config()
            return {
                "enabled": bool(cfg.get("enabled")),
                "tv_last_seen_seconds": None if age is None else round(age, 1),
                "tv_last_seen": self.last_tv_seen_wall,
                "tv_client": self.last_tv_client,
                "last_cloud_ping": self.last_cloud_ping_wall,
                "last_cloud_error": self.last_cloud_error,
            }

    @staticmethod
    def _signal_url(base_url, suffix):
        parsed = urlparse(base_url)
        new_path = parsed.path.rstrip("/") + suffix
        return parsed._replace(path=new_path).geturl()

    def _send(self, url):
        req = Request(url, method="GET", headers={"User-Agent": f"EliteNetwork/{APP_BUILD}"})
        with urlopen(req, timeout=5) as response:
            response.read(32)
        with self.lock:
            self.last_cloud_ping_wall = datetime.now().astimezone().isoformat(timespec="seconds")
            self.last_cloud_error = None

    def worker(self):
        next_success = 0.0
        while True:
            cfg = self._load_config()
            enabled = bool(cfg.get("enabled"))
            ping_url = str(cfg.get("ping_url") or "").strip()
            interval = max(30, int(cfg.get("ping_interval_seconds") or 60))
            stale_after = max(45, int(cfg.get("tv_stale_seconds") or 90))

            if not enabled or not ping_url.startswith(("http://", "https://")):
                time.sleep(5)
                continue

            with self.lock:
                last_tv = self.last_tv_seen_monotonic

            # Do not arm the external check until at least one TV client has
            # actually connected. This avoids a false alarm while you are still
            # opening the browser on the Android box.
            if last_tv is None:
                time.sleep(5)
                continue

            now_mono = time.monotonic()
            tv_age = max(0.0, now_mono - last_tv)

            try:
                if tv_age <= stale_after:
                    if now_mono >= next_success:
                        self._send(ping_url)
                        with self.lock:
                            self.fail_sent = False
                        next_success = now_mono + interval
                else:
                    with self.lock:
                        already_failed = self.fail_sent
                    if not already_failed:
                        self._send(self._signal_url(ping_url, "/fail"))
                        with self.lock:
                            self.fail_sent = True
            except Exception as exc:
                with self.lock:
                    self.last_cloud_error = str(exc)

            time.sleep(5)


HEARTBEAT = EliteHeartbeatMonitor(HEARTBEAT_CONFIG_FILE)

GAME_DATA = load_game_data()
ENGINE = GameEngine(GAME_DATA)
NETWORK = NetworkScheduler(NETWORK_SCHEDULE_FILE)
NETWORK_CONTROL = NetworkController(NETWORK, ENGINE, GAME_DATA)


class EliteRequestHandler(BaseHTTPRequestHandler):
    server_version = f"AutoEliteLocal/{APP_BUILD}"

    def log_message(self, fmt, *args):
        return

    def _send_bytes(self, data, content_type, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload).encode("utf-8")
        self._send_bytes(data, "application/json; charset=utf-8", status)

    def _serve_html(self, path):
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._send_json({"ok": False, "error": "File not found"}, HTTPStatus.NOT_FOUND)
            return

        # Keep the TV HTML file untouched on disk, but layer the Network Shell 1C
        # channel artwork into the page when it is served. This lets the host
        # replace only main.py while still using the new shared channel assets.
        if path.name.lower() == "tv.html":
            old_render_channel = """function renderChannel(state){const n=state.network||{};const type=n.filler_type||'did_you_know';if(type==='did_you_know')setBackground('/assets/slides/did_you_know_bg.png');else document.getElementById('screen').style.backgroundImage='none';let body='';\n if(type==='did_you_know'){body=`<div class=\"channelCard\"><div class=\"label\">DID YOU KNOW?</div><div class=\"main\">${esc(n.did_you_know||'Elite facts are loading.')}</div><div class=\"small\">${networkNextLine(n)}</div></div>`;}\n else if(type==='sponsor'){body=`<div class=\"channelCard\"><div class=\"label\">ELITE NETWORK SPONSOR</div><div class=\"main\">YOUR BUSINESS COULD BE HERE</div><div class=\"small\">Local â€¢ Regional â€¢ Network-wide sponsor rotations<br>${networkNextLine(n)}</div></div>`;}\n else if(type==='tv_guide'){body=`<div class=\"channelCard\"><div class=\"label\">TODAY ON ELITE</div>${guideMarkup(n)}<div class=\"small\">Sports â€¢ Elite Blitz â€¢ After Dark â€¢ Mini-Games</div></div>`;}\n else {const nx=n.next_event||{};body=`<div class=\"channelCard\"><div class=\"label\">COMING UP ON ELITE</div><div class=\"main\">${esc(nx.title||'ELITE CHANNEL')}</div>${nx.seconds_until!=null?`<div class=\"comingTime\">${formatCountdown(nx.seconds_until)}</div>`:''}<div class=\"small\">${nx.start_iso?`Starts at ${formatNetworkClock(nx.start_iso)}`:'More Elite programming coming up.'}</div></div>`;}\n document.getElementById('overlay').innerHTML=`<div class=\"networkShell\"><div class=\"channelClock\">${esc(n.now_display||'')}</div>${body}</div>`;\n}"""
            new_render_channel = """function renderChannel(state){
const n=state.network||{};
const type=n.filler_type||'did_you_know';
const item=n.content_item||null;
const overlay=document.getElementById('overlay');

function showChannelImage(url){
  setBackground(null);
  const existing=document.getElementById('channelMediaImage');
  if(existing&&existing.dataset.src===url)return;
  overlay.innerHTML=`<div style="position:absolute;inset:0;background:#000;display:flex;align-items:center;justify-content:center"><img id="channelMediaImage" data-src="${esc(url)}" src="${esc(url)}" style="width:100%;height:100%;object-fit:contain"></div>`;
}

if(type==='off_air'){
  setBackground(null);
  overlay.innerHTML=`<div class="networkShell"><div class="channelCard"><div class="label">ELITE NETWORK</div><div class="main">PROGRAMMING RETURNS AT 11 AM</div><div class="small">Sports â€¢ Elite Blitz â€¢ After Dark â€¢ Mini-Games</div></div></div>`;
  return;
}

if(type==='did_you_know'){
  setBackground('/assets/did_you_know_bg.png');
  overlay.innerHTML=`<div style="position:absolute;left:11%;right:11%;top:40%;height:27%;display:flex;align-items:center;justify-content:center;text-align:center;padding:1.5% 3%;font-size:48px;font-weight:950;line-height:1.16;text-shadow:0 3px 14px rgba(0,0,0,.9);overflow:hidden">${esc(n.did_you_know||'Elite facts are loading.')}</div>`;
  return;
}

if(type==='sponsor'){
  if(item){
    showChannelImage(item.url);
    return;
  }

  setBackground('/assets/sponsor_spotlight_slide.png');

  overlay.innerHTML=`<div style="position:absolute;left:17%;right:17%;top:36%;height:31%;display:flex;align-items:center;justify-content:center;text-align:center;padding:2% 4%;font-size:50px;font-weight:1000;line-height:1.08;text-shadow:0 4px 16px rgba(0,0,0,.9)">YOUR BUSINESS COULD BE HERE</div><div style="position:absolute;left:22%;right:27%;bottom:8.8%;text-align:center;font-size:20px;font-weight:850;color:#dbe9ff;text-shadow:0 2px 8px rgba(0,0,0,.9)">Local â€¢ Regional â€¢ Network-wide sponsor rotations &nbsp; â€¢ &nbsp; ${networkNextLine(n)}</div>`;

  return;
}

if(type==='live_event'&&item){
  showChannelImage(item.url);
  return;
}

if(type==='promo'&&item){
  showChannelImage(item.url);
  return;
}

if(type==='funny_clip'&&item){

  setBackground(null);

  const existing=
    document.getElementById(
      'channelFunnyClip'
    );

  if(
    existing&&
    existing.dataset.src===item.url
  ){
    return;
  }

  overlay.innerHTML=`<div style="position:absolute;inset:0;background:#000;display:flex;align-items:center;justify-content:center"><video id="channelFunnyClip" data-src="${esc(item.url)}" src="${esc(item.url)}" autoplay playsinline style="width:100%;height:100%;object-fit:contain"></video></div>`;

  const video=
    document.getElementById(
      'channelFunnyClip'
    );

  if(video){

    const playPromise=
      video.play();

    if(
      playPromise&&
      playPromise.catch
    ){

      playPromise.catch(
        ()=>{
          video.muted=true;
          video.play().catch(()=>{});
        }
      );
    }
  }

  return;
}

if(type==='tv_guide'){

  setBackground(
    '/assets/tv_guide_slide.png'
  );

  const rows=
    n.today_guide||[];

  const cards=
    rows.map(
      r=>`<div style="display:grid;grid-template-columns:28% 1fr;align-items:center;gap:2%;padding:1.2% 1.8%;border:2px solid rgba(99,223,255,.55);border-radius:12px;background:rgba(5,10,24,.88);min-height:60px"><div style="font-size:24px;font-weight:1000;color:#ffd85a">${formatNetworkClock(r.start_iso)}</div><div style="font-size:24px;font-weight:950;text-align:left">${esc(r.title||'')}</div></div>`
    ).join('');

  overlay.innerHTML=`<div style="position:absolute;left:5%;right:5%;top:28%;bottom:12.5%;padding:1.4% 1.8%;border-radius:18px;background:rgba(2,7,18,.94);box-shadow:0 15px 45px rgba(0,0,0,.55);overflow:hidden"><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px 18px;height:91%;align-content:start">${cards||'<div style="font-size:38px;font-weight:900">Schedule loadingâ€¦</div>'}</div><div style="position:absolute;left:0;right:0;bottom:1.5%;text-align:center;font-size:18px;font-weight:850;color:#cbd7ea">ELITE NETWORK â€¢ SPORTS â€¢ BLITZ â€¢ AFTER DARK â€¢ MINI-GAMES</div></div>`;

  return;
}

document.getElementById(
  'screen'
).style.backgroundImage='none';

const nx=
  n.next_event||{};

const body=`<div class="channelCard"><div class="label">COMING UP ON ELITE</div><div class="main">${esc(nx.title||'ELITE CHANNEL')}</div>${nx.seconds_until!=null?`<div class="comingTime">${formatCountdown(nx.seconds_until)}</div>`:''}<div class="small">${nx.start_iso?`Starts at ${formatNetworkClock(nx.start_iso)}`:'More Elite programming coming up.'}</div></div>`;

overlay.innerHTML=`<div class="networkShell"><div class="channelClock">${esc(n.now_display||'')}</div>${body}</div>`;
}"""
            if old_render_channel in text:
                text = text.replace(old_render_channel, new_render_channel)

        text = text.replace("__AUTO_ELITE_BUILD__", APP_BUILD)
        self._send_bytes(text.encode("utf-8"), "text/html; charset=utf-8")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if os.environ.get("ELITE_HEADLESS") == "1" and (path in ("/game-builder", "/admin/game-builder", "/network-monitor") or path.startswith("/api/admin/")):
            self.send_error(403, "Administration disabled on public server")
            return
        query = parse_qs(parsed.query)

        if path in ("/", "/tv"):
            return self._serve_html(WEB_DIR / "tv.html")

        if path == "/player":
            return self._serve_html(WEB_DIR / "player.html")

        if path == "/join-qr.png":
            join_url = (
                get_player_join_url()
            )

            qr_image = qrcode.make(
                join_url
            )

            buffer = io.BytesIO()

            qr_image.save(
                buffer,
                format="PNG",
            )

            return self._send_bytes(
                buffer.getvalue(),
                "image/png",
            )

        # ====================================================
        # DROP-IN ELITE CHANNEL MEDIA
        # ====================================================

        if path.startswith(
            "/channel-content/"
        ):

            parts = (
                path.strip("/")
                .split("/")
            )

            if len(parts) != 3:

                return self._send_json(
                    {
                        "ok": False,
                        "error":
                            "Invalid channel content path",
                    },
                    HTTPStatus.NOT_FOUND,
                )

            _, kind, index_text = parts

            folders = (
                NETWORK.schedule
                .get(
                    "channel",
                    {},
                )
                .get(
                    "content_folders",
                    {},
                )
                or {}
            )

            rel_folder = (
                folders.get(kind)
            )

            if not rel_folder:

                return self._send_json(
                    {
                        "ok": False,
                        "error":
                            "Unknown content type",
                    },
                    HTTPStatus.NOT_FOUND,
                )

            folder = (
                BASE_DIR
                / rel_folder
            ).resolve()

            try:
                safe = (
                    folder == BASE_DIR
                    or
                    BASE_DIR in folder.parents
                )
            except Exception:
                safe = False

            if (
                not safe
                or
                not folder.is_dir()
            ):

                return self._send_json(
                    {
                        "ok": False,
                        "error":
                            "Content folder unavailable",
                    },
                    HTTPStatus.NOT_FOUND,
                )

            allowed = (
                {
                    ".mp4",
                    ".webm",
                }
                if kind == "funny_clip"
                else
                {
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                }
            )

            media_files = sorted(
                [
                    item
                    for item
                    in folder.iterdir()
                    if (
                        item.is_file()
                        and
                        item.suffix.lower()
                        in allowed
                    )
                ],
                key=lambda p:
                    p.name.lower(),
            )

            if not media_files:

                return self._send_json(
                    {
                        "ok": False,
                        "error":
                            "No channel media available",
                    },
                    HTTPStatus.NOT_FOUND,
                )

            try:
                media_index = int(
                    index_text
                )
            except Exception:

                return self._send_json(
                    {
                        "ok": False,
                        "error":
                            "Invalid media index",
                    },
                    HTTPStatus.NOT_FOUND,
                )

            if (
                media_index < 0
                or
                media_index
                >= len(media_files)
            ):

                return self._send_json(
                    {
                        "ok": False,
                        "error":
                            "Media index unavailable",
                    },
                    HTTPStatus.NOT_FOUND,
                )

            media_file = (
                media_files[
                    media_index
                ]
            )

            content_type = (
                mimetypes.guess_type(
                    media_file.name
                )[0]
                or
                "application/octet-stream"
            )

            return self._send_bytes(
                media_file.read_bytes(),
                content_type,
            )


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

        if path == "/network-monitor":
            return self._serve_html(WEB_DIR / "network_monitor.html")

        if path == "/api/admin/game-builder/games":

            try:

                games = get_review_games()

                return self._send_json(
                    {
                        "ok": True,
                        "games": games,
                    }
                )

            except Exception as exc:

                return self._send_json(
                    {
                        "ok": False,
                        "error": (
                            "Game list error: "
                            f"{exc}"
                        ),
                    },
                    HTTPStatus.INTERNAL_SERVER_ERROR,
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
            team_id = query.get(
                "team_id",
                [None],
            )[0]

            device_token = query.get(
                "device_token",
                [None],
            )[0]

            server_session_id = query.get(
                "server_session_id",
                [None],
            )[0]

            network_state = (
                NETWORK_CONTROL.get_snapshot()
            )

            state = ENGINE.get_public_state(
                team_id,
                device_token,
                server_session_id,
            )

            state["network"] = network_state

            if state.get("team"):
                state["mini_team_response"] = (
                    NETWORK_CONTROL
                    .mini_game
                    .get_team_response(
                        team_id
                    )
                )
            else:
                state["mini_team_response"] = None

            state["join_url"] = (
                get_player_join_url()
            )

            return self._send_json(
                {
                    "ok": True,
                    "state": state,
                }
            )
        # ====================================================
        # MINI-GAMES - SKEE-BALL SHELL
        # ====================================================

        if path == "/mini-games/skee-ball":
            self.send_response(
                HTTPStatus.FOUND
            )
            self.send_header(
                "Location",
                "/mini-games/skee-ball/",
            )
            self.end_headers()
            return

        if path == "/mini-games/skee-ball/":
            return self._serve_html(
                WEB_DIR
                / "mini_games"
                / "skee_ball"
                / "index.html"
            )

        if path == "/mini-games/skee-ball/game.js":

            file_path = (
                WEB_DIR
                / "mini_games"
                / "skee_ball"
                / "game.js"
            )

            try:
                return self._send_bytes(
                    file_path.read_bytes(),
                    "application/javascript; charset=utf-8",
                )

            except FileNotFoundError:
                return self._send_json(
                    {
                        "ok": False,
                        "error": "Skee-Ball game.js not found",
                    },
                    HTTPStatus.NOT_FOUND,
                )

        if path == "/mini-games/skee-ball/style.css":

            file_path = (
                WEB_DIR
                / "mini_games"
                / "skee_ball"
                / "style.css"
            )

            try:
                return self._send_bytes(
                    file_path.read_bytes(),
                    "text/css; charset=utf-8",
                )

            except FileNotFoundError:
                return self._send_json(
                    {
                        "ok": False,
                        "error": "Skee-Ball style.css not found",
                    },
                    HTTPStatus.NOT_FOUND,
                )

        if path == "/api/health":
            return self._send_json(
                {"ok": True, "service": "Auto Elite Local", "app_build": APP_BUILD}
            )
        if path == "/api/monitor":
            return self._send_json({"ok": True, "heartbeat": HEARTBEAT.snapshot()})
        if path.startswith("/assets/"):
            rel = path[len("/assets/"):].lstrip("/")
            asset_root = (BASE_DIR / "assets").resolve()

            # Normal location first. A few fallback aliases make the theme test
            # tolerant of either assets/slides/... or assets/... placement while
            # we are still assembling the art package.
            rel_candidates = [rel]
            if rel.startswith("slides/sports/"):
                rel_candidates.append(rel[len("slides/"):])
            elif rel.startswith("slides/after_dark/"):
                rel_candidates.append(rel[len("slides/"):])
            elif rel == "slides/did_you_know_bg.png":
                rel_candidates.append("did_you_know_bg.png")

            for rel_candidate in rel_candidates:
                candidate = (asset_root / rel_candidate).resolve()
                if not (asset_root in candidate.parents or candidate == asset_root):
                    continue
                if candidate.is_file():
                    content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                    return self._send_bytes(candidate.read_bytes(), content_type)

            return self._send_json({"ok": False, "error": "Asset not found"}, HTTPStatus.NOT_FOUND)

        self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("Invalid JSON request.")

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            payload = self._read_json_body()

            # ====================================================
            # ELITE NETWORK GAME BUILDER â€” SAVE QUESTION
            # ====================================================

            # ====================================================
            # ELITE NETWORK GAME BUILDER â€” REVIEW / APPROVAL
            # ====================================================

            # ====================================================
            # ELITE NETWORK GAME BUILDER â€” AI PREP
            # ====================================================

            if parsed.path == "/api/admin/game-builder/auto-build":

                try:

                    days = int(
                        payload.get(
                            "days",
                            7,
                        )
                    )

                    start_date = (
                        payload.get(
                            "start_date"
                        )
                        or None
                    )

                    result = build_auto_games(
                        days,
                        start_date,
                    )

                    return self._send_json(
                        {
                            "ok": True,
                            "result": result,
                        }
                    )

                except (
                    ValueError,
                    RuntimeError,
                ) as exc:

                    return self._send_json(
                        {
                            "ok": False,
                            "error": str(exc),
                        },
                        HTTPStatus.BAD_REQUEST,
                    )

                except Exception as exc:

                    return self._send_json(
                        {
                            "ok": False,
                            "error": (
                                "Auto Build error: "
                                f"{exc}"
                            ),
                        },
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )


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

                result = review_game_builder_question(
                    payload
                )

                return self._send_json(
                    {
                        "ok": True,
                        "result": result,
                    }
                )

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
                HEARTBEAT.note_tv_client(
                    payload=payload,
                    client_ip=(self.client_address[0] if self.client_address else ""),
                )
                return self._send_json({"ok": True})

            if parsed.path == "/api/join":
                team = ENGINE.join_team(
                    payload.get("team_name", ""), client_id=payload.get("client_id", "")
                )
                return self._send_json(
                    {"ok": True, "team": team, "server_session_id": ENGINE.server_session_id}
                )

            if parsed.path == "/api/team-name":
                team = ENGINE.rename_team(
                    payload.get("team_id"),
                    payload.get("team_name", ""),
                    actor="player",
                    device_token=payload.get("device_token"),
                    server_session_id=payload.get("server_session_id"),
                )
                return self._send_json(
                    {"ok": True, "team": team, "server_session_id": ENGINE.server_session_id}
                )

            if parsed.path == "/api/still-playing":
                team = ENGINE.still_playing(
                    payload.get("team_id"),
                    device_token=payload.get("device_token"),
                    server_session_id=payload.get("server_session_id"),
                )
                return self._send_json({"ok": True, "team": team})

            if parsed.path == "/api/wager":
                wager = ENGINE.submit_wager(
                    payload.get("team_id"),
                    payload.get("percent"),
                    device_token=payload.get("device_token"),
                    server_session_id=payload.get("server_session_id"),
                )

                return self._send_json(
                    {
                        "ok": True,
                        "wager": wager,
                    }
                )

            if parsed.path == "/api/channel-content-finished":

                result = (
                    NETWORK
                    .advance_channel_content(
                        expected_kind="funny_clip",
                    )
                )

                return self._send_json(
                    {
                        "ok": True,
                        "result": result,
                    }
                )


            if parsed.path == "/api/skee-control":

                team_id = payload.get(
                    "team_id"
                )

                with ENGINE.lock:

                    team = (
                        ENGINE
                        ._authorized_team_locked(
                            team_id,
                            payload.get(
                                "device_token"
                            ),
                            payload.get(
                                "server_session_id"
                            ),
                        )
                    )

                if team is None:
                    raise ValueError(
                        "This phone is not attached "
                        "to that team. Rejoin first."
                    )

                control = (
                    NETWORK_CONTROL
                    .mini_game
                    .submit_skee_control(
                        team_id,
                        payload.get(
                            "action",
                            "",
                        ),
                    )
                )

                return self._send_json(
                    {
                        "ok": True,
                        "control": control,
                    }
                )


            if parsed.path == "/api/skee-result":

                result = (
                    NETWORK_CONTROL
                    .mini_game
                    .register_skee_result(
                        payload.get(
                            "points",
                            0,
                        )
                    )
                )

                return self._send_json(
                    result
                )


            if parsed.path == "/api/mini-answer":
                choice_index = payload.get(
                    "choice_index"
                )

                if isinstance(
                    choice_index,
                    bool,
                ):
                    raise ValueError(
                        "Invalid mini-game answer."
                    )

                try:
                    choice_index = int(
                        choice_index
                    )

                except Exception:
                    raise ValueError(
                        "Invalid mini-game answer."
                    )

                team_id = payload.get(
                    "team_id"
                )

                with ENGINE.lock:

                    team = (
                        ENGINE._authorized_team_locked(
                            team_id,
                            payload.get(
                                "device_token"
                            ),
                            payload.get(
                                "server_session_id"
                            ),
                        )
                    )

                    if team is None:
                        raise ValueError(
                            "This phone is not attached "
                            "to that team. Rejoin first."
                        )

                response = (
                    NETWORK_CONTROL
                    .mini_game
                    .submit_answer(
                        team_id,
                        choice_index,
                    )
                )

                return self._send_json(
                    {
                        "ok": True,
                        "response": response,
                    }
                )

            if parsed.path == "/api/answer":
                choice_index = payload.get(
                    "choice_index"
                )

                if isinstance(
                    choice_index,
                    bool,
                ):
                    raise ValueError(
                        "Invalid answer choice."
                    )

                try:
                    choice_index = int(
                        choice_index
                    )

                except Exception:
                    raise ValueError(
                        "Invalid answer choice."
                    )

                response = ENGINE.submit_answer(
                    payload.get("team_id"),
                    choice_index,
                    device_token=payload.get("device_token"),
                    server_session_id=payload.get("server_session_id"),
                )

                return self._send_json(
                    {
                        "ok": True,
                        "response": response,
                    }
                )

            if parsed.path == "/api/final":
                response = ENGINE.submit_final_wager(
                    payload.get("team_id"),
                    payload.get("decision"),
                    payload.get("answer_text", ""),
                    device_token=payload.get("device_token"),
                    server_session_id=payload.get("server_session_id"),
                )
                return self._send_json({"ok": True, "response": response})

            self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json(
                {"ok": False, "error": f"Server error: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )


def start_http_server():
    server = ThreadingHTTPServer((HOST, PORT), EliteRequestHandler)
    thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="AutoEliteHTTP"
    )
    thread.start()
    return server


class HostApp:
    def __init__(self, root, engine):
        self.root = root
        self.engine = engine
        self.local_ip = get_local_ip()
        self.join_url = get_player_join_url()
        self.tv_url = f"http://{self.local_ip}:{PORT}/tv"
        self.network = NETWORK
        self.network_control = NETWORK_CONTROL

        root.title("ELITE NETWORK SHELL - Host")
        root.geometry("1280x760")
        root.minsize(1280, 760)
        root.maxsize(1280, 760)
        root.configure(bg="black")

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        tk.Label(
            self.root,
            text=f"ELITE NETWORK SHELL - LOCAL HOST   â€¢   BUILD {APP_BUILD}",
            font=("Arial", 24, "bold"),
            fg="white",
            bg="black",
        ).pack(pady=(12, 8))

        body = tk.Frame(self.root, bg="black")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        controls = tk.Frame(body, bg="#101010", width=220)
        controls.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        controls.grid_propagate(False)

        tk.Label(
            controls,
            text="GAME CONTROLS",
            font=("Arial", 13, "bold"),
            fg="white",
            bg="#101010",
        ).pack(pady=(14, 8))

        self.auto_round_button = self._add_button(
            controls, "START FULL AUTO GAME", self.host_toggle_auto_game, bg="#7eeaff"
        )
        self.category_button = self._add_button(
            controls, "Show Category", self.host_show_category
        )
        self.wager_button = self._add_button(
            controls, "Show Hint + Wager", self.host_show_wager, bg="#f0b429"
        )
        self.question_button = self._add_button(
            controls, "Show Question", self.host_show_question
        )
        self.start_timer_button = self._add_button(
            controls, "Start Timer", self.host_start_timer
        )
        self._add_button(controls, "Stop Timer", self.host_stop_timer)
        self._add_button(controls, "Reveal Answer", self.host_reveal)
        self.speed_bonus_button = self._add_button(
            controls, "Show Speed Bonus", self.host_speed_bonus, bg="#ffd85a"
        )
        self.scores_button = self._add_button(controls, "Show Scores", self.host_scores)
        self.next_question_button = self._add_button(
            controls, "Next Question", self.host_next_question, bg="#63c7ff"
        )
        self._add_button(
            controls, "Reset Current Q", self.host_reset, bg="#d9a300"
        )
        self._add_button(
            controls, "Reset Full Game", self.host_reset_game, bg="#e67e22"
        )

        tk.Label(
            controls,
            text="PLAYER JOIN",
            font=("Arial", 11, "bold"),
            fg="#00e5ff",
            bg="#101010",
        ).pack(pady=(16, 5))
        tk.Label(
            controls,
            text=self.join_url,
            font=("Arial", 9),
            fg="white",
            bg="#101010",
            wraplength=195,
            justify="center",
        ).pack(padx=8)
        tk.Label(
            controls,
            text="TV URL",
            font=("Arial", 11, "bold"),
            fg="#00e5ff",
            bg="#101010",
        ).pack(pady=(10, 5))
        tk.Label(
            controls,
            text=self.tv_url,
            font=("Arial", 9),
            fg="white",
            bg="#101010",
            wraplength=195,
            justify="center",
        ).pack(padx=8)

        work = tk.Frame(body, bg="black")
        work.grid(row=0, column=1, sticky="nsew")

        network_box = tk.Frame(work, bg="#151515", bd=1, relief="solid")
        network_box.pack(fill="x", padx=8, pady=(2, 8))

        top_line = tk.Frame(network_box, bg="#151515")
        top_line.pack(fill="x", padx=10, pady=(8, 3))
        tk.Label(
            top_line, text="NETWORK SCHEDULER TEST", font=("Arial", 11, "bold"),
            fg="#7eeaff", bg="#151515"
        ).pack(side="left")
        self.network_clock_label = tk.Label(
            top_line, text="", font=("Arial", 11, "bold"), fg="white", bg="#151515"
        )
        self.network_clock_label.pack(side="right")

        self.network_now_label = tk.Label(
            network_box, text="NOW: --", font=("Arial", 14, "bold"),
            fg="#ffd85a", bg="#151515", anchor="w"
        )
        self.network_now_label.pack(fill="x", padx=10)
        self.network_next_label = tk.Label(
            network_box, text="NEXT: --", font=("Arial", 10, "bold"),
            fg="#bbbbbb", bg="#151515", anchor="w"
        )
        self.network_next_label.pack(fill="x", padx=10, pady=(1, 5))

        sim_line = tk.Frame(network_box, bg="#151515")
        sim_line.pack(fill="x", padx=10, pady=(0, 5))
        tk.Label(
            sim_line, text="SIM TIME:", font=("Arial", 9, "bold"), fg="white", bg="#151515"
        ).pack(side="left")
        self.sim_time_var = tk.StringVar(value="5:59:50 PM")
        self.sim_time_combo = ttk.Combobox(
            sim_line, textvariable=self.sim_time_var, width=12, state="normal",
            values=("11:09:50 AM", "11:10:00 AM", "1:59:50 PM", "2:00:00 PM", "2:28:00 PM",
                    "5:49:50 PM", "5:50:00 PM", "5:59:50 PM", "6:00:00 PM", "6:28:00 PM",
                    "6:59:50 PM", "7:00:00 PM", "8:00:00 PM", "8:59:50 PM", "9:00:00 PM",
                    "9:28:00 PM", "9:30:00 PM", "10:00:00 PM", "10:28:00 PM")
        )
        self.sim_time_combo.pack(side="left", padx=(6, 6))
        tk.Button(
            sim_line, text="JUMP", command=self.host_jump_network_time,
            font=("Arial", 9, "bold"), bg="#7eeaff", fg="black", width=8
        ).pack(side="left", padx=(0, 5))
        tk.Button(
            sim_line, text="LIVE TIME", command=self.host_network_live_time,
            font=("Arial", 9, "bold"), bg="#7cff8f", fg="black", width=10
        ).pack(side="left")
        tk.Button(
            sim_line, text="RUN QUICK 3", command=self.host_run_mini_game,
            font=("Arial", 9, "bold"), bg="#ffd85a", fg="black", width=14
        ).pack(side="left", padx=(6, 0))

        tk.Button(
            sim_line,
            text="RUN REACTION RUSH",
            command=self.host_run_reaction_rush,
            font=("Arial", 9, "bold"),
            bg="#ff9f43",
            fg="black",
            width=18,
        ).pack(side="left", padx=(6, 0))

        tk.Button(
            sim_line,
            text="RUN SKEE-BALL",
            command=self.host_run_skee_ball,
            font=("Arial", 9, "bold"),
            bg="#7fd3ff",
            fg="black",
            width=16,
        ).pack(side="left", padx=(6, 0))
        self.network_log_label = tk.Label(
            network_box, text="", font=("Consolas", 8), fg="#aaaaaa", bg="#151515",
            justify="left", anchor="w"
        )
        self.network_log_label.pack(fill="x", padx=10, pady=(0, 7))

        self.round_label = tk.Label(
            work, text="", font=("Arial", 18, "bold"), fg="white", bg="black"
        )
        self.round_label.pack(pady=(4, 2))
        self.mode_label = tk.Label(
            work, text="", font=("Arial", 11, "bold"), fg="#ffd85a", bg="black"
        )
        self.mode_label.pack(pady=1)
        self.category_label = tk.Label(
            work, text="", font=("Arial", 16, "bold"), fg="#00e5ff", bg="black"
        )
        self.category_label.pack(pady=2)
        self.question_label = tk.Label(
            work,
            text="",
            font=("Arial", 17, "bold"),
            fg="white",
            bg="black",
            wraplength=900,
            justify="center",
        )
        self.question_label.pack(pady=(4, 6))

        info = tk.Frame(work, bg="black")
        info.pack(fill="x", pady=(0, 8))
        self.timer_label = tk.Label(
            info, text="Timer: --", font=("Arial", 22, "bold"), fg="#00e5ff", bg="black"
        )
        self.timer_label.pack(side="left", padx=(10, 25))
        self.state_label = tk.Label(
            info, text="", font=("Arial", 12, "bold"), fg="yellow", bg="black"
        )
        self.state_label.pack(side="left", padx=10)
        self.count_label = tk.Label(
            info, text="", font=("Arial", 12, "bold"), fg="white", bg="black"
        )
        self.count_label.pack(side="right", padx=(10, 18))

        cols = ("team", "name", "score", "status", "wager", "answer", "time", "points")
        self.tree = ttk.Treeview(work, columns=cols, show="headings", height=18)
        headings = {
            "team": "Team #",
            "name": "Team Name",
            "score": "Score",
            "status": "Status",
            "wager": "Wager",
            "answer": "Current Answer",
            "time": "Response",
            "points": "Pts",
        }
        widths = {
            "team": 65,
            "name": 190,
            "score": 65,
            "status": 95,
            "wager": 100,
            "answer": 190,
            "time": 90,
            "points": 65,
        }
        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center")
        self.tree.column("name", anchor="w")
        self.tree.column("answer", anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        team_tools = tk.Frame(work, bg="black")
        team_tools.pack(fill="x", padx=10, pady=(0, 6))
        tk.Button(
            team_tools,
            text="Edit Selected Team Name",
            command=self.host_edit_team_name,
            font=("Arial", 10, "bold"),
            bg="#63c7ff",
            fg="black",
        ).pack(side="left")
        tk.Label(
            team_tools,
            text="Player name changes lock when the first category is shown.",
            font=("Arial", 9),
            fg="#aaaaaa",
            bg="black",
        ).pack(side="left", padx=(12, 0))

        self.note_label = tk.Label(
            work,
            text=(
                "Blitz Auto: full 4-round unattended flow â€¢ inactivity-safe progression â€¢ "
                "presentation timing is controlled from game_data.json."
            ),
            font=("Arial", 10),
            fg="#aaaaaa",
            bg="black",
        )
        self.note_label.pack(pady=(0, 2))

    def _add_button(self, parent, text, command, bg="#2ecc71"):
        button = tk.Button(
            parent,
            text=text,
            command=command,
            width=18,
            font=("Arial", 10, "bold"),
            bg=bg,
            fg="black",
            activebackground=bg,
        )
        button.pack(pady=3)
        return button

    def _run_host_action(self, fn):
        try:
            fn()
        except ValueError as exc:
            messagebox.showwarning("Auto Elite", str(exc))
        except Exception as exc:
            messagebox.showerror("Auto Elite Error", str(exc))

    def host_jump_network_time(self):
        self._run_host_action(lambda: self.network.set_simulated_time(self.sim_time_var.get()))

    def host_network_live_time(self):
        self._run_host_action(self.network.return_to_live_time)

    def host_run_mini_game(self):
        self._run_host_action(
            self.network_control.run_mini_game_now
        )

    def host_run_reaction_rush(self):
        self._run_host_action(
            self.network_control.run_reaction_rush_now
        )

    def host_run_skee_ball(self):
        self._run_host_action(
            self.network_control.run_skee_ball_now
        )

    def host_toggle_auto_game(self):
        self._run_host_action(self.engine.toggle_auto_game)

    def host_show_category(self):
        self._run_host_action(self.engine.show_category)

    def host_show_wager(self):
        self._run_host_action(self.engine.show_wager)

    def host_show_question(self):
        self._run_host_action(self.engine.show_question)

    def host_start_timer(self):
        self._run_host_action(self.engine.start_timer)

    def host_stop_timer(self):
        self._run_host_action(self.engine.stop_timer)

    def host_reveal(self):
        self._run_host_action(self.engine.reveal_answer)

    def host_speed_bonus(self):
        self._run_host_action(self.engine.show_speed_bonus)

    def host_scores(self):
        self._run_host_action(self.engine.show_scores)

    def host_next_question(self):
        self._run_host_action(self.engine.next_question)

    def host_reset(self):
        self._run_host_action(self.engine.reset_question)

    def host_reset_game(self):
        self._run_host_action(self.engine.reset_game)

    def host_edit_team_name(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Auto Elite", "Select a team in the table first.")
            return

        team_id = selected[0]
        with self.engine.lock:
            team = self.engine.teams.get(team_id)
            if not team:
                messagebox.showwarning("Auto Elite", "That team session no longer exists.")
                return
            team_number = team["number"]
            current_name = team["name"]

        new_name = simpledialog.askstring(
            "Edit Team Name",
            f"Team #{team_number} name:",
            initialvalue=current_name,
            parent=self.root,
        )
        if new_name is None:
            return
        self._run_host_action(lambda: self.engine.rename_team(team_id, new_name, actor="host"))

    def refresh(self):
        state = self.engine.get_host_snapshot()
        network = self.network_control.get_snapshot()
        q = state["question"]

        program = network.get("program", {})
        next_event = network.get("next_event") or {}
        sim_tag = "  â€¢  SIMULATED" if network.get("simulated") else "  â€¢  LIVE"
        self.network_clock_label.config(text=f"{network.get('now_display', '--')}{sim_tag}")
        self.network_now_label.config(text=f"NOW: {program.get('title', 'ELITE CHANNEL')}")
        if next_event:
            try:
                next_dt = datetime.fromisoformat(next_event.get("start_iso"))
                next_clock = next_dt.strftime("%I:%M %p").lstrip("0")
            except Exception:
                next_clock = next_event.get("start", "--")
            self.network_next_label.config(
                text=f"NEXT: {next_event.get('title', '--')}  â€¢  {next_clock}"
            )
        else:
            self.network_next_label.config(text="NEXT: --")
        recent_log = network.get("event_log", [])[-3:]
        self.network_log_label.config(text="   |   ".join(recent_log))

        self.round_label.config(
            text=(
                f"ROUND {q['round']}  |  QUESTION {q['question_number']} "
                f"OF {state['round_question_count']}  |  GAME Q {state['question_index'] + 1}/{state['question_count']}"
            )
        )

        scoring = q["scoring_type"].upper()
        if scoring == "FIXED":
            mode_text = f"REGULAR â€¢ {q['fixed_points']} POINTS â€¢ {q['timer_seconds']} SEC"
        elif scoring == "FASTEST":
            bonus_values = q.get("speed_bonus_points", [])
            bonus_text = (
                " â€¢ TOP 3 BONUS "
                + "/".join(f"+{value}" for value in bonus_values)
                if bonus_values
                else ""
            )
            mode_text = (
                f"FASTEST ANSWER â€¢ {q['max_points']}â†’{q['min_points']} POINTS â€¢ "
                f"{q['timer_seconds']} SEC{bonus_text}"
            )
        elif scoring == "ROULETTE":
            mode_text = (
                f"ELITE ROULETTE â€¢ WAGER {q['wager_seconds']} SEC â€¢ "
                f"QUESTION {q['timer_seconds']} SEC"
            )
        else:
            mode_text = f"ELITE WAGER â€¢ ALL IN OR SAVE â€¢ {q['timer_seconds']} SEC"
        self.mode_label.config(text=mode_text)

        self.category_label.config(text=f"CATEGORY: {q['category']}")
        if state["screen"] == "wager":
            self.question_label.config(text=f"HINT: {q['hint']}")
        elif state["screen"] == "speed_bonus":
            winners = state.get("speed_bonus_winners", [])
            winner_text = "   â€¢   ".join(
                f"#{item['rank']} {item['name']} +{item['bonus']}" for item in winners
            )
            self.question_label.config(text=f"SPEED BONUS: {winner_text}")
        elif state["screen"] == "round_complete":
            self.question_label.config(text=f"ROUND {q['round']} COMPLETE")
        elif state["screen"] == "game_complete":
            self.question_label.config(text="GAME COMPLETE")
        else:
            self.question_label.config(text=q["question"])

        timer_text = "--"
        if state["timer_running"]:
            timer_text = f"{state['timer_remaining']:.1f}"
        elif state["screen"] in ("wager", "question"):
            timer_text = str(int(state["timer_display_seconds"]))

        if state["screen"] == "speed_bonus":
            self.timer_label.config(
                text=f"Speed Bonus: {state.get('speed_bonus_remaining', 0):.1f}s"
            )
        elif q["scoring_type"] == "fastest" and state["screen"] == "question":
            current_value = state.get("current_fastest_points")
            self.timer_label.config(
                text=f"Timer: {timer_text}   |   Current Value: {current_value} pts"
            )
        else:
            self.timer_label.config(text=f"Timer: {timer_text}")

        auto_suffix = (
            f"  |  FULL AUTO â€¢ NEXT {state.get('auto_next_transition_in', 0):.1f}s"
            if state.get("auto_game_running")
            else ""
        )
        self.state_label.config(text=f"{state['screen'].upper()}  |  {state['status']}{auto_suffix}")
        self.auto_round_button.config(
            text="STOP FULL AUTO" if state.get("auto_game_running") else "START FULL AUTO GAME",
            bg="#ff8a80" if state.get("auto_game_running") else "#7eeaff",
            activebackground="#ff8a80" if state.get("auto_game_running") else "#7eeaff",
            state=(
                "normal"
                if state.get("auto_game_running") or state["screen"] != "game_complete"
                else "disabled"
            ),
        )
        self.count_label.config(
            text=(
                f"Teams: {state['team_count']}   Active: {state['active_team_count']}   "
                f"Eligible: {state['eligible_team_count']}   "
                f"Wagers: {state['wager_count']}/{state['eligible_team_count']}   "
                f"Answers: {state['answer_count']}/{state['eligible_team_count']}"
            )
        )

        is_roulette = q["scoring_type"] == "roulette"
        self.wager_button.config(
            state="normal" if is_roulette and state["screen"] == "category" else "disabled"
        )

        if is_roulette and state["screen"] == "category":
            self.question_button.config(state="disabled")
        elif is_roulette and state["screen"] == "wager":
            ready = state.get("all_wagers_in") or not state["timer_running"]
            self.question_button.config(state="normal" if ready else "disabled")
        elif state["screen"] == "category":
            self.question_button.config(state="normal")
        else:
            self.question_button.config(state="disabled")

        if state["screen"] == "wager":
            self.start_timer_button.config(text="Wager Timer Running", state="disabled")
        elif state["screen"] == "question":
            label = "Start Final Timer" if q["scoring_type"] == "final_wager" else "Start Answer Timer"
            self.start_timer_button.config(text=label, state="normal")
        else:
            self.start_timer_button.config(text="Start Timer", state="disabled")

        has_speed_bonus = bool(q.get("speed_bonus_points"))
        has_speed_winners = bool(state.get("speed_bonus_winners"))
        self.speed_bonus_button.config(
            state=(
                "normal"
                if state["screen"] == "reveal" and has_speed_bonus and has_speed_winners
                else "disabled"
            )
        )
        self.scores_button.config(
            state=(
                "normal"
                if state["screen"] == "reveal" and not (has_speed_bonus and has_speed_winners)
                else "disabled"
            )
        )

        if state["screen"] == "round_complete":
            self.next_question_button.config(
                text=f"Start Round {q['round'] + 1}", state="normal"
            )
        elif state["screen"] == "game_complete":
            self.next_question_button.config(text="Game Complete", state="disabled")
        elif self.engine._current_is_last_in_round():
            label = "Finish Game" if state["question_index"] == state["question_count"] - 1 else f"Complete Round {q['round']}"
            self.next_question_button.config(text=label, state="normal")
        else:
            self.next_question_button.config(text="Next Question", state="normal")

        existing = set(self.tree.get_children())
        seen = set()
        for row in state["host_rows"]:
            iid = row["id"]
            seen.add(iid)
            values = (
                row["number"],
                row["name"],
                row["score"],
                row["status"],
                row["wager"],
                row["answer"],
                row["time"],
                row["points"],
            )
            if iid in existing:
                self.tree.item(iid, values=values)
            else:
                self.tree.insert("", "end", iid=iid, values=values)

        for iid in existing - seen:
            self.tree.delete(iid)

        self.root.after(POLL_MS, self.refresh)


def run_app():
    server = None
    try:
        server = start_http_server()
        automation_thread = threading.Thread(
            target=ENGINE.automation_worker, daemon=True, name="AutoEliteRoundFlow"
        )
        automation_thread.start()
        network_thread = threading.Thread(
            target=NETWORK_CONTROL.worker, daemon=True, name="EliteNetworkScheduler"
        )
        network_thread.start()
        heartbeat_thread = threading.Thread(
            target=HEARTBEAT.worker, daemon=True, name="EliteNetworkHeartbeat"
        )
        heartbeat_thread.start()
        root = tk.Tk()
        HostApp(root, ENGINE)
        root.mainloop()
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


def run_headless():
    server = None
    try:
        server = start_http_server()

        threading.Thread(
            target=ENGINE.automation_worker,
            daemon=True,
            name="AutoEliteRoundFlow",
        ).start()

        threading.Thread(
            target=NETWORK_CONTROL.worker,
            daemon=True,
            name="EliteNetworkScheduler",
        ).start()

        threading.Thread(
            target=HEARTBEAT.worker,
            daemon=True,
            name="EliteNetworkHeartbeat",
        ).start()

        print(
            f"Elite Network headless server running on port {PORT}",
            flush=True,
        )

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("Elite Network headless server stopping.", flush=True)

    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    if os.environ.get("ELITE_HEADLESS") == "1":
        run_headless()
    else:
        run_app()