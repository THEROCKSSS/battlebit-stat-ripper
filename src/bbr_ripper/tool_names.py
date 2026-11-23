"""ToolID -> in-game name, with a small display-name layer.

`tool_names_generated.py` is produced from the game's `Tools.AllTools` asset by
`tools/extract_tool_names.py`.  This module keeps the hand-written display
overrides separate so a regeneration never loses them.
"""

from __future__ import annotations

from .tool_names_generated import TOOL_NAMES

__all__ = ["TOOL_NAMES", "DISPLAY_OVERRIDES", "pretty_name"]


def pretty_name(tool_id: int) -> str | None:
    return DISPLAY_OVERRIDES.get(tool_id) or TOOL_NAMES.get(tool_id)


# In-game display names for the entries where the raw asset name is awkward.
DISPLAY_OVERRIDES: dict[int, str] = {
    34: "RPG-7 HE",
    71: "RPG-7 Frag",
    72: "RPG-7 HE (older)",
    73: "RPG-7 Tandem",
    74: "RPG-7 PGO-7 Tandem",
    75: "RPG-7 PGO-7 HE",
    76: "RPG-7 PGO-7 Frag",
    77: "RPG-7 Frag (older)",
    78: "Drill",
    79: "Hook",
    80: "Grappling Hook",
    81: "Air Drone",
    89: "Tank MG",
    90: "Flashbang",
    91: "Pickaxe",
    92: "Empty Gun",
    93: "Empty Gadget",
    94: "Suicide C4",
    105: "Blackhawk",
    110: "RHIB",
    111: "Minigun",
    112: "KA-60",
    113: "Littlebird (Police)",
    114: "Littlebird (Lux)",
    115: "Littlebird (Transport)",
    116: "Littlebird (Armed)",
    117: "Littlebird (Minigun)",
    118: "Hermit (Transport)",
    119: "Hermit (Armed)",
    120: "Hermit (Police)",
    121: "Hermit (Lux)",
    122: "RCB-90",
    123: "Scorpion EVO",
    124: "RSH-12",
    128: "RCB-90 Turret",
    129: "Anti-Grenade Trophy",
    47: "Humvee (7M)",
    48: "Gas Tiger (7M)",
    49: "Remote Turret (7M)",
    51: "Humvee (Civilian)",
    53: "M1 Abrams",
    54: "Gas Tiger",
    55: "Humvee",
    56: "AP Shell",
    57: "HE Shell",
    58: "M1 Abrams Turret",
    59: "T-90",
    60: "LAV-25A1",
    61: "Gas Tiger (M2)",
    62: "Humvee (M2)",
    63: "T-90 Turret",
    64: "Explosive Bullet",
    65: "LAV-25A1 Turret",
    67: "BTR-82",
    68: "BTR-82 Turret",
    69: "PWC",
    70: "Quad Bike",
    46: "MDX-201",
    50: "SOFLAM",
}
