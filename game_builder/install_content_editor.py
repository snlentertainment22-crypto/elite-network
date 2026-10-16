from pathlib import Path
import shutil


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
    / "game_builder.before_content_editor.html"
)


CSS = r"""

/* ==========================================================
   GAME BUILDER EDITOR TABS
   ========================================================== */

.editorTabs {

    display:
        flex;

    gap:
        6px;

    margin-top:
        12px;
}


.editorTab {

    padding:
        8px 13px;

    border:
        1px solid #34445a;

    border-radius:
        7px 7px 0 0;

    background:
        #101721;

    color:
        #9fadc0;

    font-size:
        11px;

    font-weight:
        1000;

    cursor:
        pointer;
}


.editorTab.active {

    color:
        #7eeaff;

    border-color:
        #3a98b1;

    background:
        #112632;
}


.editorPanelHidden {

    display:
        none !important;
}


#contentEditor {

    padding:
        14px;

    border:
        1px solid #283648;

    border-radius:
        0 9px 9px 9px;

    background:
        #0b1119;
}


.contentGrid {

    display:
        grid;

    grid-template-columns:
        1fr 160px 160px;

    gap:
        10px;
}


.contentWide {

    grid-column:
        1 / -1;
}


.contentTwo {

    display:
        grid;

    grid-template-columns:
        1fr 1fr;

    gap:
        10px;
}


.contentTextarea {

    width:
        100%;

    min-height:
        72px;

    resize:
        vertical;

    padding:
        9px 10px;

    border:
        1px solid #34445a;

    border-radius:
        6px;

    background:
        #111925;

    color:
        white;

    font:
        800 13px Arial;

    line-height:
        1.35;
}


.answerEditorGrid {

    display:
        grid;

    grid-template-columns:
        1fr 1fr;

    gap:
        8px 10px;

    margin-top:
        8px;
}


#saveContentButton {

    padding:
        9px 13px;

    border:
        1px solid #42d28b;

    border-radius:
        7px;

    background:
        #123526;

    color:
        #7af0ae;

    font-size:
        11px;

    font-weight:
        1000;

    cursor:
        pointer;
}


#contentSaveStatus {

    margin-top:
        10px;

    min-height:
        16px;

    color:
        #a6b2c2;

    font-size:
        11px;

    font-weight:
        900;
}


#contentSaveStatus.dirty {
    color: #ffd46a;
}


#contentSaveStatus.saved {
    color: #70efa9;
}


#contentSaveStatus.error {
    color: #ff8d8d;
}


@media (max-width: 1200px) {

    .contentGrid {
        grid-template-columns:
            1fr 130px 130px;
    }
}

"""


HTML = r"""

                <div class="editorTabs">

                    <button
                        id="contentTab"
                        class="editorTab active"
                        type="button"
                    >
                        CONTENT
                    </button>

                    <button
                        id="presentationTab"
                        class="editorTab"
                        type="button"
                    >
                        PRESENTATION
                    </button>

                </div>


                <div id="contentEditor">

                    <div class="presentationHeader">

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


                    <div class="contentGrid">

                        <div class="editorField">

                            <label class="editorLabel">
                                Category
                            </label>

                            <input
                                id="editCategory"
                                class="editorInput"
                                type="text"
                            >

                        </div>


                        <div class="editorField">

                            <label class="editorLabel">
                                Type
                            </label>

                            <select
                                id="editQuestionType"
                                class="editorInput"
                            >
                                <option value="normal">
                                    Normal
                                </option>

                                <option value="roulette">
                                    Roulette
                                </option>

                                <option value="final_wager">
                                    Final Wager
                                </option>
                            </select>

                        </div>


                        <div class="editorField">

                            <label class="editorLabel">
                                Timer
                            </label>

                            <input
                                id="editTimer"
                                class="editorInput"
                                type="number"
                                min="1"
                                max="600"
                            >

                        </div>


                        <div class="contentWide">

                            <label class="editorLabel">
                                Question
                            </label>

                            <textarea
                                id="editQuestion"
                                class="contentTextarea"
                            ></textarea>

                        </div>


                        <div class="contentTwo contentWide">

                            <div>

                                <label class="editorLabel">
                                    Correct Answer
                                </label>

                                <input
                                    id="editCorrectAnswer"
                                    class="editorInput"
                                    type="text"
                                >

                            </div>


                            <div id="rouletteHintField">

                                <label class="editorLabel">
                                    Roulette Hint
                                </label>

                                <input
                                    id="editRouletteHint"
                                    class="editorInput"
                                    type="text"
                                >

                            </div>

                        </div>


                        <div class="contentWide">

                            <label class="editorLabel">
                                Wrong Answers
                            </label>

                            <div class="answerEditorGrid">

                                <input
                                    id="wrongAnswer1"
                                    class="editorInput"
                                    placeholder="Wrong answer 1"
                                >

                                <input
                                    id="wrongAnswer2"
                                    class="editorInput"
                                    placeholder="Wrong answer 2"
                                >

                                <input
                                    id="wrongAnswer3"
                                    class="editorInput"
                                    placeholder="Wrong answer 3"
                                >

                                <input
                                    id="wrongAnswer4"
                                    class="editorInput"
                                    placeholder="Wrong answer 4"
                                >

                                <input
                                    id="wrongAnswer5"
                                    class="editorInput"
                                    placeholder="Wrong answer 5"
                                >

                            </div>

                        </div>

                    </div>


                    <div id="contentSaveStatus">
                        Game-specific edits. Master question is unchanged.
                    </div>

                </div>

"""


