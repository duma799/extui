from __future__ import annotations

import re
from dataclasses import dataclass, replace

from extui.api.text import plain_text

_DIMENSION = re.compile(r"^[A-Za-z0-9_:\-.]+$")


class ChunkyError(ValueError):
    pass


@dataclass(frozen=True)
class ChunkyConfiguration:
    dimension: str = "world"
    center_x: int = 0
    center_z: int = 0
    radius: int = 500

    def validated(self) -> "ChunkyConfiguration":
        if not self.dimension or not _DIMENSION.match(self.dimension):
            raise ChunkyError("Invalid dimension name.")
        if self.radius <= 0:
            raise ChunkyError("Radius must be a positive whole number.")
        return self

    @property
    def estimated_square_chunks(self) -> int:
        side = (self.radius * 2 + 15) // 16
        return side * side

    @property
    def is_large_job(self) -> bool:
        return self.estimated_square_chunks >= 100_000

    def start_command(self) -> str:
        c = self.validated()
        return f"chunky start {c.dimension} square {c.center_x} {c.center_z} {c.radius}"


class ChunkyCommand:
    STATUS = "chunky progress"

    @staticmethod
    def pause(dimension: str | None = None) -> str:
        return " ".join(part for part in ("chunky", "pause", dimension) if part)

    @staticmethod
    def resume(dimension: str | None = None) -> str:
        return " ".join(part for part in ("chunky", "continue", dimension) if part)

    @staticmethod
    def cancel(dimension: str | None = None) -> str:
        return " ".join(part for part in ("chunky", "cancel", dimension) if part)


@dataclass(frozen=True)
class ChunkyProgress:
    lifecycle: str = "idle"
    world: str | None = None
    processed_chunks: int | None = None
    percentage: float | None = None
    chunks_per_second: float | None = None
    eta: str | None = None
    message: str | None = None


_WORLD = re.compile(r"Task (?:running|finished|paused|cancelled|canceled) for ([^\.,]+)", re.I)
_PROCESSED = re.compile(r"Processed:\s*([0-9]+)", re.I)
_PERCENT = re.compile(r"\(([0-9]+(?:[.,][0-9]+)?)%\)")
_RATE = re.compile(r"Rate:\s*([0-9]+(?:[.,][0-9]+)?)\s*(?:cps|chunks/s)", re.I)
_ETA = re.compile(r"ETA:\s*([^,]+)", re.I)


def _number(value: str) -> float:
    return float(value.replace(",", "."))


def parse_chunky_line(raw: str, previous: ChunkyProgress | None = None) -> ChunkyProgress | None:
    line = plain_text(raw)
    if "[chunky]" not in line.lower():
        return None
    value = previous or ChunkyProgress()
    lower = line.lower()
    updates: dict = {"message": line.split("[Chunky]", 1)[-1].strip() if "[Chunky]" in line else line}
    if match := _WORLD.search(line):
        updates["world"] = match.group(1).strip()
    if "task running" in lower or "task started" in lower:
        updates["lifecycle"] = "running"
    if "paused" in lower:
        updates["lifecycle"] = "paused"
    if "finished" in lower or "complete" in lower:
        updates["lifecycle"] = "completed"
        updates["percentage"] = 100.0
    if "cancelled" in lower or "canceled" in lower:
        updates["lifecycle"] = "cancelled"
    if "no tasks running" in lower or "no task" in lower:
        updates["lifecycle"] = "idle"
    if "error" in lower or "failed" in lower:
        updates["lifecycle"] = "error"
    if match := _PROCESSED.search(line):
        updates["processed_chunks"] = int(match.group(1))
    if match := _PERCENT.search(line):
        updates["percentage"] = _number(match.group(1))
    if match := _RATE.search(line):
        updates["chunks_per_second"] = _number(match.group(1))
    if match := _ETA.search(line):
        updates["eta"] = match.group(1).strip()
    return replace(value, **updates)
