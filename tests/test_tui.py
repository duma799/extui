from __future__ import annotations

import asyncio

import pytest

from extui.api.models import ServerStatus
from extui.config import ConfigurationStore

pytestmark = pytest.mark.asyncio

PAGE_KEYS = [("1", "overview"), ("2", "console"), ("3", "players"), ("4", "chunky"),
             ("5", "advancements"), ("6", "exploration"), ("7", "structures"),
             ("8", "waypoints"), ("9", "files"), ("0", "logs")]


async def goto(pilot, key: str) -> None:
    await pilot.press("escape")
    await pilot.pause(0.05)
    await pilot.press(key)
    await pilot.pause(0.6)


async def test_connects_and_populates_initial_state(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        assert app.stream_state == "live"
        assert app.server is not None and app.server.status is ServerStatus.ONLINE
        assert len(app.console_lines) > 20, "console is seeded from the log tail"
        assert app.credits is not None
        assert app.ram_gb == 4.0


async def test_every_page_renders_and_focuses_something_useful(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.0)
        for key, expected in PAGE_KEYS:
            await goto(pilot, key)
            assert app.current_page.KEY == expected
            assert app.focused is not None


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (200, 60)])
async def test_every_page_renders_at_any_terminal_size(make_app, size) -> None:
    app = make_app()
    async with app.run_test(size=size) as pilot:
        await asyncio.sleep(0.8)
        for key, expected in PAGE_KEYS:
            await pilot.press("escape")
            await pilot.press(key)
            await asyncio.sleep(0.4)
            assert app.current_page.KEY == expected, f"{expected} broke at {size}"


async def test_telemetry_flows_while_online_and_clears_when_stopped(app, service) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(2.5)
        assert app.tps_history and app.mem_history
        await goto(pilot, "1")
        await pilot.press("s")
        await pilot.pause(0.6)
        assert type(app.screen).__name__ == "ConfirmDialog"
        await pilot.press("y")
        await pilot.pause(3.0)
        assert app.server.status is ServerStatus.OFFLINE
        assert service.actions == ["stop"]
        assert not app.tps_history, "stale telemetry must not linger once the server stops"


async def test_start_stop_round_trip(app, service) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "1")
        await pilot.press("s"); await pilot.pause(0.5); await pilot.press("y")
        await pilot.pause(3.0)
        assert app.server.status is ServerStatus.OFFLINE
        await pilot.press("s"); await pilot.pause(0.5); await pilot.press("y")
        await pilot.pause(4.0)
        assert app.server.status is ServerStatus.ONLINE
        assert service.actions == ["stop", "start"]


async def test_console_sends_commands_and_recalls_history(app, service) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "2")
        for ch in "say hello":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(0.8)
        assert "say hello" in service.commands
        assert any("hello" in line.text for line in app.console_lines)
        await pilot.press("up")
        await pilot.pause(0.1)
        assert app.console_page.query_one("#console-input").value == "say hello"


async def test_console_refuses_to_send_while_offline(app, service) -> None:
    service.status = ServerStatus.OFFLINE
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "2")
        for ch in "say hi":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(0.6)
        assert service.commands == [], "commands must not reach an offline server"


async def test_player_lists_switch_and_load_entries(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "3")
        page = app.current_page
        assert set(page.list_names) >= {"online", "whitelist", "ops"}
        assert page.query_one("#player-table").row_count == 3
        await pilot.press("right")
        await pilot.pause(0.8)
        assert page.list_names[page.selected] == "whitelist"
        assert page.query_one("#player-table").row_count == 4
        await pilot.press("right")
        await pilot.pause(0.8)
        assert page.list_names[page.selected] == "ops"
        assert page.query_one("#player-table").row_count == 1


async def test_chunky_progress_parsing_and_dialog(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "4")
        await pilot.press("g")
        await pilot.pause(1.0)
        assert app.chunky.lifecycle == "running"
        assert app.chunky.percentage == 37.4
        await pilot.press("n")
        await pilot.pause(0.5)
        assert type(app.screen).__name__ == "ChunkyDialog"
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "Screen"


