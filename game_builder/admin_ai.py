from __future__ import annotations




# ============================================================
# ELITE NETWORK GAME BUILDER
# ADMIN AI PREP BRIDGE
# Build 1A
#
# Gives the browser a safe way to prepare ONE selected slot.
#
# The real cost guards remain inside ai_prepare_service.py.
# ============================================================


def prepare_admin_game_slot(
    payload: dict,
) -> dict:

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "Invalid AI prep payload."
        )

    game_key = str(
        payload.get(
            "game_key",
            "",
        )
    ).strip()

    slot_id = str(
        payload.get(
            "slot_id",
            "",
        )
    ).strip()

    if not game_key:
        raise ValueError(
            "Missing game_key."
        )

    if not slot_id:
        raise ValueError(
            "Missing slot_id."
        )

        from .ai_prepare_service import prepare_game_slot

    result = prepare_game_slot(
        game_key,
        slot_id,
    )

    return result