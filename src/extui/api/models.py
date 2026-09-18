from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from .text import plain_text, sanitize


class ServerStatus(IntEnum):
    OFFLINE = 0
    ONLINE = 1
    STARTING = 2
    STOPPING = 3
    RESTARTING = 4
    SAVING = 5
    LOADING = 6
    CRASHED = 7
    PENDING = 8
    TRANSFERRING = 9
    PREPARING = 10

    @property
    def label(self) -> str:
        return self.name

    @property
    def is_transitional(self) -> bool:
        return self not in (ServerStatus.OFFLINE, ServerStatus.ONLINE, ServerStatus.CRASHED)

    @property
    def can_start(self) -> bool:
        return self in (ServerStatus.OFFLINE, ServerStatus.CRASHED)

    @classmethod
    def parse(cls, value: Any) -> "ServerStatus":
        try:
            return cls(int(value))
        except (TypeError, ValueError):
            return cls.OFFLINE


@dataclass(frozen=True)
class Account:
    name: str
    email: str
    verified: bool
    credits: float

    @classmethod
    def from_dict(cls, raw: dict) -> "Account":
        return cls(
            name=str(raw.get("name", "")),
            email=str(raw.get("email", "")),
            verified=bool(raw.get("verified", False)),
            credits=float(raw.get("credits") or 0.0),
        )


@dataclass(frozen=True)
class Players:
    max: int = 0
    count: int = 0
    list: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Players":
        raw = raw or {}
        names = raw.get("list") or []
        return cls(
            max=int(raw.get("max") or 0),
            count=int(raw.get("count") or 0),
            list=tuple(sanitize(str(name)) for name in names),
        )


@dataclass(frozen=True)
class Software:
    id: str
    name: str
    version: str

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Software | None":
        if not raw:
            return None
        return cls(id=str(raw.get("id", "")), name=str(raw.get("name", "")), version=str(raw.get("version", "")))


@dataclass(frozen=True)
class Server:
    id: str
    name: str
    address: str
    motd: str
    status: ServerStatus
    host: str | None
    port: int | None
    players: Players
    software: Software | None
    shared: bool

    @classmethod
    def from_dict(cls, raw: dict) -> "Server":
        return cls(
            id=str(raw.get("id", "")),
            name=sanitize(str(raw.get("name", ""))),
            address=sanitize(str(raw.get("address", ""))),
            motd=str(raw.get("motd") or ""),
            status=ServerStatus.parse(raw.get("status")),
            host=raw.get("host") or None,
            port=int(raw["port"]) if raw.get("port") is not None else None,
            players=Players.from_dict(raw.get("players")),
            software=Software.from_dict(raw.get("software")),
            shared=bool(raw.get("shared", False)),
        )

    @property
    def software_label(self) -> str:
        if not self.software:
            return "—"
        return f"{self.software.name} {self.software.version}".strip()


@dataclass(frozen=True)
class FileInfo:
    path: str
    name: str
    is_text_file: bool
    is_config_file: bool
    is_directory: bool
    is_log: bool
    is_readable: bool
    is_writable: bool
    size: int
    children: tuple["FileInfo", ...] | None

    @classmethod
    def from_dict(cls, raw: dict) -> "FileInfo":
        children = raw.get("children")
        return cls(
            path=str(raw.get("path", "")).strip("/"),
            name=sanitize(str(raw.get("name", ""))),
            is_text_file=bool(raw.get("isTextFile", False)),
            is_config_file=bool(raw.get("isConfigFile", False)),
            is_directory=bool(raw.get("isDirectory", False)),
            is_log=bool(raw.get("isLog", False)),
            is_readable=bool(raw.get("isReadable", False)),
            is_writable=bool(raw.get("isWritable", False)),
            size=int(raw.get("size") or 0),
            children=tuple(cls.from_dict(child) for child in children) if isinstance(children, list) else None,
        )

    @property
    def sorted_children(self) -> list["FileInfo"]:
        return sorted(self.children or (), key=lambda f: (not f.is_directory, f.name.lower()))


class ServerAction(str):
    START = "start"
    STOP = "stop"
    RESTART = "restart"

    ALL = ("start", "stop", "restart")

    @staticmethod
    def validate(action: str, status: ServerStatus) -> None:
        ok = (action == "start" and status.can_start) or (action in ("stop", "restart") and status == ServerStatus.ONLINE)
        if not ok:
            raise ServerActionError(f"Cannot {action} a server while it is {status.label}.")

    @staticmethod
    def target(action: str) -> ServerStatus:
        return ServerStatus.OFFLINE if action == "stop" else ServerStatus.ONLINE

    @staticmethod
    def progress_label(action: str) -> str:
        return {"start": "Starting…", "stop": "Stopping…", "restart": "Restarting…"}[action]


class ServerActionError(RuntimeError):
    pass


_TIMESTAMP = re.compile(r"^\[(\d{2}:\d{2}:\d{2})")
_LEVEL = re.compile(r"/(INFO|WARN|ERROR|FATAL|DEBUG|TRACE)\]")


@dataclass(frozen=True)
class ConsoleLine:
    raw: str
    text: str = field(init=False)
    timestamp: str | None = field(init=False)
    level: str | None = field(init=False)

    def __post_init__(self) -> None:
        text = plain_text(self.raw)
        object.__setattr__(self, "text", text)
        ts = _TIMESTAMP.match(text)
        object.__setattr__(self, "timestamp", ts.group(1) if ts else None)
        level = _LEVEL.search(text)
        object.__setattr__(self, "level", level.group(1) if level else None)


@dataclass(frozen=True)
class StreamEvent:
    ...


@dataclass(frozen=True)
class ConnectionEvent(StreamEvent):
    state: str
    detail: str | None = None
    attempt: int = 0


@dataclass(frozen=True)
class StatusEvent(StreamEvent):
    server: Server


@dataclass(frozen=True)
class ConsoleEvent(StreamEvent):
    line: ConsoleLine


@dataclass(frozen=True)
class TickEvent(StreamEvent):
    average_tick_ms: float

    @property
    def tps(self) -> float:
        if self.average_tick_ms <= 0:
            return 20.0
        return min(20.0, 1000.0 / self.average_tick_ms)


@dataclass(frozen=True)
class StatsEvent(StreamEvent):
    memory_percent: float
    memory_usage_bytes: float


@dataclass(frozen=True)
class HeapEvent(StreamEvent):
    usage_bytes: float
