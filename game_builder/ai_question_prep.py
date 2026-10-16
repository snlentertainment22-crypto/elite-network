from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

try:
    from .question_bank import connect, initialize_database
except ImportError:
    from question_bank import connect, initialize_database


# ============================================================
# ELITE NETWORK GAME BUILDER
# AI QUESTION PREP — COST-GUARDED ROULETTE TEST
# Build 1C
#
# HARD COST GUARDS:
#
# Distractors:
#   Maximum 2 generation attempts.
#
# Roulette Hint:
#   Maximum 2 generation attempts.
#
# No endless retry loops.
#
# If distractors pass but hints fail twice:
#   - Keep/save the good distractors.
#   - Mark Roulette hint as NEEDS_MANUAL_HINT.
#   - Mark question not automatically Roulette suitable.
# ============================================================


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
ENV_PATH = PROJECT_DIR / ".env"

load_dotenv(ENV_PATH)


client = OpenAI(
    timeout=60.0,
    max_retries=1,
)


MODEL = "gpt-5.6-luna"

TEST_GAME_KEY = "regular-blitz-test-2022-001"
TEST_SLOT = "R1Q6"


# ============================================================
# COST GUARDS
# ============================================================

MAX_DISTRACTOR_ATTEMPTS = 2
MAX_HINT_ATTEMPTS = 2


# ============================================================
# BASIC HELPERS
# ============================================================


def clean_json_text(text: str) -> str:

    text = (text or "").strip()

    if text.startswith("```json"):
        text = text[len("```json"):].strip()

    elif text.startswith("```"):
        text = text[len("```"):].strip()

    if text.endswith("```"):
        text = text[:-3].strip()

    start = text.find("{")
    end = text.rfind("}")

    if (
        start != -1
        and end != -1
        and end > start
    ):
        text = text[start:end + 1]

    return text.strip()


def normalize_answer(text: str) -> str:

    text = (text or "").lower().strip()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return " ".join(
        text.split()
    )


def answers_too_similar(
    answer_a: str,
    answer_b: str,
) -> bool:

    a = normalize_answer(answer_a)
    b = normalize_answer(answer_b)

    if not a or not b:
        return True

    if a == b:
        return True

    if len(a) >= 4 and len(b) >= 4:

        if a in b or b in a:
            return True

    similarity = SequenceMatcher(
        None,
        a,
        b,
    ).ratio()

    if similarity >= 0.88:
        return True

    return False


def format_feedback(
    issues: list[str] | None,
) -> str:

    if not issues:
        return ""

    lines = "\n".join(
        f"- {issue}"
        for issue in issues
    )

    return f"""
PREVIOUS ATTEMPT WAS REJECTED.

REASONS:
{lines}

Create a DIFFERENT result that specifically fixes
those problems. Do not repeat the rejected approach.
"""


# ============================================================
# LOAD QUESTION
# ============================================================


def load_test_question() -> dict:

    initialize_database()

    conn = connect()

    try:

        row = conn.execute(
            """
            SELECT
                gq.slot_id,
                gq.question_type,

                q.id AS question_id,
                q.category,
                q.question,
                q.correct_answer,
                q.fact_check_date,

                q.wrong_answers_json,
                q.network_status,

                q.roulette_hint,
                q.roulette_hint_status,
                q.roulette_suitable

            FROM game_questions gq

            JOIN games g
              ON g.id = gq.game_id

            JOIN questions q
              ON q.id = gq.question_id

            WHERE g.game_key = ?
              AND gq.slot_id = ?
            """,
            (
                TEST_GAME_KEY,
                TEST_SLOT,
            ),
        ).fetchone()

        if row is None:

            raise RuntimeError(
                f"Could not find "
                f"{TEST_GAME_KEY} / {TEST_SLOT}"
            )

        return dict(row)

    finally:

        conn.close()


# ============================================================
# DISTRACTOR GENERATION
# ============================================================