JS = r"""

// ============================================================
// CONTENT EDITOR
// ============================================================


let activeEditorTab =
    "content";


function setEditorTab(
    tab
) {

    activeEditorTab =
        tab;


    document.getElementById(
        "contentTab"
    ).classList.toggle(
        "active",
        tab === "content"
    );


    document.getElementById(
        "presentationTab"
    ).classList.toggle(
        "active",
        tab === "presentation"
    );


    document.getElementById(
        "contentEditor"
    ).classList.toggle(
        "editorPanelHidden",
        tab !== "content"
    );


    document.getElementById(
        "presentationEditor"
    ).classList.toggle(
        "editorPanelHidden",
        tab !== "presentation"
    );
}


function setContentStatus(
    text,
    className = ""
) {

    const el =
        document.getElementById(
            "contentSaveStatus"
        );


    el.textContent =
        text;

    el.className =
        className;
}


function loadContentEditor() {

    if (
        !selectedQuestion
    ) {
        return;
    }


    const q =
        selectedQuestion;


    document.getElementById(
        "editCategory"
    ).value =
        q.category || "";


    document.getElementById(
        "editQuestion"
    ).value =
        q.question || "";


    document.getElementById(
        "editCorrectAnswer"
    ).value =
        q.correct_answer || "";


    document.getElementById(
        "editQuestionType"
    ).value =
        q.question_type || "normal";


    document.getElementById(
        "editTimer"
    ).value =
        q.timer_seconds ?? "";


    document.getElementById(
        "editRouletteHint"
    ).value =
        q.roulette_hint || "";


    const wrong =
        Array.isArray(
            q.wrong_answers
        )
        ?
        q.wrong_answers
        :
        [];


    for (
        let i = 1;
        i <= 5;
        i += 1
    ) {

        document.getElementById(
            "wrongAnswer" + i
        ).value =
            wrong[i - 1]
            ||
            "";
    }


    updateContentVisibility();


    setContentStatus(
        "Game-specific edits. Master question is unchanged."
    );
}


function collectWrongAnswers() {

    const answers =
        [];


    for (
        let i = 1;
        i <= 5;
        i += 1
    ) {

        const value =
            document.getElementById(
                "wrongAnswer" + i
            ).value.trim();


        if (
            value
        ) {
            answers.push(
                value
            );
        }
    }


    return answers;
}


function updateContentVisibility() {

    const type =
        document.getElementById(
            "editQuestionType"
        ).value;


    document.getElementById(
        "rouletteHintField"
    ).style.display =
        type === "roulette"
        ?
        ""
        :
        "none";
}


function applyContentDraft() {

    if (
        !selectedQuestion
    ) {
        return;
    }


    const q =
        selectedQuestion;


    q.category =
        document.getElementById(
            "editCategory"
        ).value.trim();


    q.question =
        document.getElementById(
            "editQuestion"
        ).value.trim();


    q.correct_answer =
        document.getElementById(
            "editCorrectAnswer"
        ).value.trim();


    q.question_type =
        document.getElementById(
            "editQuestionType"
        ).value;


    const timerRaw =
        document.getElementById(
            "editTimer"
        ).value.trim();


    q.timer_seconds =
        timerRaw === ""
        ?
        null
        :
        Number(timerRaw);


    q.wrong_answers =
        collectWrongAnswers();


    q.roulette_hint =
        document.getElementById(
            "editRouletteHint"
        ).value.trim();


    updateContentVisibility();

    renderPreview();

    renderDetails();


    setContentStatus(
        "UNSAVED GAME-SPECIFIC CHANGES",
        "dirty"
    );
}


async function saveContent() {

    if (
        !selectedQuestion
        ||
        !gameData
    ) {
        return;
    }


    applyContentDraft();


    const q =
        selectedQuestion;


    const button =
        document.getElementById(
            "saveContentButton"
        );


    button.disabled =
        true;


    setContentStatus(
        "SAVING..."
    );


    const payload = {

        save_scope:
            "content",

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
            q.wrong_answers,

        roulette_hint:
            q.roulette_hint,

        question_type:
            q.question_type,

        timer_seconds:
            q.timer_seconds,

        wager_seconds:
            q.wager_seconds,

        max_points:
            q.max_points,

        min_points:
            q.min_points
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
                "Unable to save question."
            );
        }


        setContentStatus(
            "SAVED TO THIS GAME ✓",
            "saved"
        );


        renderPreview();

        renderDetails();

    }

    catch (
        error
    ) {

        setContentStatus(
            "SAVE ERROR: "
            +
            error.message,
            "error"
        );

    }

    finally {

        button.disabled =
            false;
    }
}


document.getElementById(
    "contentTab"
).addEventListener(
    "click",
    () => {
        setEditorTab(
            "content"
        );
    }
);


document.getElementById(
    "presentationTab"
).addEventListener(
    "click",
    () => {
        setEditorTab(
            "presentation"
        );
    }
);


document.getElementById(
    "saveContentButton"
).addEventListener(
    "click",
    saveContent
);


[
    "editCategory",
    "editQuestion",
    "editCorrectAnswer",
    "editQuestionType",
    "editTimer",
    "editRouletteHint",
    "wrongAnswer1",
    "wrongAnswer2",
    "wrongAnswer3",
    "wrongAnswer4",
    "wrongAnswer5"
].forEach(
    id => {

        document.getElementById(
            id
        ).addEventListener(
            "input",
            applyContentDraft
        );
    }
);


document.getElementById(
    "editQuestionType"
).addEventListener(
    "change",
    applyContentDraft
);


setEditorTab(
    "content"
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

    if ".editorTabs" not in text:

        text = text.replace(
            "</style>",
            CSS
            +
            "\n</style>",
            1,
        )

        changed = True

        print(
            "Installed content editor CSS."
        )

    # --------------------------------------------------------
    # HTML
    #
    # Insert tabs/content immediately before presentation panel.
    # --------------------------------------------------------

    if 'id="contentEditor"' not in text:

        anchor = (
            '<div id="presentationEditor">'
        )

        if anchor not in text:
            raise RuntimeError(
                "Could not find "
                "presentation editor."
            )

        text = text.replace(
            anchor,
            HTML
            +
            "\n"
            +
            anchor,
            1,
        )

        changed = True

        print(
            "Installed compact editor tabs "
            "and content editor."
        )

    # --------------------------------------------------------
    # LOAD SELECTED QUESTION
    # --------------------------------------------------------

    if (
        "loadContentEditor();"
        not in text
    ):

        anchor = (
            "loadPresentationEditor();"
        )

        if anchor not in text:
            raise RuntimeError(
                "Could not find "
                "presentation loader."
            )

        text = text.replace(
            anchor,
            anchor
            +
            "\n\n    loadContentEditor();",
            1,
        )

        changed = True

        print(
            "Connected content editor "
            "to selected question."
        )

    # --------------------------------------------------------
    # JAVASCRIPT
    # --------------------------------------------------------

    if (
        "function saveContent()"
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
            "Installed content editor "
            "JavaScript."
        )

    # --------------------------------------------------------
    # MAKE PRESENTATION PANEL HIDDEN INITIALLY
    # --------------------------------------------------------

    old = (
        '<div id="presentationEditor">'
    )

    new = (
        '<div id="presentationEditor" '
        'class="editorPanelHidden">'
    )

    if old in text:

        text = text.replace(
            old,
            new,
            1,
        )

        changed = True

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
            "CONTENT EDITOR INSTALLED SUCCESSFULLY."
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