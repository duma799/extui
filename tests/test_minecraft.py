from __future__ import annotations

import json

import pytest

from extui.minecraft.advancements import (
    ADVENTURING_TIME_ID,
    AdvancementDefinition,
    AdvancementError,
    AdvancementSummary,
    adventuring_time_definition,
    build_summaries,
    parse_definition,
    parse_minecraft_version,
    parse_progress,
    resolve_adventuring_time,
)
from extui.minecraft.chunky import ChunkyCommand, ChunkyConfiguration, ChunkyError, parse_chunky_line
from extui.minecraft.locate import LocateError, is_locate_failure, locate_command, parse_locate_line


def test_chunky_commands_use_documented_syntax() -> None:
    config = ChunkyConfiguration("world", -3000, -2700, 10_000)
    assert config.start_command() == "chunky start world square -3000 -2700 10000"
    assert ChunkyCommand.pause() == "chunky pause"
    assert ChunkyCommand.resume() == "chunky continue"
    assert ChunkyCommand.cancel() == "chunky cancel"
    assert ChunkyCommand.STATUS == "chunky progress"
    assert ChunkyCommand.pause("the_nether") == "chunky pause the_nether"


def test_chunky_rejects_bad_configuration() -> None:
    with pytest.raises(ChunkyError):
        ChunkyConfiguration(radius=0).validated()
    with pytest.raises(ChunkyError):
        ChunkyConfiguration(radius=-1).validated()
    with pytest.raises(ChunkyError):
        ChunkyConfiguration(dimension="world; rm -rf /").validated()
    with pytest.raises(ChunkyError):
        ChunkyConfiguration(dimension="").validated()
    assert ChunkyConfiguration(dimension="minecraft:the_nether").validated()


def test_chunky_chunk_estimate_and_large_job_flag() -> None:
    assert ChunkyConfiguration(radius=16).estimated_square_chunks == 4
    assert ChunkyConfiguration(radius=10_000).is_large_job
    assert not ChunkyConfiguration(radius=100).is_large_job


def test_parses_chunky_progress_with_locale_decimals() -> None:
    line = ("[12:00:00] [Server thread/INFO]: [Chunky] Task running for world. "
            "Processed: 182430 chunks (37,4%), ETA: 0:41:23, Rate: 124,5 cps, Current: 1, 2")
    progress = parse_chunky_line(line)
    assert progress is not None
    assert progress.lifecycle == "running"
    assert progress.world == "world"
    assert progress.processed_chunks == 182430
    assert progress.percentage == 37.4
    assert progress.chunks_per_second == 124.5
    assert progress.eta == "0:41:23"


def test_ignores_unrelated_console_output() -> None:
    assert parse_chunky_line("[12:00:00] [Server thread/INFO]: ordinary server output") is None
    assert parse_chunky_line("duma_n1 joined the game") is None


def test_parses_chunky_output_that_carries_color_codes() -> None:
    line = ("§7[Chunky] §aTask running for world. Processed: §e182430§7 chunks (§937.4%§7), "
            "ETA: §641m 23s§7, Rate: §b124 cps")
    progress = parse_chunky_line(line)
    assert progress is not None
    assert progress.lifecycle == "running"
    assert progress.processed_chunks == 182430
    assert progress.percentage == 37.4
    assert progress.eta == "41m 23s"


def test_chunky_lifecycle_retains_earlier_metrics() -> None:
    running = parse_chunky_line("[Chunky] Task running for minecraft:overworld. Processed: 50 chunks (50%), ETA: 0:00:05, Rate: 10 cps")
    assert running is not None and running.lifecycle == "running"
    paused = parse_chunky_line("[Chunky] Task paused for minecraft:overworld.", running)
    assert paused is not None
    assert paused.lifecycle == "paused"
    assert paused.percentage == 50, "metrics from the running update must survive a pause"
    finished = parse_chunky_line("[Chunky] Task finished for world. Processed: 100 chunks (100%), Total time: 0:00:10")
    assert finished is not None and finished.lifecycle == "completed" and finished.percentage == 100
    cancelled = parse_chunky_line("[Chunky] Task cancelled for world")
    assert cancelled is not None and cancelled.lifecycle == "cancelled"


def test_locate_commands_are_validated() -> None:
    assert locate_command("biome", "minecraft:ice_spikes") == "locate biome minecraft:ice_spikes"
    assert locate_command("structure", "nova_structures:lone_citadel") == "locate structure nova_structures:lone_citadel"
    with pytest.raises(LocateError):
        locate_command("biome", "ice spikes; op @a")
    with pytest.raises(LocateError):
        locate_command("biome", "")
    with pytest.raises(LocateError):
        locate_command("village", "minecraft:plains")


def test_parses_locate_output_forms() -> None:
    biome = parse_locate_line(
        "[Server/INFO]: The nearest biome is at [18240 96 -5312] (1,234 blocks away)", "biome", "minecraft:ice_spikes")
    assert biome is not None
    assert (biome.x, biome.y, biome.z, biome.distance) == (18240, 96, -5312, 1234)

    structure = parse_locate_line("The nearest structure is at [208 ~ -14224] (500 blocks away)", "structure", "x")
    assert structure is not None and structure.y is None
    assert structure.coordinates == "208, ~, -14224"

    colored = parse_locate_line(
        "§7The nearest biome is at §a[18240 96 -5312] §7(1,234 blocks away)", "biome", "minecraft:ice_spikes")
    assert colored is not None and colored.x == 18240 and colored.distance == 1234
    assert "§" not in colored.raw_output


