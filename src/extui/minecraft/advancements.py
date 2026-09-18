from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from extui.api.models import FileInfo

ADVENTURING_TIME_ID = "minecraft:adventure/adventuring_time"

_ADVENTURING_TIME_BIOMES = [
    "badlands", "bamboo_jungle", "beach", "birch_forest", "cherry_grove", "cold_ocean", "dark_forest",
    "deep_cold_ocean", "deep_dark", "deep_frozen_ocean", "deep_lukewarm_ocean", "deep_ocean", "desert",
    "dripstone_caves", "eroded_badlands", "flower_forest", "forest", "frozen_ocean", "frozen_peaks",
    "frozen_river", "grove", "ice_spikes", "jagged_peaks", "jungle", "lukewarm_ocean", "lush_caves",
    "mangrove_swamp", "meadow", "mushroom_fields", "ocean", "old_growth_birch_forest", "old_growth_pine_taiga",
    "old_growth_spruce_taiga", "plains", "river", "savanna", "savanna_plateau", "snowy_beach", "snowy_plains",
    "snowy_slopes", "snowy_taiga", "sparse_jungle", "stony_peaks", "stony_shore", "sunflower_plains", "swamp",
    "taiga", "warm_ocean", "windswept_forest", "windswept_gravelly_hills", "windswept_hills", "windswept_savanna",
    "wooded_badlands",
]


class AdvancementError(RuntimeError):
    pass


@dataclass(frozen=True)
class Criterion:
    id: str
    completed_at: str | None = None


@dataclass(frozen=True)
class AdvancementProgress:
    id: str
    done: bool
    criteria: tuple[Criterion, ...]

    @property
    def namespace(self) -> str:
        return self.id.split(":", 1)[0] if ":" in self.id else "minecraft"


@dataclass(frozen=True)
class AdvancementDefinition:
    id: str
    criteria: frozenset[str]


@dataclass(frozen=True)
class AdvancementSummary:
    progress: AdvancementProgress
    required: frozenset[str] | None = None

    @property
    def completed(self) -> frozenset[str]:
        return frozenset(c.id for c in self.progress.criteria)

    @property
    def missing(self) -> frozenset[str] | None:
        return None if self.required is None else self.required - self.completed

    @property
    def completed_count(self) -> int:
        return len(self.completed)

    @property
    def required_count(self) -> int | None:
        return None if self.required is None else len(self.required)

    @property
    def percentage(self) -> float | None:
        if not self.required:
            return 100.0 if self.progress.done else None
        return min(100.0, self.completed_count / len(self.required) * 100.0)

    @property
    def progress_label(self) -> str:
        if self.progress.done:
            return "✓ done"
        required = self.required_count
        return f"{self.completed_count}/{required if required is not None else '?'}"


@dataclass(frozen=True)
class AdvancementDocument:
    data_version: int | None
    advancements: tuple[AdvancementProgress, ...]


@dataclass(frozen=True)
class AdvancementPlayer:
    uuid: str
    display_name: str | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.uuid


def parse_progress(data: bytes) -> AdvancementDocument:
    try:
        root = json.loads(data.decode("utf-8", "replace"))
    except ValueError as error:
        raise AdvancementError("The advancement JSON is malformed.") from error
    if not isinstance(root, dict):
        raise AdvancementError("The advancement JSON is malformed.")
    values: list[AdvancementProgress] = []
    for advancement_id, entry in root.items():
        if advancement_id == "DataVersion" or not isinstance(entry, dict):
            continue
        raw_criteria = entry.get("criteria") if isinstance(entry.get("criteria"), dict) else {}
        criteria = tuple(sorted((Criterion(str(k), str(v) if v is not None else None) for k, v in raw_criteria.items()), key=lambda c: c.id))
        values.append(AdvancementProgress(str(advancement_id), bool(entry.get("done", False)), criteria))
    version = root.get("DataVersion")
    return AdvancementDocument(int(version) if isinstance(version, int) else None, tuple(sorted(values, key=lambda a: a.id)))


def parse_definition(advancement_id: str, data: bytes) -> AdvancementDefinition:
    try:
        root = json.loads(data.decode("utf-8", "replace"))
    except ValueError as error:
        raise AdvancementError("The advancement definition JSON is malformed.") from error
    if not isinstance(root, dict) or not isinstance(root.get("criteria"), dict):
        raise AdvancementError("The advancement definition JSON is malformed.")
    return AdvancementDefinition(advancement_id, frozenset(str(key) for key in root["criteria"]))


