from pathlib import Path
import shutil


# ============================================================
# ELITE NETWORK GAME BUILDER
# REVIEW CONTROL INSTALLER
# Build 1A
#
# Adds compact game-specific approval controls.
# ============================================================


ROOT_DIR = Path(
    __file__
).resolve().parent.parent

HTML_FILE = (
    ROOT_DIR
    / "web"
    / "game_builder.html"
)

BACKUP_FILE = (
    ROOT_DIR
    / "web"
    / "game_builder.before_review_controls.html"
)


CSS = r"""

/* ==========================================================
   GAME REVIEW / APPROVAL
   ========================================================== */


.reviewActions {

    display:
        flex;

    align-items:
        center;

    gap:
        8px;
}


#gameReviewStatus {

    padding:
        7px
        9px;

    border:
        1px solid
        #725d24;

    border-radius:
        6px;

    background:
        #2c2513;

    color:
        #ffd568;

    font-size:
        10px;

    font-weight:
        1000;

    white-space:
        nowrap;
}


#gameReviewStatus.approved {

    border-color:
        #2d7652;

    background:
        #142b21;

    color:
        #70efa9;
}


#approveGameQuestionButton {

    padding:
        9px
        12px;

    border:
        1px solid
        #42d28b;

    border-radius:
        7px;

    background:
        #123526;

    color:
        #7af0ae;

    font-size:
        10px;

    font-weight:
        1000;

    cursor:
        pointer;
}


#approveGameQuestionButton:hover {

    background:
        #184a34;
}


#approveGameQuestionButton:disabled {

    opacity:
        .45;

    cursor:
        default;
}

"""


OLD_HEADER = r"""                    <div class="presentationHeader">

                        <div class="presentationTitle">
                            QUESTION CONTENT
                        </div>

                        <button
                            id="saveContentButton"
                            type="button"
                        >
                            SAVE QUESTION
                        </button>

                    </div>
"""


NEW_HEADER = r"""                    <div class="presentationHeader">

                        <div class="presentationTitle">
                            QUESTION CONTENT
                        </div>


                        <div class="reviewActions">

                            <div id="gameReviewStatus">
                                NEEDS REVIEW
                            </div>

                            <button
                                id="approveGameQuestionButton"
                                type="button"
                            >
                                APPROVE FOR THIS GAME
                            </button>

                            <button
                                id="saveContentButton"
                                type="button"
                            >
                                SAVE QUESTION
                            </button>

                        </div>

                    </div>
"""


JS = r"""

// ============================================================
// GAME REVIEW / APPROVAL
// ============================================================


let contentDirty =
    false;


function renderGameReviewStatus() {

    if (
        !selectedQuestion
    ) {
        return;
    }


    const status =
        selectedQuestion.game_review_status
        ||
        "NEEDS_REVIEW";


    const statusElement =
        document.getElementById(
            "gameReviewStatus"
        );


    const button =
        document.getElementById(
            "approveGameQuestionButton"
        );


    const approved =
        status ===
        "APPROVED";


    statusElement.textContent =
        approved
        ?
        "✓ APPROVED"
        :
        "NEEDS REVIEW";


    statusElement.classList.toggle(
        "approved",
        approved
    );


    if (
        approved
    ) {

        button.textContent =
            "APPROVED";

        button.disabled =
            true;

    }

    else {

        button.textContent =
            "APPROVE FOR THIS GAME";

        button.disabled =
            false;
    }
}


async function approveCurrentQuestion() {

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

        setContentStatus(
            "SAVE QUESTION BEFORE APPROVING.",
            "error"
        );

        return;
    }


    const button =
        document.getElementById(
            "approveGameQuestionButton"
        );


    button.disabled =
        true;


    setContentStatus(
        "CHECKING QUESTION..."
    );


    try {

        const response =
            await fetch(
                "/api/admin/game-builder/review",
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
                                action:
                                    "approve",

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
                "Unable to approve question."
            );
        }


        const result =
            data.result
            ||
            {};


        if (
            result.approved
        ) {

            selectedQuestion.game_review_status =
                "APPROVED";


            selectedQuestion.game_review_approved_at =
                result.approved_at
                ||
                "";


            renderGameReviewStatus();


            setContentStatus(
                "APPROVED FOR THIS GAME ✓",
                "saved"
            );


            return;
        }


        const issues =
            Array.isArray(
                result.issues
            )
            ?
            result.issues
            :
            [];


        selectedQuestion.game_review_status =
            "NEEDS_REVIEW";


        renderGameReviewStatus();


        setContentStatus(
            issues.length
            ?
            "CANNOT APPROVE: "
            +
            issues.join(
                " • "
            )
            :
            "QUESTION IS NOT READY FOR APPROVAL.",
            "error"
        );

    }

    catch (
        error
    ) {

        setContentStatus(
            "APPROVAL ERROR: "
            +
            error.message,
            "error"
        );


        button.disabled =
            false;
    }
}


document.getElementById(
    "approveGameQuestionButton"
).addEventListener(
    "click",
    approveCurrentQuestion
);

"""