def test_locate_ignores_unrelated_and_detects_failure() -> None:
    assert parse_locate_line("duma_n1 joined the game", "biome", "x") is None
    assert parse_locate_line("The nearest biome is somewhere", "biome", "x") is None
    assert is_locate_failure("Could not find a biome of type minecraft:ice_spikes within reasonable distance")
    assert not is_locate_failure("The nearest biome is at [1 ~ 2]")


PROGRESS_FIXTURE = json.dumps({
    "DataVersion": 3953,
    ADVENTURING_TIME_ID: {"criteria": {"minecraft:plains": "2026-09-10 10:00:00 +0000",
                                       "minecraft:desert": "2026-09-10 11:00:00 +0000"}, "done": False},
    "examplemod:journey/root": {"criteria": {"entered_custom_biome": "2026-09-10 12:00:00 +0000"}, "done": True},
}).encode()


def test_parses_vanilla_and_modded_progress() -> None:
    document = parse_progress(PROGRESS_FIXTURE)
    assert document.data_version == 3953
    assert len(document.advancements) == 2
    partial = next(a for a in document.advancements if a.id == ADVENTURING_TIME_ID)
    assert partial.done is False and len(partial.criteria) == 2
    modded = next(a for a in document.advancements if a.namespace == "examplemod")
    assert modded.done is True


def test_rejects_malformed_and_tolerates_missing_criteria() -> None:
    with pytest.raises(AdvancementError):
        parse_progress(b"[")
    with pytest.raises(AdvancementError):
        parse_progress(b"[1, 2, 3]")
    document = parse_progress(b'{"mod:test": {"done": false}}')
    assert document.advancements[0].criteria == ()


def test_definition_parsing_and_exact_missing_set() -> None:
    definition = parse_definition("mod:test", json.dumps(
        {"criteria": {"a": {"trigger": "x"}, "b": {"trigger": "x"}, "mod:c": {"trigger": "x"}}}).encode())
    assert definition.criteria == frozenset({"a", "b", "mod:c"})
    document = parse_progress(json.dumps({"mod:test": {"criteria": {"a": "t", "mod:c": "t"}, "done": False}}).encode())
    summary = AdvancementSummary(document.advancements[0], definition.criteria)
    assert summary.missing == frozenset({"b"})
    assert summary.completed_count == 2 and summary.required_count == 3
    assert summary.percentage == pytest.approx(200 / 3)
    assert summary.progress_label == "2/3"


def test_summary_without_definition_admits_ignorance() -> None:
    document = parse_progress(b'{"mod:test": {"criteria": {"a": "t"}, "done": false}}')
    summary = AdvancementSummary(document.advancements[0])
    assert summary.missing is None
    assert summary.required_count is None
    assert summary.percentage is None
    assert summary.progress_label == "1/?"


def test_minecraft_version_parsing() -> None:
    assert parse_minecraft_version("1.21.4") == (1, 21, 4)
    assert parse_minecraft_version("Fabric 1.21.1") == (1, 21, 1)
    assert parse_minecraft_version("Minecraft 1.20") == (1, 20, None)
    assert parse_minecraft_version("nonsense") is None


def test_parses_the_calendar_versioning_exaroton_reports_today() -> None:
    assert parse_minecraft_version("26.2 (0.19.5)") == (26, 2, None)
    assert parse_minecraft_version("0.19.5 for Minecraft 1.21.4") == (1, 21, 4)


def test_unknown_versions_never_reuse_another_versions_biome_list() -> None:
    assert adventuring_time_definition("26.2 (0.19.5)") is None
    assert resolve_adventuring_time(None, "26.2 (0.19.5)") is None


def test_adventuring_time_catalog_is_version_scoped() -> None:
    assert adventuring_time_definition("1.19.4") is None
    assert adventuring_time_definition("1.22") is None
    assert adventuring_time_definition("nonsense") is None
    for version in ("1.20.4", "1.21.1", "1.21.4", "Fabric 1.21.1", "Minecraft 1.20"):
        definition = adventuring_time_definition(version)
        assert definition is not None and len(definition.criteria) == 53


def test_server_definition_beats_bundled_fallback() -> None:
    server_definition = AdvancementDefinition(ADVENTURING_TIME_ID, frozenset({"modded:required"}))
    assert resolve_adventuring_time(server_definition, "1.22") is server_definition
    assert resolve_adventuring_time(None, "1.21.4") is not None
    assert resolve_adventuring_time(None, "1.19") is None


def test_build_summaries_applies_version_fallback() -> None:
    document = parse_progress(PROGRESS_FIXTURE)
    summaries = build_summaries(document, "1.21.4", {})
    adventuring = next(s for s in summaries if s.progress.id == ADVENTURING_TIME_ID)
    assert adventuring.required_count == 53
    assert adventuring.missing is not None and "minecraft:plains" not in adventuring.missing
    assert "minecraft:ice_spikes" in adventuring.missing
    modded = next(s for s in summaries if s.progress.namespace == "examplemod")
    assert modded.missing is None, "no definition is known for the modded advancement"


def test_build_summaries_without_a_usable_version() -> None:
    summaries = build_summaries(parse_progress(PROGRESS_FIXTURE), "1.19.2", {})
    assert all(s.missing is None for s in summaries)