def generate_distractors(
    item: dict,
    previous_issues: list[str] | None = None,
) -> list[str]:

    retry_feedback = format_feedback(
        previous_issues
    )

    prompt = f"""
You are preparing a multiple-choice trivia question
for Elite Trivia.

QUESTION:
{item["question"]}

CONFIRMED CORRECT ANSWER:
{item["correct_answer"]}

CATEGORY:
{item["category"]}

Create exactly FIVE plausible WRONG answer choices.

CRITICAL ELITE RULE:

There must be exactly ONE defensible correct answer
when the confirmed correct answer and these five
distractors are displayed together.

Every distractor must be unquestionably wrong
for this exact question.

DO NOT use a distractor that:

- is also correct
- could reasonably be argued as correct
- is a synonym of the correct answer
- is an alternate spelling of the correct answer
- is an alias or alternate name for the correct answer
- is a translation of the correct answer
- is a broader or narrower equivalent
- contains the correct answer
- is essentially the same answer with extra words
- overlaps strongly enough that a knowledgeable
  player could dispute the answer key

QUALITY RULES:

- Make every distractor plausible.
- Keep all choices in the same logical answer type.
- Match the specificity of the correct answer.
- Avoid joke answers.
- Avoid obviously impossible answers.
- Do not use "All of the above."
- Do not use "None of the above."
- Do not create trick ambiguity.
- Do not rewrite the question.
- Do not change the confirmed correct answer.

{retry_feedback}

Return ONLY valid JSON:

{{
  "wrong_answers": [
    "Wrong answer 1",
    "Wrong answer 2",
    "Wrong answer 3",
    "Wrong answer 4",
    "Wrong answer 5"
  ]
}}
"""

    response = client.responses.create(
        model=MODEL,
        input=prompt,
        reasoning={
            "effort": "low",
        },
    )

    data = json.loads(
        clean_json_text(
            response.output_text
        )
    )

    answers = data.get(
        "wrong_answers",
        [],
    )

    if not isinstance(
        answers,
        list,
    ):
        raise RuntimeError(
            "AI did not return a list "
            "of wrong answers."
        )

    return [
        str(answer).strip()
        for answer in answers
        if str(answer).strip()
    ]


# ============================================================
# LOCAL DISTRACTOR VALIDATION
# ============================================================


def local_validate_distractors(
    correct_answer: str,
    wrong_answers: list[str],
) -> list[str]:

    issues = []

    if len(wrong_answers) != 5:

        issues.append(
            f"Expected 5 distractors; "
            f"received {len(wrong_answers)}."
        )

    normalized = [
        normalize_answer(answer)
        for answer in wrong_answers
    ]

    if len(set(normalized)) != len(normalized):

        issues.append(
            "Duplicate distractors detected."
        )

    for answer in wrong_answers:

        if answers_too_similar(
            correct_answer,
            answer,
        ):

            issues.append(
                f'Distractor too similar to '
                f'correct answer: "{answer}"'
            )

    for index_a, answer_a in enumerate(
        wrong_answers
    ):

        for index_b, answer_b in enumerate(
            wrong_answers
        ):

            if index_b <= index_a:
                continue

            if answers_too_similar(
                answer_a,
                answer_b,
            ):

                issues.append(
                    "Distractors may be duplicates "
                    f"or near-duplicates: "
                    f'"{answer_a}" / "{answer_b}"'
                )

    return issues


# ============================================================
# AI DISTRACTOR VALIDATOR
# ============================================================


