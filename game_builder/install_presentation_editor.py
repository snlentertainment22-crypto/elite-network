from pathlib import Path
import shutil


# ============================================================
# ELITE NETWORK GAME BUILDER
# PRESENTATION EDITOR INSTALLER
# Build 1A
#
# Adds editable TV presentation controls to the existing
# Game Builder page.
#
# Creates a backup first.
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
    / "game_builder.before_presentation_editor.html"
)


# ============================================================
# CSS TO INSERT
# ============================================================


CSS_BLOCK = r"""

/* ==========================================================
   PRESENTATION EDITOR
   ========================================================== */


#presentationEditor {

    margin-top:
        12px;

    padding:
        14px;

    border:
        1px solid
        #283648;

    border-radius:
        9px;

    background:
        #0b1119;
}


.presentationHeader {

    display:
        flex;

    align-items:
        center;

    justify-content:
        space-between;

    gap:
        12px;

    margin-bottom:
        12px;
}


.presentationTitle {

    color:
        #7eeaff;

    font-size:
        12px;

    font-weight:
        1000;

    letter-spacing:
        .07em;

    text-transform:
        uppercase;
}


.presentationGrid {

    display:
        grid;

    grid-template-columns:
        1fr
        180px
        180px;

    gap:
        10px;

    align-items:
        end;
}


.editorField {

    min-width:
        0;
}


.editorLabel {

    display:
        block;

    margin-bottom:
        5px;

    color:
        #aab7c8;

    font-size:
        10px;

    font-weight:
        1000;

    text-transform:
        uppercase;

    letter-spacing:
        .05em;
}


.editorInput {

    width:
        100%;

    min-width:
        0;

    padding:
        9px
        10px;

    border:
        1px solid
        #34445a;

    border-radius:
        6px;

    outline:
        none;

    background:
        #111925;

    color:
        white;

    font-size:
        13px;

    font-weight:
        800;
}


.editorInput:focus {

    border-color:
        #63dfff;

    box-shadow:
        0 0 0 1px
        rgba(
            99,
            223,
            255,
            .28
        );
}


.backgroundButtons {

    display:
        flex;

    flex-wrap:
        wrap;

    gap:
        7px;

    margin-top:
        9px;
}


.smallEditorButton {

    padding:
        7px
        9px;

    border:
        1px solid
        #34445a;

    border-radius:
        6px;

    background:
        #141d29;

    color:
        #dce6f2;

    font-size:
        10px;

    font-weight:
        900;

    cursor:
        pointer;
}


.smallEditorButton:hover {

    border-color:
        #63dfff;

    color:
        #7eeaff;
}


#savePresentationButton {

    padding:
        9px
        13px;

    border:
        1px solid
        #38b9dc;

    border-radius:
        7px;

    background:
        #123444;

    color:
        #7eeaff;

    font-size:
        11px;

    font-weight:
        1000;

    cursor:
        pointer;
}


#savePresentationButton:hover {

    background:
        #174659;
}


#savePresentationButton:disabled {

    opacity:
        .5;

    cursor:
        default;
}


#presentationSaveStatus {

    margin-top:
        10px;

    min-height:
        16px;

    font-size:
        11px;

    font-weight:
        900;

    color:
        #9daabd;
}


#presentationSaveStatus.dirty {

    color:
        #ffd46a;
}


#presentationSaveStatus.saving {

    color:
        #7eeaff;
}


#presentationSaveStatus.saved {

    color:
        #70efa9;
}


#presentationSaveStatus.error {

    color:
        #ff8d8d;
}


@media (
    max-width:
    1250px
) {

    .presentationGrid {

        grid-template-columns:
            1fr
            150px
            150px;
    }
}

"""


# ============================================================
# HTML TO INSERT
# ============================================================


