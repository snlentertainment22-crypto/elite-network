from pathlib import Path
import shutil


# ============================================================
# ELITE NETWORK GAME BUILDER
# AI PREP BUTTON INSTALLER
# Build 1A
# ============================================================


ROOT_DIR = Path(
    __file__
).resolve().parent.parent

HTML_FILE = (
    ROOT_DIR
    /
    "web"
    /
    "game_builder.html"
)

BACKUP_FILE = (
    ROOT_DIR
    /
    "web"
    /
    "game_builder.before_ai_prep_button.html"
)


CSS = r"""

/* ==========================================================
   AI PREP BUTTON
   ========================================================== */


#aiPrepButton {

    padding:
        9px
        12px;

    border:
        1px solid
        #9d6cff;

    border-radius:
        7px;

    background:
        #25183d;

    color:
        #caaeff;

    font-size:
        10px;

    font-weight:
        1000;

    cursor:
        pointer;
}


#aiPrepButton:hover {

    background:
        #342052;
}


#aiPrepButton:disabled {

    opacity:
        .65;

    cursor:
        default;
}


#aiPrepButton.prepared {

    border-color:
        #2d7652;

    background:
        #142b21;

    color:
        #70efa9;
}


#aiPrepStatus {

    margin-top:
        6px;

    min-height:
        14px;

    color:
        #9ca9ba;

    font-size:
        10px;

    font-weight:
        900;
}


#aiPrepStatus.working {

    color:
        #caaeff;
}


#aiPrepStatus.success {

    color:
        #70efa9;
}


#aiPrepStatus.error {

    color:
        #ff8d8d;
}

"""


JS = r"""

// ============================================================
// AI PREP UI
// ============================================================


function questionNeedsAiPrep(
    q
) {

    if (
        !q
    ) {

        return false;
    }


    if (
        q.question_type ===
        "final_wager"
    ) {

        return false;
    }


    const hasFiveDistractors =
        Array.isArray(
            q.wrong_answers
        )
        &&
        q.wrong_answers.length === 5;


    if (
        !hasFiveDistractors
    ) {

        return true;
    }


    if (
        q.question_type ===
        "roulette"
    ) {

        const hasHint =
            String(
                q.roulette_hint
                ||
                ""
            ).trim() !== "";


        const hintBlocked =
            q.roulette_hint_status ===
            "NEEDS_HINT"
            ||
            q.roulette_hint_status ===
            "NEEDS_MANUAL_HINT";


        if (
            !hasHint
            ||
            hintBlocked
        ) {

            return true;
        }
    }


    return false;
}


function renderAiPrepButton() {

    const button =
        document.getElementById(
            "aiPrepButton"
        );


    const status =
        document.getElementById(
            "aiPrepStatus"
        );


    if (
        !button
        ||
        !status
        ||
        !selectedQuestion
    ) {

        return;
    }


    const q =
        selectedQuestion;


    button.classList.remove(
        "prepared"
    );


    if (
        q.question_type ===
        "final_wager"
    ) {

        button.textContent =
            "AI PREP NOT NEEDED";

        button.disabled =
            true;

        button.classList.add(
            "prepared"
        );


        status.textContent =
            "Final Wager uses a typed answer.";

        status.className =
            "";

        return;
    }


    if (
        !questionNeedsAiPrep(
            q
        )
    ) {

        button.textContent =
            "AI PREPARED ✓";

        button.disabled =
            true;

        button.classList.add(
            "prepared"
        );


        status.textContent =
            "Saved AI prep will be reused. No new call needed.";

        status.className =
            "success";

        return;
    }


    button.textContent =
        "PREPARE WITH AI";

    button.disabled =
        false;


    status.textContent =
        "Hard limit: 2 attempts. Existing prep is reused.";

    status.className =
        "";
}


async function reloadSelectedGameData() {

    const currentSlot =
        selectedQuestion
        ?
        selectedQuestion.slot_id
        :
        null;


    const response =
        await fetch(
            "/api/admin/game-builder"
            +
            "?game_key="
            +
            encodeURIComponent(
                gameData.game_key
            ),
            {
                cache:
                    "no-store"
            }
        );


    const data =
        await response.json();


    if (
        !response.ok
        ||
        !data.ok
    ) {

        throw new Error(
            data.error
            ||
            "Unable to reload game."
        );
    }


    gameData =
        data.game;


    const refreshed =
        gameData.questions.find(
            q =>
                q.slot_id
                ===
                currentSlot
        );


    renderGame();


    if (
        refreshed
    ) {

        selectQuestion(
            refreshed
        );
    }
}


async function prepareSelectedQuestionWithAi() {

    if (
        !selectedQuestion
        ||
        !gameData
    ) {

        return;
    }


    if (
        contentDirty
    ) {

        const status =
            document.getElementById(
                "aiPrepStatus"
            );


        status.textContent =
            "SAVE YOUR GAME-SPECIFIC EDITS FIRST.";

        status.className =
            "error";

        return;
    }


    const button =
        document.getElementById(
            "aiPrepButton"
        );


    const status =
        document.getElementById(
            "aiPrepStatus"
        );


    button.disabled =
        true;


    button.textContent =
        "PREPARING...";


    status.textContent =
        "AI prep running — hard retry limit is active.";

    status.className =
        "working";


    try {

        const response =
            await fetch(
                "/api/admin/game-builder/ai-prep",
                {
                    method:
                        "POST",

                    headers:
                        {
                            "Content-Type":
                                "application/json"
                        },

                    body:
                        JSON.stringify(
                            {
                                game_key:
                                    gameData.game_key,

                                slot_id:
                                    selectedQuestion.slot_id
                            }
                        )
                }
            );


        const data =
            await response.json();


        if (
            !response.ok
            ||
            !data.ok
        ) {

            throw new Error(
                data.error
                ||
                "AI preparation failed."
            );
        }


        const result =
            data.result
            ||
            {};


        if (
            !result.ok
        ) {

            let message =
                result.reason
                ||
                "AI preparation stopped.";


            if (
                result.reason ===
                "GAME_SPECIFIC_CONTENT_EDIT"
            ) {

                message =
                    "AI PREP STOPPED: THIS SLOT HAS "
                    +
                    "GAME-SPECIFIC WORDING. "
                    +
                    "MASTER PREP WAS NOT CHANGED.";
            }


            status.textContent =
                message
                +
                " • API calls: "
                +
                (
                    result.api_calls
                    ??
                    0
                );


            status.className =
                "error";


            renderAiPrepButton();

            return;
        }


        const calls =
            result.api_calls
            ??
            0;


        await reloadSelectedGameData();


        const newStatus =
            document.getElementById(
                "aiPrepStatus"
            );


        newStatus.textContent =
            "AI PREP COMPLETE ✓ • API calls used: "
            +
            calls
            +
            " • Human review still required.";


        newStatus.className =
            "success";


        selectedQuestion.game_review_status =
            "NEEDS_REVIEW";


        renderGameReviewStatus();

    }

    catch (
        error
    ) {

        status.textContent =
            "AI PREP ERROR: "
            +
            error.message;


        status.className =
            "error";


        renderAiPrepButton();
    }
}


document.getElementById(
    "aiPrepButton"
).addEventListener(
    "click",
    prepareSelectedQuestionWithAi
);

"""