def judge_answer_set(
    item: dict,
    wrong_answers: list[str],
) -> dict:

    answers_text = "\n".join(
        f"- {answer}"
        for answer in wrong_answers
    )

    prompt = f"""
You are the final multiple-choice safety judge
for Elite Trivia.

QUESTION:
{item["question"]}

INTENDED CORRECT ANSWER:
{item["correct_answer"]}

PROPOSED WRONG ANSWERS:
{answers_text}

Determine whether this answer set is safe to publish.

PASS only if ALL are true:

1. The intended correct answer is clearly correct.
2. Every proposed distractor is clearly wrong.
3. Exactly ONE answer is defensibly correct.
4. No distractor is a synonym, alias,
   alternate spelling, equivalent form,
   translation, broader/narrower equivalent,
   or substantially overlapping version
   of the correct answer.
5. No knowledgeable player could reasonably
   dispute the intended answer.
6. The distractors are plausible and belong
   to the same logical answer type.
7. There are exactly five distinct distractors.

Be strict.

If there is reasonable ambiguity, FAIL.

Do not repair the answer set.
Judge exactly what was supplied.

Return ONLY valid JSON:

{{
  "pass": true,
  "issues": []
}}

or:

{{
  "pass": false,
  "issues": [
    "Specific reason"
  ]
}}
"""

    response = client.responses.create(
        model=MODEL,
        input=prompt,
        reasoning={
            "effort": "low",
        },
    )

    return json.loads(
        clean_json_text(
            response.output_text
        )
    )


# ============================================================
# PREPARE DISTRACTORS WITH HARD RETRY CAP
# ============================================================


def prepare_distractors(
    item: dict,
) -> list[str] | None:

    previous_issues = []

    for attempt in range(
        1,
        MAX_DISTRACTOR_ATTEMPTS + 1,
    ):

        print()
        print(
            f"[DISTRACTORS] "
            f"Attempt {attempt} of "
            f"{MAX_DISTRACTOR_ATTEMPTS}"
        )

        wrong_answers = generate_distractors(
            item,
            previous_issues,
        )

        print()
        print(
            "GENERATED WRONG ANSWERS"
        )
        print(
            "-----------------------"
        )

        for number, answer in enumerate(
            wrong_answers,
            start=1,
        ):

            print(
                f"{number}. {answer}"
            )

        # ----------------------------------------------------
        # LOCAL CHECK
        # ----------------------------------------------------

        local_issues = (
            local_validate_distractors(
                item["correct_answer"],
                wrong_answers,
            )
        )

        print()
        print(
            "LOCAL DISTRACTOR VALIDATION"
        )
        print(
            "---------------------------"
        )

        if local_issues:

            print(
                "FAILED"
            )

            for issue in local_issues:

                print(
                    f"- {issue}"
                )

            previous_issues = local_issues

            continue

        print(
            "PASSED"
        )

        # ----------------------------------------------------
        # AI CHECK
        # ----------------------------------------------------

        print(
            "[AI VALIDATOR] "
            "Checking distractor safety..."
        )

        judge = judge_answer_set(
            item,
            wrong_answers,
        )

        print()
        print(
            "AI DISTRACTOR VALIDATION"
        )
        print(
            "------------------------"
        )

        passed = bool(
            judge.get(
                "pass",
                False,
            )
        )

        issues = judge.get(
            "issues",
            [],
        )

        if passed:

            print(
                "PASSED"
            )

            print()
            print(
                "Exactly one defensible "
                "correct answer detected."
            )

            return wrong_answers

        print(
            "FAILED"
        )

        if issues:

            for issue in issues:

                print(
                    f"- {issue}"
                )

            previous_issues = issues

        else:

            previous_issues = [
                "AI validator rejected the answer set."
            ]

    # --------------------------------------------------------
    # HARD STOP
    # --------------------------------------------------------

    print()
    print(
        "======================================================"
    )
    print(
        "DISTRACTOR ATTEMPT LIMIT REACHED"
    )
    print(
        "Question requires manual review."
    )
    print(
        "No additional AI attempts will be made."
    )
    print(
        "======================================================"
    )

    return None


# ============================================================
# ROULETTE HINT GENERATION
#
# IMPORTANT:
# The generator intentionally DOES NOT see the answer choices.
#
# That prevents it from designing a hint specifically to
# eliminate the displayed choices.
# ============================================================