async def test_chunky_cancel_asks_before_destroying_progress(app, service) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "4")
        await pilot.press("x")
        await pilot.pause(0.5)
        assert type(app.screen).__name__ == "ConfirmDialog"
        await pilot.press("escape")
        await pilot.pause(0.4)
        assert "chunky cancel" not in service.commands, "declining must not send the command"


async def test_advancements_discovered_and_summarised(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "5")
        await pilot.pause(1.2)
        assert len(app.adv.players) == 1
        assert len(app.adv.summaries) == 5
        assert app.current_page.query_one("#adv-table").row_count == 5
        summary = app.adv.adventuring_time
        assert summary is not None and summary.missing is not None
        assert len(summary.missing) == 43


async def test_advancement_search_filters_the_table(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "5")
        await pilot.pause(1.2)
        await pilot.press("slash")
        await pilot.pause(0.2)
        for ch in "nether":
            await pilot.press(ch)
        await pilot.pause(0.4)
        assert app.current_page.query_one("#adv-table").row_count == 1


async def test_exploration_locates_a_biome_and_saves_a_waypoint(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "6")
        await pilot.pause(1.4)
        assert app.current_page.query_one("#exp-missing").option_count == 43
        await pilot.press("l")
        await pilot.pause(1.2)
        assert any(r.kind == "biome" for r in app.locate_results)
        await pilot.press("ctrl+s")
        await pilot.pause(0.6)
        assert type(app.screen).__name__ == "WaypointDialog"
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert len(app.waypoints.all()) == 1


async def test_structures_locate_from_the_input(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "7")
        for ch in "minecraft:ancient_city":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(1.2)
        assert any(r.kind == "structure" for r in app.locate_results)
        assert app.current_page.query_one("#structure-results").row_count >= 1
        await pilot.press("ctrl+s")
        await pilot.pause(0.6)
        assert type(app.screen).__name__ == "WaypointDialog", "ctrl+s must work while the input has focus"


async def test_waypoints_delete_and_teleport_helper(app, tmp_path) -> None:
    from extui.minecraft.waypoints import Waypoint

    app.waypoints.add(Waypoint("Base", "overworld", 100, 200, y=64))
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "8")
        assert app.current_page.query_one("#wp-table").row_count == 1
        await pilot.press("t")
        await pilot.pause(0.5)
        assert app.current_page.KEY == "console"
        assert app.console_page.query_one("#console-input").value == "tp @p 100 64 200"
        await goto(pilot, "8")
        await pilot.press("d")
        await pilot.pause(0.5)
        assert type(app.screen).__name__ == "ConfirmDialog"
        await pilot.press("y")
        await pilot.pause(0.5)
        assert app.waypoints.all() == []


async def test_file_browser_lists_and_previews(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "9")
        await pilot.pause(1.2)
        tree = app.current_page.query_one("#file-tree")
        assert len(tree.root.children) == 3
        for _ in range(3):
            await pilot.press("down")
            await pilot.pause(0.15)
        await pilot.press("enter")
        await pilot.pause(1.5)
        assert len(app.current_page.query_one("#file-preview").lines) > 0


async def test_logs_snapshot_loads(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "0")
        await pilot.pause(1.2)
        assert len(app.current_page.query_one("#logs-log").lines) > 20


async def test_help_dialog_opens_and_closes(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.0)
        await pilot.press("question_mark")
        await pilot.pause(0.5)
        assert type(app.screen).__name__ == "HelpDialog"
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "Screen"


async def test_theme_choice_is_persisted(app, tmp_path) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.0)
        app.theme = "gruvbox"
        await pilot.pause(0.3)
    assert ConfigurationStore(tmp_path / "config.json").load().theme == "gruvbox"


async def test_offline_server_disables_destructive_shortcuts(app, service) -> None:
    service.status = ServerStatus.OFFLINE
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.2)
        await goto(pilot, "1")
        await pilot.press("r")
        await pilot.pause(0.5)
        assert type(app.screen).__name__ == "Screen", "restart must not be offered while offline"
        assert service.actions == []


async def test_sidebar_collapses_on_narrow_terminals(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)):
        await asyncio.sleep(0.8)
        sidebar = app.query_one("#sidebar")
        assert sidebar.has_class("compact")
        first = sidebar.get_option_at_index(0)
        assert "Overview" not in str(first.prompt), "labels collapse to icons when space is tight"