HTML_BLOCK = r"""

                <div id="presentationEditor">

                    <div class="presentationHeader">

                        <div class="presentationTitle">
                            TV PRESENTATION
                        </div>

                        <button
                            id="savePresentationButton"
                            type="button"
                        >
                            SAVE PRESENTATION
                        </button>

                    </div>


                    <div class="presentationGrid">

                        <div class="editorField">

                            <label
                                class="editorLabel"
                                for="backgroundPath"
                            >
                                Background Image
                            </label>

                            <input
                                id="backgroundPath"
                                class="editorInput"
                                type="text"
                                placeholder="Default background"
                                autocomplete="off"
                            >

                        </div>


                        <div class="editorField">

                            <label
                                class="editorLabel"
                                for="questionFontOverride"
                            >
                                Question Font
                            </label>

                            <input
                                id="questionFontOverride"
                                class="editorInput"
                                type="number"
                                min="18"
                                max="90"
                                step="1"
                                placeholder="AUTO"
                            >

                        </div>


                        <div class="editorField">

                            <label
                                class="editorLabel"
                                for="answerFontOverride"
                            >
                                Answer Font
                            </label>

                            <input
                                id="answerFontOverride"
                                class="editorInput"
                                type="number"
                                min="16"
                                max="72"
                                step="1"
                                placeholder="AUTO"
                            >

                        </div>

                    </div>


                    <div class="backgroundButtons">

                        <button
                            id="useDefaultBackground"
                            class="smallEditorButton"
                            type="button"
                        >
                            USE DEFAULT
                        </button>

                        <button
                            id="useQuestionBackground"
                            class="smallEditorButton"
                            type="button"
                        >
                            QUESTION BG
                        </button>

                        <button
                            id="useRouletteBackground"
                            class="smallEditorButton"
                            type="button"
                        >
                            ROULETTE BG
                        </button>

                        <button
                            id="resetFontsAuto"
                            class="smallEditorButton"
                            type="button"
                        >
                            RESET FONTS TO AUTO
                        </button>

                    </div>


                    <div id="presentationSaveStatus">
                        Select a question to edit presentation.
                    </div>

                </div>

"""


# ============================================================
# JAVASCRIPT TO INSERT
# ============================================================


