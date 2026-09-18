from __future__ import annotations

import re
from dataclasses import dataclass

from extui.api.text import plain_text

_TARGET = re.compile(r"^[A-Za-z0-9_:\-./#]+$")
_COORDS = re.compile(r"\[\s*(-?\d+)\s+(~|-?\d+)\s+(-?\d+)\s*\]")
_DISTANCE = re.compile(r"\(([\d,.]+)\s+blocks? away\)", re.I)


class LocateError(ValueError):
    pass


@dataclass(frozen=True)
class LocateResult:
    kind: str
    target_id: str
    x: int
    y: int | None
    z: int
    distance: int | None
    raw_output: str

    @property
    def coordinates(self) -> str:
        return f"{self.x}, {self.y if self.y is not None else '~'}, {self.z}"


def locate_command(kind: str, target_id: str) -> str:
    if kind not in ("biome", "structure"):
        raise LocateError("Locate kind must be biome or structure.")
    if not target_id or not _TARGET.match(target_id):
        raise LocateError("Invalid Minecraft resource identifier.")
    return f"locate {kind} {target_id}"


def parse_locate_line(raw: str, kind: str, target_id: str) -> LocateResult | None:
    line = plain_text(raw)
    lower = line.lower()
    if "nearest" not in lower and "locate" not in lower and "is at" not in lower:
        return None
    match = _COORDS.search(line)
    if not match:
        return None
    x, middle, z = match.groups()
    distance = None
    if dist := _DISTANCE.search(line):
        try:
            distance = int(float(dist.group(1).replace(",", "")))
        except ValueError:
            distance = None
    return LocateResult(kind, target_id, int(x), None if middle == "~" else int(middle), int(z), distance, line)


def is_locate_failure(raw: str) -> bool:
    lower = plain_text(raw).lower()
    return "could not find" in lower and ("biome" in lower or "structure" in lower)