def generate_roulette_hint(
    item: dict,
    previous_issues: list[str] | None = None,
) -> str:

    retry_feedback = format_feedback(
        previous_issues
    )

    prompt = f"""
You are writing an Elite Roulette hint
for a bar trivia game.

QUESTION:
{item["question"]}

CORRECT ANSWER:
{item["correct_answer"]}

CATEGORY:
{item["category"]}

Write ONE short useful hint.

PURPOSE:

The hint should point the player in the right
direction without giving away the answer.

The player should still need to know the trivia
or reason out the answer.

GOOD HINTS may provide:

- broad context
- an era or time period
- a useful association
- a related fact
- a broad geographic clue
- a broad genre or subject clue
- a relationship that helps memory

DO NOT:

- include the correct answer
- include a revealing portion of the answer
- use an obvious synonym or alias
- summarize the exact plot in a way that identifies
  the answer
- describe the answer so specifically that the player
  barely needs trivia knowledge
- effectively restate the question
- give away the answer through wordplay
- tell the player which option to choose

The hint should normally be ONE short sentence.

Think:
"Useful clue — not giveaway."

{retry_feedback}

Return ONLY valid JSON:

{{
  "hint": "Hint text"
}}
"""

    response = client.responses.create(
        model=MODEL,
        input=prompt,
        reasoning={
            "effort": "low",
        },
    )

    data = json.loads(
        clean_json_text(
            response.output_text
        )
    )

    return str(
        data.get(
            "hint",
            "",
        )
    ).strip()


# ============================================================
# LOCAL HINT VALIDATION
# ============================================================


HINT_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "what",
    "when",
    "where",
    "which",
    "who",
    "into",
    "your",
    "their",
    "have",
    "has",
    "was",
    "were",
    "are",
    "you",
    "its",
}


def local_validate_hint(
    correct_answer: str,
    hint: str,
) -> list[str]:

    issues = []

    if not hint:

        issues.append(
            "Hint is blank."
        )

        return issues

    normalized_hint = normalize_answer(
        hint
    )

    normalized_answer = normalize_answer(
        correct_answer
    )

    # Entire answer appears in hint.
    if (
        normalized_answer
        and normalized_answer
        in normalized_hint
    ):

        issues.append(
            "Hint contains the correct answer."
        )

    # Detect meaningful answer words leaking.
    answer_words = [
        word
        for word in normalized_answer.split()
        if (
            len(word) >= 4
            and word not in HINT_STOP_WORDS
        )
    ]

    hint_words = set(
        normalized_hint.split()
    )

    leaked_words = [
        word
        for word in answer_words
        if word in hint_words
    ]

    if leaked_words:

        issues.append(
            "Hint contains distinctive answer "
            "word(s): "
            + ", ".join(leaked_words)
        )

    word_count = len(
        hint.split()
    )

    if word_count > 30:

        issues.append(
            f"Hint is too long "
            f"({word_count} words)."
        )

    return issues


# ============================================================
# AI HINT VALIDATOR
#
# The validator DOES see the displayed answers.
# ============================================================


def judge_roulette_hint(
    item: dict,
    wrong_answers: list[str],
    hint: str,
) -> dict:

    choices_text = "\n".join(
        [
            f"- {item['correct_answer']}",
            *[
                f"- {answer}"
                for answer in wrong_answers
            ],
        ]
    )

    prompt = f"""
You are the final hint judge for Elite Roulette.

QUESTION:
{item["question"]}

CORRECT ANSWER:
{item["correct_answer"]}

DISPLAYED ANSWERS:
{choices_text}

PROPOSED HINT:
{hint}

Judge whether this hint is appropriate.

PASS only if ALL are true:

1. The hint is factually accurate.
2. It meaningfully points the player in the
   right direction.
3. It does NOT reveal the correct answer.
4. It does NOT contain a revealing synonym,
   alias, distinctive answer word, or equivalent.
5. It does NOT make the correct displayed choice
   immediately obvious.
6. It does NOT eliminate so many displayed answers
   that the player barely needs trivia knowledge.
7. It is concise and useful.

The goal is:

USEFUL CLUE — NOT GIVEAWAY.

Be strict.

Return ONLY valid JSON:

{{
  "pass": true,
  "issues": []
}}

or:

{{
  "pass": false,
  "issues": [
    "Specific reason"
  ]
}}
"""

    response = client.responses.create(
        model=MODEL,
        input=prompt,
        reasoning={
            "effort": "low",
        },
    )

    return json.loads(
        clean_json_text(
            response.output_text
        )
    )