JS_BLOCK = r"""

// ============================================================
// PRESENTATION EDITOR
// ============================================================


function getPreviewBackground(
    q
) {

    const overrides =
        q?.presentation_overrides
        &&
        typeof q.presentation_overrides
        === "object"
        ?
        q.presentation_overrides
        :
        {};


    const custom =
        String(
            overrides.background_image
            ||
            ""
        ).trim();


    if (
        custom
    ) {

        return custom;
    }


    if (
        previewMode === "hint"
        &&
        q?.question_type === "roulette"
    ) {

        return "/assets/slides/roulette_bg.png";
    }


    return "/assets/slides/question_bg.png";
}


function optionalNumberFromInput(
    id
) {

    const element =
        document.getElementById(
            id
        );


    if (
        !element
    ) {

        return null;
    }


    const raw =
        element.value.trim();


    if (
        raw === ""
    ) {

        return null;
    }


    const number =
        Number(
            raw
        );


    if (
        !Number.isFinite(
            number
        )
    ) {

        return null;
    }


    return Math.round(
        number
    );
}


function setPresentationStatus(
    text,
    className = ""
) {

    const element =
        document.getElementById(
            "presentationSaveStatus"
        );


    if (
        !element
    ) {

        return;
    }


    element.textContent =
        text;


    element.className =
        className;
}


function loadPresentationEditor() {

    if (
        !selectedQuestion
    ) {

        return;
    }


    const q =
        selectedQuestion;


    const overrides =
        q.presentation_overrides
        &&
        typeof q.presentation_overrides
        === "object"
        ?
        q.presentation_overrides
        :
        {};


    document.getElementById(
        "backgroundPath"
    ).value =
        overrides.background_image
        ||
        "";


    document.getElementById(
        "questionFontOverride"
    ).value =
        q.question_font_override
        ??
        "";


    document.getElementById(
        "answerFontOverride"
    ).value =
        q.answer_font_override
        ??
        "";


    setPresentationStatus(
        "AUTO settings are used when a field is blank."
    );
}


function applyPresentationDraft() {

    if (
        !selectedQuestion
    ) {

        return;
    }


    const q =
        selectedQuestion;


    if (
        !q.presentation_overrides
        ||
        typeof q.presentation_overrides
        !== "object"
    ) {

        q.presentation_overrides =
            {};
    }


    const background =
        document.getElementById(
            "backgroundPath"
        ).value.trim();


    if (
        background
    ) {

        q.presentation_overrides.background_image =
            background;
    }

    else {

        delete q.presentation_overrides.background_image;
    }


    q.question_font_override =
        optionalNumberFromInput(
            "questionFontOverride"
        );


    q.answer_font_override =
        optionalNumberFromInput(
            "answerFontOverride"
        );


    renderPreview();


    setPresentationStatus(
        "UNSAVED PRESENTATION CHANGES",
        "dirty"
    );
}


function useBackgroundPreset(
    value
) {

    const input =
        document.getElementById(
            "backgroundPath"
        );


    input.value =
        value;


    applyPresentationDraft();
}


async function savePresentation() {

    if (
        !selectedQuestion
        ||
        !gameData
    ) {

        return;
    }


    const q =
        selectedQuestion;


    applyPresentationDraft();


    const saveButton =
        document.getElementById(
            "savePresentationButton"
        );


    saveButton.disabled =
        true;


    setPresentationStatus(
        "SAVING...",
        "saving"
    );


    const backgroundImage =
        document.getElementById(
            "backgroundPath"
        ).value.trim();


    const payload = {

        game_key:
            gameData.game_key,

        slot_id:
            q.slot_id,

        category:
            q.category,

        question:
            q.question,

        correct_answer:
            q.correct_answer,

        wrong_answers:
            Array.isArray(
                q.wrong_answers
            )
            ?
            q.wrong_answers
            :
            [],

        roulette_hint:
            q.roulette_hint
            ||
            "",

        question_type:
            q.question_type,

        timer_seconds:
            q.timer_seconds,

        wager_seconds:
            q.wager_seconds,

        max_points:
            q.max_points,

        min_points:
            q.min_points,

        background_image:
            backgroundImage,

        question_font_override:
            optionalNumberFromInput(
                "questionFontOverride"
            ),

        answer_font_override:
            optionalNumberFromInput(
                "answerFontOverride"
            )
    };


    try {

        const response =
            await fetch(
                "/api/admin/game-builder/save",
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
                            payload
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
                "Unable to save presentation."
            );
        }


        const result =
            data.result
            ||
            {};


        if (
            !q.presentation_overrides
            ||
            typeof q.presentation_overrides
            !== "object"
        ) {

            q.presentation_overrides =
                {};
        }


        if (
            result.background_image
        ) {

            q.presentation_overrides.background_image =
                result.background_image;
        }

        else {

            delete q.presentation_overrides.background_image;
        }


        q.question_font_override =
            result.question_font_override
            ??
            null;


        q.answer_font_override =
            result.answer_font_override
            ??
            null;


        renderPreview();


        setPresentationStatus(
            "SAVED ✓",
            "saved"
        );

    }

    catch (
        error
    ) {

        setPresentationStatus(
            "SAVE ERROR: "
            +
            error.message,
            "error"
        );

    }

    finally {

        saveButton.disabled =
            false;
    }
}


// ============================================================
// PRESENTATION EDITOR EVENTS
// ============================================================


document.getElementById(
    "backgroundPath"
).addEventListener(
    "input",
    applyPresentationDraft
);


document.getElementById(
    "questionFontOverride"
).addEventListener(
    "input",
    applyPresentationDraft
);


document.getElementById(
    "answerFontOverride"
).addEventListener(
    "input",
    applyPresentationDraft
);


document.getElementById(
    "useDefaultBackground"
).addEventListener(
    "click",
    () => {

        useBackgroundPreset(
            ""
        );
    }
);


document.getElementById(
    "useQuestionBackground"
).addEventListener(
    "click",
    () => {

        useBackgroundPreset(
            "/assets/slides/question_bg.png"
        );
    }
);


document.getElementById(
    "useRouletteBackground"
).addEventListener(
    "click",
    () => {

        useBackgroundPreset(
            "/assets/slides/roulette_bg.png"
        );
    }
);


document.getElementById(
    "resetFontsAuto"
).addEventListener(
    "click",
    () => {

        document.getElementById(
            "questionFontOverride"
        ).value =
            "";


        document.getElementById(
            "answerFontOverride"
        ).value =
            "";


        applyPresentationDraft();
    }
);


document.getElementById(
    "savePresentationButton"
).addEventListener(
    "click",
    savePresentation
);

"""


# ============================================================
# ANCHORS
# ============================================================


STYLE_ANCHOR = """
</style>
"""


HTML_ANCHOR = """                <div id="fitBar"></div>

            </div>


            <div id="details"></div>
"""


HTML_REPLACEMENT = """                <div id="fitBar"></div>

""" + HTML_BLOCK + """

            </div>


            <div id="details"></div>
"""


JS_ANCHOR = """// ============================================================
// DETAILS
// ============================================================
"""