_VERSION = re.compile(r"(?<![0-9])(\d+)\.(\d+)(?:\.(\d+))?")


def parse_minecraft_version(raw: str) -> tuple[int, int, int | None] | None:
    versions = [(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None) for m in _VERSION.finditer(raw or "")]
    return next((v for v in versions if v[0] == 1), versions[0] if versions else None)


def adventuring_time_definition(raw_version: str | None) -> AdvancementDefinition | None:
    version = parse_minecraft_version(raw_version or "")
    if not version or version[0] != 1 or version[1] not in (20, 21):
        return None
    return AdvancementDefinition(ADVENTURING_TIME_ID, frozenset(f"minecraft:{b}" for b in _ADVENTURING_TIME_BIOMES))


def resolve_adventuring_time(server_definition: AdvancementDefinition | None, raw_version: str | None) -> AdvancementDefinition | None:
    return server_definition or adventuring_time_definition(raw_version)


def build_summaries(document: AdvancementDocument, raw_version: str | None, definitions: dict[str, AdvancementDefinition]) -> list[AdvancementSummary]:
    summaries = []
    for progress in document.advancements:
        definition = definitions.get(progress.id)
        if definition is None and progress.id == ADVENTURING_TIME_ID:
            definition = adventuring_time_definition(raw_version)
        summaries.append(AdvancementSummary(progress, definition.criteria if definition else None))
    return summaries


class FileService(Protocol):
    async def file_info(self, server_id: str, path: str) -> FileInfo: ...
    async def file_data(self, server_id: str, path: str) -> bytes: ...


@dataclass
class Discovery:
    world_path: str
    players: list[AdvancementPlayer] = field(default_factory=list)


class AdvancementSource:
    def __init__(self, service: FileService, server_id: str, aliases: dict[str, str] | None = None) -> None:
        self._service = service
        self._server_id = server_id
        self._aliases = aliases or {}

    async def discover(self) -> Discovery:
        root = await self._service.file_info(self._server_id, "")
        for world in root.sorted_children:
            if not world.is_directory:
                continue
            for relative in ("advancements", "players/advancements"):
                path = "/".join(p for p in (world.path, relative) if p)
                try:
                    directory = await self._service.file_info(self._server_id, path)
                except Exception:
                    continue
                if not directory.is_directory:
                    continue
                players = [
                    AdvancementPlayer(child.name[:-5], self._aliases.get(child.name[:-5]))
                    for child in directory.sorted_children
                    if not child.is_directory and child.name.endswith(".json")
                ]
                if players:
                    players.sort(key=lambda p: p.label.lower())
                    return Discovery(world.path, players)
        raise AdvancementError("No player advancement directory was found through the exaroton Files API.")

    async def progress(self, uuid: str, world_path: str) -> AdvancementDocument:
        for relative in (f"advancements/{uuid}.json", f"players/advancements/{uuid}.json"):
            path = "/".join(p for p in (world_path, relative) if p)
            try:
                info = await self._service.file_info(self._server_id, path)
            except Exception:
                continue
            if not info.is_readable:
                raise AdvancementError(f"Advancement metadata is visible, but exaroton denied reading {path}.")
            return parse_progress(await self._service.file_data(self._server_id, path))
        raise AdvancementError("No advancement file was found for that player.")

    async def definition(self, advancement_id: str, world_path: str) -> AdvancementDefinition | None:
        if ":" not in advancement_id:
            return None
        namespace, name = advancement_id.split(":", 1)
        try:
            datapacks = await self._service.file_info(self._server_id, f"{world_path}/datapacks")
        except Exception:
            return None
        for pack in datapacks.sorted_children:
            if not pack.is_directory:
                continue
            for folder in ("advancement", "advancements"):
                path = f"{pack.path}/data/{namespace}/{folder}/{name}.json"
                try:
                    info = await self._service.file_info(self._server_id, path)
                except Exception:
                    continue
                if info.is_readable and not info.is_directory:
                    return parse_definition(advancement_id, await self._service.file_data(self._server_id, path))
        return None
