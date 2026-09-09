"""Slot Provider Bounding Box Presets for Stake / Kick Casino Streams.

Contains tuned initial region-of-interest (ROI) bounding boxes for major slot engines
commonly played on Kick (Pragmatic Play, Hacksaw Gaming, Nolimit City, and Generic Slots).
"""

from typing import Any, Dict, List

SLOT_PRESETS: Dict[str, Dict[str, Any]] = {
    "pragmatic_play": {
        "name": "Pragmatic Play",
        "description": "Gates of Olympus, Sweet Bonanza, Sugar Rush, Starlight Princess",
        "areas": [
            {
                "id": "slot_balance",
                "label": "Balance",
                "color": "#10b981",
                "roi": {"x": 0.05, "y": 0.91, "w": 0.18, "h": 0.06},
            },
            {
                "id": "slot_bet",
                "label": "Bet",
                "color": "#38bdf8",
                "roi": {"x": 0.40, "y": 0.91, "w": 0.15, "h": 0.06},
            },
            {
                "id": "slot_win",
                "label": "Win",
                "color": "#f59e0b",
                "roi": {"x": 0.30, "y": 0.50, "w": 0.40, "h": 0.16},
            },
            {
                "id": "slot_bonus",
                "label": "Bonus / Free Spins",
                "color": "#a855f7",
                "roi": {"x": 0.40, "y": 0.08, "w": 0.20, "h": 0.07},
            },
        ],
    },
    "hacksaw_gaming": {
        "name": "Hacksaw Gaming",
        "description": "Wanted Dead or a Wild, Dork Unit, Chaos Crew, RIP City",
        "areas": [
            {
                "id": "slot_balance",
                "label": "Balance",
                "color": "#10b981",
                "roi": {"x": 0.04, "y": 0.93, "w": 0.16, "h": 0.05},
            },
            {
                "id": "slot_bet",
                "label": "Bet",
                "color": "#38bdf8",
                "roi": {"x": 0.42, "y": 0.93, "w": 0.16, "h": 0.05},
            },
            {
                "id": "slot_win",
                "label": "Win",
                "color": "#f59e0b",
                "roi": {"x": 0.35, "y": 0.45, "w": 0.30, "h": 0.14},
            },
            {
                "id": "slot_bonus",
                "label": "Bonus / Free Spins",
                "color": "#a855f7",
                "roi": {"x": 0.04, "y": 0.08, "w": 0.18, "h": 0.07},
            },
        ],
    },
    "nolimit_city": {
        "name": "Nolimit City",
        "description": "San Quentin, Mental, Tombstone RIP, Fire in the Hole",
        "areas": [
            {
                "id": "slot_balance",
                "label": "Balance",
                "color": "#10b981",
                "roi": {"x": 0.05, "y": 0.92, "w": 0.18, "h": 0.06},
            },
            {
                "id": "slot_bet",
                "label": "Bet",
                "color": "#38bdf8",
                "roi": {"x": 0.78, "y": 0.92, "w": 0.16, "h": 0.06},
            },
            {
                "id": "slot_win",
                "label": "Win",
                "color": "#f59e0b",
                "roi": {"x": 0.30, "y": 0.48, "w": 0.40, "h": 0.15},
            },
            {
                "id": "slot_bonus",
                "label": "Bonus / Free Spins",
                "color": "#a855f7",
                "roi": {"x": 0.42, "y": 0.10, "w": 0.16, "h": 0.07},
            },
        ],
    },
    "default_slots": {
        "name": "Stake Standard Slots",
        "description": "Generic Stake & Casino layout with balance, bet, and central win",
        "areas": [
            {
                "id": "slot_balance",
                "label": "Balance",
                "color": "#10b981",
                "roi": {"x": 0.05, "y": 0.88, "w": 0.22, "h": 0.08},
            },
            {
                "id": "slot_bet",
                "label": "Bet",
                "color": "#38bdf8",
                "roi": {"x": 0.40, "y": 0.88, "w": 0.20, "h": 0.08},
            },
            {
                "id": "slot_win",
                "label": "Win",
                "color": "#f59e0b",
                "roi": {"x": 0.35, "y": 0.48, "w": 0.30, "h": 0.12},
            },
        ],
    },
}


def get_slot_preset(preset_name: str) -> List[Dict[str, Any]]:
    """Returns a list of extraction area configs for a given provider preset."""
    norm = preset_name.lower().strip()
    if norm in SLOT_PRESETS:
        return [dict(a) for a in SLOT_PRESETS[norm]["areas"]]
    return [dict(a) for a in SLOT_PRESETS["default_slots"]["areas"]]


def list_available_presets() -> List[Dict[str, str]]:
    """Lists available slot provider presets with labels and descriptions."""
    return [
        {"key": key, "name": val["name"], "description": val["description"]}
        for key, val in SLOT_PRESETS.items()
    ]