def main():

    if not HTML_FILE.exists():

        raise FileNotFoundError(
            f"Could not find:\n"
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

    if ".reviewActions" not in text:

        text = text.replace(
            "</style>",
            CSS
            +
            "\n</style>",
            1,
        )

        changed = True

        print(
            "Installed review control CSS."
        )

    # --------------------------------------------------------
    # HEADER UI
    # --------------------------------------------------------

    if (
        'id="gameReviewStatus"'
        not in text
    ):

        if OLD_HEADER not in text:

            raise RuntimeError(
                "Could not find "
                "Question Content header."
            )

        text = text.replace(
            OLD_HEADER,
            NEW_HEADER,
            1,
        )

        changed = True

        print(
            "Installed compact approval controls."
        )

    # --------------------------------------------------------
    # JAVASCRIPT
    # --------------------------------------------------------

    if (
        "function approveCurrentQuestion()"
        not in text
    ):

        anchor = """// ============================================================
// DETAILS
// ============================================================
"""

        if anchor not in text:

            raise RuntimeError(
                "Could not find "
                "JavaScript insertion point."
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
            "Installed approval JavaScript."
        )

    # --------------------------------------------------------
    # LOAD STATUS WHEN QUESTION CHANGES
    # --------------------------------------------------------

    if (
        "renderGameReviewStatus();"
        not in text
    ):

        anchor = (
            "loadContentEditor();"
        )

        if anchor not in text:

            raise RuntimeError(
                "Could not find "
                "content editor loader."
            )

        text = text.replace(
            anchor,
            anchor
            +
            "\n\n    "
            "contentDirty = false;"
            "\n\n    "
            "renderGameReviewStatus();",
            1,
        )

        changed = True

        print(
            "Connected review status "
            "to selected question."
        )

    # --------------------------------------------------------
    # MARK CONTENT DIRTY
    # --------------------------------------------------------

    old = """    setContentStatus(
        "UNSAVED GAME-SPECIFIC CHANGES",
        "dirty"
    );
}
"""

    new = """    contentDirty =
        true;

    selectedQuestion.game_review_status =
        "NEEDS_REVIEW";

    renderGameReviewStatus();

    setContentStatus(
        "UNSAVED GAME-SPECIFIC CHANGES",
        "dirty"
    );
}
"""

    if (
        "contentDirty =\n        true;"
        not in text
        and
        old in text
    ):

        text = text.replace(
            old,
            new,
            1,
        )

        changed = True

        print(
            "Connected edits to review invalidation."
        )

    # --------------------------------------------------------
    # AFTER SAVE: CLEAR DIRTY + REQUIRE REVIEW
    # --------------------------------------------------------

    old_save = """        setContentStatus(
            "SAVED TO THIS GAME ✓",
            "saved"
        );


        renderPreview();

        renderDetails();
"""

    new_save = """        contentDirty =
            false;

        selectedQuestion.game_review_status =
            "NEEDS_REVIEW";

        renderGameReviewStatus();

        setContentStatus(
            "SAVED TO THIS GAME ✓ — REVIEW REQUIRED",
            "saved"
        );


        renderPreview();

        renderDetails();
"""

    if (
        "SAVED TO THIS GAME ✓ — REVIEW REQUIRED"
        not in text
        and
        old_save in text
    ):

        text = text.replace(
            old_save,
            new_save,
            1,
        )

        changed = True

        print(
            "Connected save to review reset."
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
            "REVIEW CONTROLS INSTALLED SUCCESSFULLY."
        )

    else:

        print()

        print(
            "No changes were needed."
        )

    print()

    print(
        "Refresh:"
    )

    print(
        "http://localhost:8080/game-builder"
    )

    print()


if __name__ == "__main__":

    main()