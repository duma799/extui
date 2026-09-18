from __future__ import annotations

import os
from dataclasses import dataclass

@dataclass(frozen=True)
class IconSet:
    overview: str
    console: str
    players: str
    chunky: str
    advancements: str
    exploration: str
    structures: str
    waypoints: str
    files: str
    logs: str

    server: str
    player_count: str
    tps: str
    memory: str
    credits: str
    stream: str
    clock: str

    ok: str
    warning: str
    error: str
    dot_on: str
    dot_off: str
    dot_partial: str
    dot_pending: str
    bullet: str
    folder: str
    file: str
    arrow: str


NERD = IconSet(
    overview="",
    console="",
    players="",
    chunky="",
    advancements="",
    exploration="",
    structures="",
    waypoints="",
    files="",
    logs="",
    server="",
    player_count="",
    tps="",
    memory="",
    credits="",
    stream="",
    clock="",
    ok="",
    warning="",
    error="",
    dot_on="●",
    dot_off="○",
    dot_partial="◐",
    dot_pending="◌",
    bullet="·",
    folder="",
    file="",
    arrow="→",
)

ASCII = IconSet(
    overview="~", console=">", players="&", chunky="#", advancements="*",
    exploration="+", structures="^", waypoints="@", files="/", logs="=",
    server="[]", player_count="P", tps="T", memory="M", credits="$", stream="<>", clock="@",
    ok="ok", warning="!", error="x",
    dot_on="*", dot_off="o", dot_partial="=", dot_pending=".", bullet="-",
    folder="/", file=".", arrow="->",
)

SETS = {"nerd": NERD, "ascii": ASCII}

_active: IconSet = NERD


def resolve_name(configured: str | None = None) -> str:
    for candidate in (os.environ.get("EXTUI_ICONS"), configured):
        if candidate and candidate.strip().lower() in SETS:
            return candidate.strip().lower()
    return "nerd"


def use(name: str | None) -> IconSet:
    global _active
    _active = SETS[resolve_name(name)]
    return _active


def icons() -> IconSet:
    return _active