async def test_sidebar_shows_labels_on_wide_terminals(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(150, 40)):
        await asyncio.sleep(0.8)
        sidebar = app.query_one("#sidebar")
        assert not sidebar.has_class("compact")
        assert "Overview" in str(sidebar.get_option_at_index(0).prompt)


async def test_pages_stay_reachable_after_the_sidebar_collapses(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(150, 40)) as pilot:
        await asyncio.sleep(0.8)
        await pilot.resize_terminal(80, 24)
        await asyncio.sleep(0.5)
        assert app.query_one("#sidebar").has_class("compact")
        for key, expected in PAGE_KEYS:
            await pilot.press("escape")
            await pilot.press(key)
            await asyncio.sleep(0.3)
            assert app.current_page.KEY == expected


async def test_q_quits_from_the_sidebar(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.0)
        assert type(app.focused).__name__ == "Sidebar"
        await pilot.press("q")
        await asyncio.sleep(0.8)
        assert not app.is_running


async def test_overview_shows_a_live_console_tail(app, service) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.5)
        tail = app.current_page.query_one("#overview-tail")
        assert len(tail.lines) > 0, "the tail is seeded from console history"
        before = len(tail.lines)
        await service.send_command("demo-server", "say dashboard")
        await asyncio.sleep(1.0)
        assert len(tail.lines) > before, "new console lines reach the dashboard too"


async def test_overview_lists_online_players(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.5)
        body = app.current_page.query_one("#card-players .card-body")
        rendered = str(body.content)
        for name in ("duma_n1", "Havar887", "Steve"):
            assert name in rendered
        assert "3 of 20 slots used" in rendered


async def test_overview_player_panel_reflects_an_offline_server(app, service) -> None:
    service.status = ServerStatus.OFFLINE
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.5)
        rendered = str(app.current_page.query_one("#card-players .card-body").content)
        assert "offline" in rendered.lower()


async def test_sidebar_badges_track_live_state(app, service) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.5)
        sidebar = app.query_one("#sidebar")

        def prompt(key: str) -> str:
            index = next(i for i, (_, name) in enumerate(PAGE_KEYS) if name == key)
            return str(sidebar.get_option_at_index(index).prompt)

        assert "3" in prompt("players"), "the online player count shows beside Players"

        await service.send_command("demo-server", "chunky progress")
        await asyncio.sleep(1.2)
        assert "37%" in prompt("chunky"), "a running pregeneration shows its percentage"


async def test_console_alerts_badge_appears_and_clears(app, service) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.5)
        sidebar = app.query_one("#sidebar")
        console_index = next(i for i, (_, name) in enumerate(PAGE_KEYS) if name == "console")
        app._console_alerts = 0
        app.refresh_sidebar()

        from extui.api.models import ConsoleEvent, ConsoleLine
        await service._emit(ConsoleEvent(ConsoleLine("[12:00:00] [Server thread/ERROR]: something broke")))
        await asyncio.sleep(1.0)
        assert app._console_alerts >= 1
        assert "1" in str(sidebar.get_option_at_index(console_index).prompt)

        await goto(pilot, "2")
        await asyncio.sleep(0.4)
        assert app._console_alerts == 0, "opening the console acknowledges the alerts"


async def test_default_theme_is_tokyo_night(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.0)
        assert app.theme == "tokyo-night"
        assert "minecraft" in app.available_themes, "the old theme stays selectable"


async def test_interface_draws_no_emoji(app) -> None:
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.5)
        for key, _ in PAGE_KEYS:
            await pilot.press("escape")
            await pilot.press(key)
            await asyncio.sleep(0.4)
            drawn = "\n".join(s.text for s in app.screen._compositor.render_strips())
            offenders = {c for c in drawn if 0x1F000 <= ord(c) <= 0x1FAFF}
            assert not offenders, f"emoji {offenders} still drawn on {key}"


async def test_ascii_icon_mode_draws_no_private_use_glyphs(make_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EXTUI_ICONS", "ascii")
    app = make_app()
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause(1.5)
        drawn = "\n".join(s.text for s in app.screen._compositor.render_strips())
        assert not {c for c in drawn if 0xE000 <= ord(c) <= 0xF8FF}, "ascii mode must avoid Nerd Font glyphs"
