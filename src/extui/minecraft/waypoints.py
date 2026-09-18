from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from extui.config import data_dir, write_private_json


@dataclass
class Waypoint:
    name: str
    dimension: str
    x: int
    z: int
    y: int | None = None
    source: str | None = None
    target_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()).upper())
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def coordinates(self) -> str:
        return f"{self.x}, {self.y if self.y is not None else '~'}, {self.z}"

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "name": self.name,
            "dimension": self.dimension,
            "x": self.x,
            "z": self.z,
            "createdAt": self.created_at.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        if self.y is not None:
            payload["y"] = self.y
        if self.source:
            payload["source"] = self.source
        if self.target_id:
            payload["targetID"] = self.target_id
        return payload

    @classmethod
    def from_dict(cls, raw: dict) -> "Waypoint":
        created = raw.get("createdAt")
        try:
            created_at = datetime.fromisoformat(str(created).replace("Z", "+00:00")) if created else datetime.now(timezone.utc)
        except ValueError:
            created_at = datetime.now(timezone.utc)
        y = raw.get("y")
        return cls(
            name=str(raw.get("name", "")),
            dimension=str(raw.get("dimension", "overworld")),
            x=int(raw.get("x", 0)),
            z=int(raw.get("z", 0)),
            y=int(y) if y is not None else None,
            source=raw.get("source") or None,
            target_id=raw.get("targetID") or None,
            id=str(raw.get("id") or uuid.uuid4()).upper(),
            created_at=created_at,
        )


class WaypointStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "waypoints.json"
        self._values: list[Waypoint] = []
        self.reload()

    def reload(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._values = [Waypoint.from_dict(item) for item in raw if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            self._values = []

    def all(self, dimension: str | None = None, source: str | None = None) -> list[Waypoint]:
        values = [w for w in self._values if (dimension is None or w.dimension == dimension) and (source is None or w.source == source)]
        return sorted(values, key=lambda w: w.created_at, reverse=True)

    def get(self, waypoint_id: str) -> Waypoint | None:
        return next((w for w in self._values if w.id == waypoint_id.upper()), None)

    def add(self, waypoint: Waypoint) -> None:
        self._values.append(waypoint)
        self._save()

    def rename(self, waypoint_id: str, name: str) -> bool:
        name = name.strip()
        waypoint = self.get(waypoint_id)
        if not name or waypoint is None:
            return False
        waypoint.name = name
        self._save()
        return True

    def delete(self, waypoint_id: str) -> bool:
        before = len(self._values)
        self._values = [w for w in self._values if w.id != waypoint_id.upper()]
        if len(self._values) != before:
            self._save()
            return True
        return False

    def _save(self) -> None:
        write_private_json(self.path, [w.to_dict() for w in self._values])