SELECT_ANCHOR = """    renderPreview();

    renderDetails();
}
"""


SELECT_REPLACEMENT = """    renderPreview();

    renderDetails();

    loadPresentationEditor();
}
"""


OLD_ROULETTE_BACKGROUND = """        stage.style.backgroundImage =
            "url('/assets/slides/roulette_bg.png')";
"""


NEW_ROULETTE_BACKGROUND = """        stage.style.backgroundImage =
            `url('${getPreviewBackground(q)}')`;
"""


OLD_QUESTION_BACKGROUND = """        stage.style.backgroundImage =
            "url('/assets/slides/question_bg.png')";
"""


NEW_QUESTION_BACKGROUND = """        stage.style.backgroundImage =
            `url('${getPreviewBackground(q)}')`;
"""


# ============================================================
# INSTALL
# ============================================================


def main():

    if not HTML_FILE.exists():

        raise FileNotFoundError(
            f"Could not find:\n"
            f"{HTML_FILE}"
        )

    text = HTML_FILE.read_text(
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # BACKUP
    # --------------------------------------------------------

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

    if (
        "#presentationEditor"
        not in text
    ):

        if STYLE_ANCHOR not in text:

            raise RuntimeError(
                "Could not find </style> anchor."
            )

        text = text.replace(
            STYLE_ANCHOR,
            CSS_BLOCK
            +
            STYLE_ANCHOR,
            1,
        )

        changed = True

        print(
            "Installed presentation editor CSS."
        )

    else:

        print(
            "Presentation editor CSS "
            "already installed."
        )

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    if (
        'id="savePresentationButton"'
        not in text
    ):

        if HTML_ANCHOR not in text:

            raise RuntimeError(
                "Could not find preview-card "
                "HTML anchor."
            )

        text = text.replace(
            HTML_ANCHOR,
            HTML_REPLACEMENT,
            1,
        )

        changed = True

        print(
            "Installed presentation editor controls."
        )

    else:

        print(
            "Presentation editor controls "
            "already installed."
        )

    # --------------------------------------------------------
    # SELECT QUESTION HOOK
    # --------------------------------------------------------

    if (
        "loadPresentationEditor();"
        not in text
    ):

        if SELECT_ANCHOR not in text:

            raise RuntimeError(
                "Could not find selectQuestion "
                "anchor."
            )

        text = text.replace(
            SELECT_ANCHOR,
            SELECT_REPLACEMENT,
            1,
        )

        changed = True

        print(
            "Installed selected-question "
            "editor loading."
        )

    # --------------------------------------------------------
    # BACKGROUND RENDERING
    # --------------------------------------------------------

    if OLD_ROULETTE_BACKGROUND in text:

        text = text.replace(
            OLD_ROULETTE_BACKGROUND,
            NEW_ROULETTE_BACKGROUND,
            1,
        )

        changed = True

        print(
            "Connected Roulette preview "
            "to background override."
        )

    if OLD_QUESTION_BACKGROUND in text:

        text = text.replace(
            OLD_QUESTION_BACKGROUND,
            NEW_QUESTION_BACKGROUND,
            1,
        )

        changed = True

        print(
            "Connected question preview "
            "to background override."
        )

    # --------------------------------------------------------
    # JAVASCRIPT
    # --------------------------------------------------------

    if (
        "function savePresentation()"
        not in text
    ):

        if JS_ANCHOR not in text:

            raise RuntimeError(
                "Could not find JavaScript "
                "details anchor."
            )

        text = text.replace(
            JS_ANCHOR,
            JS_BLOCK
            +
            "\n\n"
            +
            JS_ANCHOR,
            1,
        )

        changed = True

        print(
            "Installed presentation editor JavaScript."
        )

    else:

        print(
            "Presentation editor JavaScript "
            "already installed."
        )

    # --------------------------------------------------------
    # SAVE FILE
    # --------------------------------------------------------

    if changed:

        HTML_FILE.write_text(
            text,
            encoding="utf-8",
        )

        print()
        print(
            "GAME BUILDER UPDATED SUCCESSFULLY."
        )

    else:

        print()
        print(
            "No changes were needed."
        )

    print()
    print(
        "Presentation editor installed."
    )

    print(
        "Open:"
    )

    print(
        "http://localhost:8080/game-builder"
    )

    print()


if __name__ == "__main__":

    main()