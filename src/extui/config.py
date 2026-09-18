from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "extui"


def data_dir() -> Path:
    override = os.environ.get("EXTUI_HOME")
    return Path(override).expanduser() if override else Path(user_data_dir(APP_NAME, appauthor=False))


def write_private_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass
class Configuration:
    selected_server_id: str | None = None
    refresh_interval_seconds: float = 10.0
    player_aliases: dict[str, str] = field(default_factory=dict)
    theme: str | None = None
    icons: str | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Configuration":
        aliases = raw.get("playerAliases") or {}
        interval = raw.get("refreshIntervalSeconds", 10.0)
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            interval = 10.0
        return cls(
            selected_server_id=raw.get("selectedServerID") or None,
            refresh_interval_seconds=max(interval, 5.0),
            player_aliases={str(k): str(v) for k, v in aliases.items()},
            theme=raw.get("theme") or None,
            icons=raw.get("icons") or None,
        )

    def to_dict(self) -> dict:
        payload: dict = {"refreshIntervalSeconds": self.refresh_interval_seconds}
        if self.selected_server_id:
            payload["selectedServerID"] = self.selected_server_id
        if self.player_aliases:
            payload["playerAliases"] = dict(sorted(self.player_aliases.items()))
        if self.theme:
            payload["theme"] = self.theme
        if self.icons:
            payload["icons"] = self.icons
        return payload


class ConfigurationStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "config.json"

    def load(self) -> Configuration:
        if not self.path.exists():
            return Configuration()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return Configuration()
        return Configuration.from_dict(raw if isinstance(raw, dict) else {})

    def save(self, configuration: Configuration) -> None:
        write_private_json(self.path, configuration.to_dict())