# ============================================================
# PREPARE ROULETTE HINT WITH HARD RETRY CAP
# ============================================================


def prepare_roulette_hint(
    item: dict,
    wrong_answers: list[str],
) -> tuple[str | None, list[str]]:

    previous_issues = []

    for attempt in range(
        1,
        MAX_HINT_ATTEMPTS + 1,
    ):

        print()
        print(
            f"[ROULETTE HINT] "
            f"Attempt {attempt} of "
            f"{MAX_HINT_ATTEMPTS}"
        )

        hint = generate_roulette_hint(
            item,
            previous_issues,
        )

        print()
        print(
            "GENERATED ROULETTE HINT"
        )
        print(
            "-----------------------"
        )
        print(
            hint
        )

        # ----------------------------------------------------
        # LOCAL CHECK
        # ----------------------------------------------------

        local_issues = (
            local_validate_hint(
                item["correct_answer"],
                hint,
            )
        )

        print()
        print(
            "LOCAL HINT VALIDATION"
        )
        print(
            "---------------------"
        )

        if local_issues:

            print(
                "FAILED"
            )

            for issue in local_issues:

                print(
                    f"- {issue}"
                )

            previous_issues = local_issues

            continue

        print(
            "PASSED"
        )

        # ----------------------------------------------------
        # AI CHECK
        # ----------------------------------------------------

        print(
            "[AI HINT VALIDATOR] "
            "Checking usefulness / answer leakage..."
        )

        judge = judge_roulette_hint(
            item,
            wrong_answers,
            hint,
        )

        print()
        print(
            "AI HINT VALIDATION"
        )
        print(
            "------------------"
        )

        passed = bool(
            judge.get(
                "pass",
                False,
            )
        )

        issues = judge.get(
            "issues",
            [],
        )

        if passed:

            print(
                "PASSED"
            )

            return hint, []

        print(
            "FAILED"
        )

        if issues:

            for issue in issues:

                print(
                    f"- {issue}"
                )

            previous_issues = issues

        else:

            previous_issues = [
                "AI validator rejected the hint."
            ]

    # --------------------------------------------------------
    # HARD STOP
    # --------------------------------------------------------

    print()
    print(
        "======================================================"
    )
    print(
        "ROULETTE HINT ATTEMPT LIMIT REACHED"
    )
    print(
        "No additional AI attempts will be made."
    )
    print(
        "Question will require a manual hint or "
        "will not be used automatically for Roulette."
    )
    print(
        "======================================================"
    )

    return None, previous_issues


# ============================================================
# DATABASE SAVE FUNCTIONS
# ============================================================


def save_validated_distractors(
    question_id: int,
    wrong_answers: list[str],
) -> None:

    conn = connect()

    try:

        conn.execute(
            """
            UPDATE questions

            SET
                wrong_answers_json = ?,
                network_status = 'NEEDS_REVIEW',
                updated_at = datetime('now')

            WHERE id = ?
            """,
            (
                json.dumps(
                    wrong_answers,
                    ensure_ascii=False,
                ),
                question_id,
            ),
        )

        conn.commit()

    finally:

        conn.close()