def main():

    if not HTML_FILE.exists():

        raise FileNotFoundError(
            f"Could not find:\\n"
            f"{HTML_FILE}"
        )

    text = HTML_FILE.read_text(
        encoding="utf-8"
    )

    if not BACKUP_FILE.exists():

        shutil.copy2(
            HTML_FILE,
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
    # CSS
    # --------------------------------------------------------

    if "#aiPrepButton" not in text:

        text = text.replace(
            "</style>",
            CSS
            +
            "\n</style>",
            1,
        )

        changed = True

        print(
            "Installed AI Prep button CSS."
        )

    # --------------------------------------------------------
    # BUTTON
    #
    # Put it at the start of the existing reviewActions group.
    # --------------------------------------------------------

    if 'id="aiPrepButton"' not in text:

        anchor = """                        <div class="reviewActions">
"""

        replacement = """                        <div class="reviewActions">

                            <button
                                id="aiPrepButton"
                                type="button"
                            >
                                PREPARE WITH AI
                            </button>
"""

        if anchor not in text:

            raise RuntimeError(
                "Could not find reviewActions."
            )

        text = text.replace(
            anchor,
            replacement,
            1,
        )

        changed = True

        print(
            "Installed AI Prep button."
        )

    # --------------------------------------------------------
    # STATUS LINE
    # --------------------------------------------------------

    if 'id="aiPrepStatus"' not in text:

        anchor = """                    <div id="contentSaveStatus">
"""

        replacement = """                    <div id="aiPrepStatus"></div>

                    <div id="contentSaveStatus">
"""

        if anchor not in text:

            raise RuntimeError(
                "Could not find content status."
            )

        text = text.replace(
            anchor,
            replacement,
            1,
        )

        changed = True

        print(
            "Installed AI Prep status."
        )

    # --------------------------------------------------------
    # JS
    # --------------------------------------------------------

    if (
        "function prepareSelectedQuestionWithAi()"
        not in text
    ):

        anchor = """// ============================================================
// DETAILS
// ============================================================
"""

        if anchor not in text:

            raise RuntimeError(
                "Could not find JS insertion point."
            )

        text = text.replace(
            anchor,
            JS
            +
            "\n\n"
            +
            anchor,
            1,
        )

        changed = True

        print(
            "Installed AI Prep JavaScript."
        )

    # --------------------------------------------------------
    # RENDER BUTTON WHEN QUESTION CHANGES
    # --------------------------------------------------------

    hook = """    renderGameReviewStatus();
"""

    replacement = """    renderGameReviewStatus();

    renderAiPrepButton();
"""

    if (
        "renderAiPrepButton();"
        not in text
    ):

        if hook not in text:

            raise RuntimeError(
                "Could not find review-status hook."
            )

        text = text.replace(
            hook,
            replacement,
            1,
        )

        changed = True

        print(
            "Connected AI Prep state "
            "to selected question."
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    if changed:

        HTML_FILE.write_text(
            text,
            encoding="utf-8",
        )

        print()

        print(
            "AI PREP BUTTON INSTALLED SUCCESSFULLY."
        )

    else:

        print()

        print(
            "No changes were needed."
        )

    print()


if __name__ == "__main__":

    main()