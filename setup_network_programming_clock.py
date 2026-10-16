import json
import shutil
from pathlib import Path
from datetime import datetime

root = Path(".")
schedule_path = root / "network_schedule.json"

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

backup = root / f"network_schedule.BEFORE-PROGRAMMING-CLOCK-{stamp}.json"

shutil.copy2(
    schedule_path,
    backup,
)

data = json.loads(
    schedule_path.read_text(
        encoding="utf-8"
    )
)

channel = data.setdefault(
    "channel",
    {}
)

# ============================================================
# ELITE NETWORK DAILY CHANNEL CLOCK
# ============================================================

channel["network_start"] = "11:00"
channel["network_end"] = "02:00"

channel["auto_mini_enabled"] = True

# Keep the proven pre-game lead-in timing.
channel["lead_in_enabled"] = True
channel["join_before_mini_seconds"] = 600
channel["mini_game_start_seconds"] = 420
channel["teams_ready_seconds"] = 360

# ============================================================
# CHANNEL CONTENT ROTATION
# ============================================================

channel["content_rotation"] = [
    "sponsor",
    "did_you_know",
    "live_event",
    "tv_guide",
    "sponsor",
    "funny_clip",
    "did_you_know",
    "promo",
    "coming_up",
]

# ============================================================
# LONG-BREAK MINI WINDOWS
#
# Repeating Quick 3 gives it extra weight.
# ============================================================

channel["mini_windows"] = [
    {
        "start": "11:00",
        "end": "14:00",
        "every_minutes": 20,
        "rotation": [
            "quick_3",
            "quick_3",
            "quick_3",
            "reaction_rush",
            "skee_ball",
        ],
    },
    {
        "start": "16:00",
        "end": "17:30",
        "every_minutes": 20,
        "rotation": [
            "quick_3",
            "quick_3",
            "quick_3",
            "reaction_rush",
            "skee_ball",
        ],
    },
    {
        "start": "23:00",
        "end": "02:00",
        "every_minutes": 20,
        "rotation": [
            "quick_3",
            "reaction_rush",
            "skee_ball",
        ],
    },
]

# ============================================================
# MINI BEFORE EVERY BLITZ
# ============================================================

channel["pre_blitz_mini_rotation"] = [
    "quick_3",
    "reaction_rush",
    "skee_ball",
]

channel["skee_ball_fallback"] = "quick_3"

# ============================================================
# DROP-IN CONTENT FOLDERS
# ============================================================

channel["content_folders"] = {
    "sponsor": "assets/channel/sponsors",
    "live_event": "assets/channel/live_events",
    "promo": "assets/channel/promos",
    "funny_clip": "assets/channel/funny_clips",
}

schedule_path.write_text(
    json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
    )
    + "\n",
    encoding="utf-8",
)

folders = [
    root / "assets/channel/sponsors",
    root / "assets/channel/live_events",
    root / "assets/channel/promos",
    root / "assets/channel/funny_clips",
]

for folder in folders:
    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

print("BACKUP:", backup)
print()
print("ELITE NETWORK PROGRAMMING CONFIG INSTALLED")
print("NETWORK HOURS: 11:00 AM -> 2:00 AM")
print("AUTO MINI-GAMES: ENABLED")
print("DAYTIME MINI WEIGHT: MOSTLY QUICK 3")
print("LATE NIGHT MINI ROTATION: ALL THREE")
print("PRE-BLITZ MINI ROTATION: ALL THREE")
print()
print("DROP-IN CONTENT FOLDERS READY:")

for folder in folders:
    print(" -", folder)