def save_validated_roulette_hint(
    question_id: int,
    roulette_hint: str,
) -> None:

    conn = connect()

    try:

        conn.execute(
            """
            UPDATE questions

            SET
                roulette_hint = ?,

                roulette_hint_status =
                    'NEEDS_REVIEW',

                roulette_suitable = 1,

                network_status =
                    'NEEDS_REVIEW',

                updated_at =
                    datetime('now')

            WHERE id = ?
            """,
            (
                roulette_hint,
                question_id,
            ),
        )

        conn.commit()

    finally:

        conn.close()


def mark_manual_hint_required(
    question_id: int,
) -> None:

    conn = connect()

    try:

        conn.execute(
            """
            UPDATE questions

            SET
                roulette_hint = '',

                roulette_hint_status =
                    'NEEDS_MANUAL_HINT',

                roulette_suitable = 0,

                network_status =
                    'NEEDS_REVIEW',

                updated_at =
                    datetime('now')

            WHERE id = ?
            """,
            (
                question_id,
            ),
        )

        conn.commit()

    finally:

        conn.close()


# ============================================================
# MAIN
# ============================================================


def main() -> None:

    item = load_test_question()

    print()
    print(
        "======================================================"
    )
    print(
        " ELITE NETWORK — COST-GUARDED QUESTION PREP"
    )
    print(
        "======================================================"
    )

    print(
        f"Game Slot:     "
        f"{item['slot_id']}"
    )

    print(
        f"Question Type: "
        f"{item['question_type']}"
    )

    print(
        f"Question ID:   "
        f"{item['question_id']}"
    )

    print(
        f"Category:      "
        f"{item['category']}"
    )

    print(
        f"Fact Checked:  "
        f"{item['fact_check_date']}"
    )

    print()
    print(
        "QUESTION:"
    )
    print(
        item["question"]
    )

    print()
    print(
        "CORRECT ANSWER:"
    )
    print(
        item["correct_answer"]
    )

    print()
    print(
        "AI COST GUARD"
    )
    print(
        "-------------"
    )

    print(
        f"Max distractor attempts: "
        f"{MAX_DISTRACTOR_ATTEMPTS}"
    )

    print(
        f"Max hint attempts:       "
        f"{MAX_HINT_ATTEMPTS}"
    )

    print(
        "Unlimited retries:       OFF"
    )

    # ========================================================
    # PREPARE DISTRACTORS
    # ========================================================

    wrong_answers = prepare_distractors(
        item
    )

    if wrong_answers is None:

        print()
        print(
            "Question prep stopped."
        )

        print(
            "Distractors require manual review."
        )

        return

    # Save good distractors immediately.
    save_validated_distractors(
        item["question_id"],
        wrong_answers,
    )

    print()
    print(
        "Validated distractors SAVED."
    )

    # ========================================================
    # IF NOT ROULETTE, STOP HERE
    # ========================================================

    if item["question_type"] != "roulette":

        print()
        print(
            "Question is not a Roulette slot."
        )

        print(
            "No Roulette hint required."
        )

        return

    # ========================================================
    # PREPARE ROULETTE HINT
    # ========================================================

    roulette_hint, hint_issues = (
        prepare_roulette_hint(
            item,
            wrong_answers,
        )
    )

    if roulette_hint is None:

        mark_manual_hint_required(
            item["question_id"]
        )

        print()
        print(
            "GOOD DISTRACTORS WERE KEPT."
        )

        print(
            "Roulette hint status: "
            "NEEDS_MANUAL_HINT"
        )

        print(
            "Automatic Roulette suitability: OFF"
        )

        return

    # ========================================================
    # SAVE GOOD HINT
    # ========================================================

    save_validated_roulette_hint(
        item["question_id"],
        roulette_hint,
    )

    print()
    print(
        "======================================================"
    )

    print(
        "QUESTION PREP COMPLETE"
    )

    print(
        "Validated distractors: SAVED"
    )

    print(
        "Validated Roulette hint: SAVED"
    )

    print(
        "Question status: NEEDS_REVIEW"
    )

    print(
        "Hint status:     NEEDS_REVIEW"
    )

    print(
        "======================================================"
    )

    print()


if __name__ == "__main__":
    main()