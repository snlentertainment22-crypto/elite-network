from game_builder.admin_auto_build import plan_auto_games

print("1-DAY PREVIEW")

p = plan_auto_games(1)

print("DATES:", p["start_date"], "to", p["end_date"])
print("GAMES:", p["game_count"])
print("UNIQUE QUESTIONS:", p["question_count"])
print(
    "DAY 1 QUESTIONS:",
    p["day_plans"][0]["question_count"],
)

print()
print("2-DAY CAPACITY TEST")

try:
    plan_auto_games(2)
    print("ERROR: 2-day build unexpectedly succeeded")
except Exception as exc:
    print("EXPECTED STOP:", exc)
