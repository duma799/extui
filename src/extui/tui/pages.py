from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Digits, Input, Label, OptionList, ProgressBar, RichLog, Sparkline, Static, Tree
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from extui.api.models import ConsoleLine, FileInfo, Server, ServerStatus
from extui.api.text import motd_to_rich, sanitize, to_rich
from extui.minecraft.advancements import AdvancementSummary
from extui.minecraft.chunky import ChunkyCommand, ChunkyConfiguration, ChunkyProgress
from extui.minecraft.locate import LocateResult
from extui.minecraft.waypoints import Waypoint

from .dialogs import ChunkyDialog, ConfirmDialog, PromptDialog, WaypointDialog
from .icons import icons
from .widgets import CardBody, CommandInput, KeyValue, StatCard, Toolbar, format_bytes, status_text

if TYPE_CHECKING:
    from .app import ExtuiApp

PREVIEW_LIMIT = 64 * 1024
TAIL_MAX = 200


class Page(Vertical):
    KEY = ""
    TITLE = ""

    @classmethod
    def icon(cls) -> str:
        return getattr(icons(), cls.KEY, icons().bullet)

    @property
    def mc(self) -> "ExtuiApp":
        return self.app

    def focus_primary(self) -> None:
        self.focus()

    def refresh_view(self) -> None:
        ...

    def on_show_page(self) -> None: ...
    def on_server(self, server: Server) -> None: ...
    def on_console_line(self, line: ConsoleLine) -> None: ...
    def on_stream_state(self, state: str, detail: str | None) -> None: ...
    def on_telemetry(self) -> None: ...
    def on_chunky(self, progress: ChunkyProgress) -> None: ...
    def on_locate(self, result: LocateResult) -> None: ...
    def on_waypoints(self) -> None: ...
    def on_account(self) -> None: ...

    def action_refresh(self) -> None: ...


class OverviewPage(Page):
    KEY, TITLE = "overview", "Overview"
    BINDINGS = [Binding("f5", "refresh", "Refresh")]

    TAIL_LINES = 200

    def compose(self) -> ComposeResult:
        with Horizontal(classes="card-row", id="overview-top"):
            yield StatCard("Server", CardBody(), id="card-server")
            with StatCard("Status", id="card-status"):
                yield CardBody()
                with Horizontal(classes="button-row"):
                    yield Button("Start", variant="success", id="btn-start", action="app.start_stop")
                    yield Button("Restart", variant="warning", id="btn-restart", action="app.restart")
                    yield Button("Console", id="btn-console", action="app.show_page('console')")
        with Horizontal(classes="card-row", id="overview-metrics"):
            with StatCard("Performance", id="card-perf"):
                with Horizontal(classes="perf-row"):
                    with Vertical(classes="perf-col"):
                        yield Label("TPS", classes="perf-label")
                        yield Digits("—", id="tps-digits")
                        yield Sparkline([], id="tps-spark", summary_function=min)
                    with Vertical(classes="perf-col"):
                        yield Label("Memory", classes="perf-label")
                        yield Digits("—", id="mem-digits")
                        yield Sparkline([], id="mem-spark", summary_function=max)
            with StatCard("Account & connection", id="card-account"):
                yield CardBody()
        with Horizontal(id="overview-bottom"):
            with StatCard("Recent console", id="card-tail"):
                yield RichLog(highlight=False, markup=False, wrap=False, max_lines=TAIL_MAX, id="overview-tail")
            with StatCard("Online players", id="card-players"):
                yield CardBody()

    def on_mount(self) -> None:
        self.render_all()
        for line in list(self.mc.console_lines)[-self.TAIL_LINES:]:
            self._append_tail(line)

    def focus_primary(self) -> None:
        self.query_one("#btn-start", Button).focus()

    def on_show_page(self) -> None:
        self.render_all()

    def on_server(self, server: Server) -> None:
        self.render_all()

    def on_console_line(self, line: ConsoleLine) -> None:
        self._append_tail(line)

    def _append_tail(self, line: ConsoleLine) -> None:
        text = to_rich(line.raw)
        if line.level in ("WARN", "ERROR", "FATAL") and not text.spans:
            text.stylize("yellow" if line.level == "WARN" else "bold red")
        if line.timestamp:
            text.stylize("dim", 0, min(len(text), 10))
        self.query_one("#overview-tail", RichLog).write(text)

    def on_stream_state(self, state: str, detail: str | None) -> None:
        self._render_account()

    def on_account(self) -> None:
        self._render_account()

    def on_telemetry(self) -> None:
        app = self.mc
        online = app.server is not None and app.server.status == ServerStatus.ONLINE

        tps = app.tps_history[-1] if app.tps_history and online else None
        tps_digits = self.query_one("#tps-digits", Digits)
        tps_digits.update(f"{tps:.1f}" if tps is not None else "—")
        tps_digits.set_class(tps is not None and tps < 15, "bad")
        tps_digits.set_class(tps is not None and 15 <= tps < 19, "warn")
        self.query_one("#tps-spark", Sparkline).data = list(app.tps_history) if online else []

        percent = app.mem_history[-1] if app.mem_history and online else None
        mem_digits = self.query_one("#mem-digits", Digits)
        mem_digits.update(f"{percent:.0f}%" if percent is not None else "—")
        mem_digits.set_class(percent is not None and percent >= 90, "bad")
        mem_digits.set_class(percent is not None and 75 <= percent < 90, "warn")
        self.query_one("#mem-spark", Sparkline).data = list(app.mem_history) if online else []
        self._render_account()

    def action_refresh(self) -> None:
        self.mc.refresh_now()

    def render_all(self) -> None:
        app = self.mc
        server = app.server
        info = KeyValue()
        if server:
            info.row("Name", server.name, "bold").row("Address", server.address).row("Software", server.software_label)
            info.row("Shared", "yes" if server.shared else "no").row("ID", server.id, "dim")
            if server.motd:
                info.append("\nMOTD\n", style="dim")
                info.append_text(motd_to_rich(server.motd))
        else:
            info.append("Waiting for server data…", style="dim")
        self.query_one("#card-server", StatCard).body.update(info)

        status = Text()
        if server:
            status.append_text(status_text(server.status))
            status.append("\n")
            if app.active_action:
                status.append(app.active_action_label, style="yellow")
            elif server.status == ServerStatus.ONLINE:
                status.append(f"{server.players.count} of {server.players.max} players online", style="dim")
            elif server.status.is_transitional:
                status.append("Transitioning. Controls unlock once it settles.", style="dim")
            else:
                status.append("Server is stopped. Press s to start it.", style="dim")
        else:
            status.append("—", style="dim")
        self.query_one("#card-status", StatCard).body.update(status)
        start = self.query_one("#btn-start", Button)
        restart = self.query_one("#btn-restart", Button)
        if server and app.active_action is None and server.status == ServerStatus.ONLINE:
            start.label, start.variant, start.disabled = "Stop", "error", False
            restart.disabled = False
        elif server and app.active_action is None and server.status.can_start:
            start.label, start.variant, start.disabled = "Start", "success", False
            restart.disabled = True
        else:
            start.label, start.disabled = ("Working…" if app.active_action else "Start"), True
            restart.disabled = True
        self._render_players()
        self._render_account()
        self.on_telemetry()

    def _render_players(self) -> None:
        app = self.mc
        server = app.server
        text = Text()
        ic = icons()
        if server is None:
            text.append("—", style="dim")
        elif server.status != ServerStatus.ONLINE:
            text.append(f"Server is {server.status.label.lower()}.", style="dim")
        elif not server.players.list:
            if server.players.count:
                text.append(f"{server.players.count} online, names not reported", style="dim")
            else:
                text.append("Nobody online right now.", style="dim")
        else:
            for name in server.players.list:
                text.append(f"{ic.dot_on} ", style="green")
                text.append(f"{name}\n")
            text.append(f"\n{server.players.count} of {server.players.max} slots used", style="dim")
        self.query_one("#card-players", StatCard).body.update(text)

    def _render_account(self) -> None:
        app = self.mc
        info = KeyValue()
        info.row("Credits", f"{app.credits:,.2f}" if app.credits is not None else "—", "yellow")
        if app.memory_usage and app.server is not None and app.server.status == ServerStatus.ONLINE:
            used = format_bytes(app.memory_usage)
            info.row("Memory", f"{used} of {app.ram_gb:g} GB" if app.ram_gb else used)
            if app.heap_usage:
                info.row("Java heap", format_bytes(app.heap_usage))
        else:
            info.row("RAM", f"{app.ram_gb:g} GB allocated" if app.ram_gb else "—")
        info.row("Stream", Text(app.stream_state + (f" · {app.stream_detail}" if app.stream_detail else ""),
                                style={"live": "green", "disconnected": "red"}.get(app.stream_state, "yellow")))
        info.row("Polling", f"every {app.refresh_interval:g}s")
        if app.api_error:
            info.row("Last error", Text(app.api_error, style="red"))
        self.query_one("#card-account", StatCard).body.update(info)


class ConsolePage(Page):
    KEY, TITLE = "console", "Console"
    BINDINGS = [Binding("ctrl+l", "clear", "Clear", show=False)]

    LEVEL_STYLES = {"WARN": "yellow", "ERROR": "bold red", "FATAL": "bold red", "DEBUG": "dim"}

    def compose(self) -> ComposeResult:
        yield Static("", id="console-state", classes="page-banner")
        yield RichLog(highlight=False, markup=False, wrap=True, max_lines=2000, id="console-log")
        yield CommandInput(id="console-input")

    def on_mount(self) -> None:
        for line in self.mc.console_lines:
            self._write(line)
        self.on_stream_state(self.mc.stream_state, self.mc.stream_detail)

    def focus_primary(self) -> None:
        self.query_one("#console-input", CommandInput).focus()

    def on_console_line(self, line: ConsoleLine) -> None:
        self._write(line)

    def _write(self, line: ConsoleLine) -> None:
        text = to_rich(line.raw)
        if line.level in self.LEVEL_STYLES and not text.spans:
            text.stylize(self.LEVEL_STYLES[line.level])
        if line.timestamp:
            text.stylize("dim", 0, min(len(text), 10))
        self.query_one("#console-log", RichLog).write(text)

    def on_stream_state(self, state: str, detail: str | None) -> None:
        self.on_server(self.mc.server) if self.mc.server else self._banner(state, detail)

    def on_server(self, server: Server) -> None:
        self._banner(self.mc.stream_state, self.mc.stream_detail)

    def _banner(self, state: str, detail: str | None) -> None:
        server = self.mc.server
        text = Text()
        if server and server.status != ServerStatus.ONLINE:
            text.append_text(status_text(server.status))
            text.append("  console unavailable until the server is online", style="dim")
        else:
            ic = icons()
            label = {
                "live": (f"{ic.dot_on} live console", "green"),
                "connected": (f"{ic.dot_partial} connected, waiting for console stream", "yellow"),
                "connecting": (f"{ic.dot_off} connecting…", "dim"),
                "reconnecting": (f"{ic.dot_pending} reconnecting…", "yellow"),
                "disconnected": (f"{ic.dot_off} disconnected", "red"),
            }.get(state, (ic.bullet, "dim"))
            text.append(label[0], style=label[1])
            if detail:
                text.append(f"  {sanitize(detail)}", style="dim")
        self.query_one("#console-state", Static).update(text)

    @on(Input.Submitted, "#console-input")
    def _submit(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        widget = self.query_one("#console-input", CommandInput)
        widget.value = ""
        if not command:
            return
        widget.remember(command)
        self.mc.send_command(command)

    def action_clear(self) -> None:
        self.query_one("#console-log", RichLog).clear()

    def prefill(self, command: str) -> None:
        widget = self.query_one("#console-input", CommandInput)
        widget.value = command
        widget.cursor_position = len(command)


class PlayersPage(Page):
    KEY, TITLE = "players", "Players"
    BINDINGS = [
        Binding("f5", "refresh", "Refresh"),
        Binding("left", "switch_list(-1)", "Prev list", show=False),
        Binding("right", "switch_list(1)", "Next list", show=False),
        Binding("a", "add_entry", "Add"),
        Binding("d", "remove_entry", "Remove"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.list_names: list[str] = ["online"]
        self.selected = 0
        self._loaded = False

    def compose(self) -> ComposeResult:
        yield Static("", id="players-summary", classes="page-banner")
        with Horizontal():
            yield OptionList(Option("online", id="online"), id="player-lists")
            table = DataTable(id="player-table", cursor_type="row", zebra_stripes=True)
            yield table
        yield Toolbar("←/→ switch list · a add · d remove · F5 refresh")

    def on_mount(self) -> None:
        self.query_one("#player-table", DataTable).add_columns("#", "Entry")

    def focus_primary(self) -> None:
        self.query_one("#player-table", DataTable).focus()

    def on_show_page(self) -> None:
        if not self._loaded:
            self.action_refresh()
        self._summary()

    def on_server(self, server: Server) -> None:
        self._summary()
        if self.selected == 0:
            self._fill(list(server.players.list))

    def _summary(self) -> None:
        server = self.mc.server
        text = Text()
        if server:
            text.append_text(status_text(server.status))
            text.append(f"   {server.players.count}/{server.players.max} online", style="bold" if server.players.count else "dim")
        self.query_one("#players-summary", Static).update(text)

    @on(OptionList.OptionHighlighted, "#player-lists")
    def _highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self.selected = event.option_index or 0
        self._load_entries()

    def action_switch_list(self, delta: int) -> None:
        if not self.list_names:
            return
        target = (self.selected + delta) % len(self.list_names)
        self.query_one("#player-lists", OptionList).highlighted = target

    @work(exclusive=True, group="players")
    async def action_refresh(self) -> None:
        client = self.mc.client
        if client is None:
            return
        try:
            names = ["online"] + await client.player_lists(self.mc.server_id)
        except Exception as error:
            self.mc.report_error(error)
            return
        self.list_names = names
        options = self.query_one("#player-lists", OptionList)
        options.clear_options()
        options.add_options([Option(name, id=name) for name in names])
        self.selected = min(self.selected, len(names) - 1)
        options.highlighted = self.selected
        self._loaded = True
        self._load_entries()

    @work(exclusive=True, group="player-entries")
    async def _load_entries(self) -> None:
        name = self.list_names[self.selected] if self.list_names else "online"
        if name == "online":
            self._fill(list(self.mc.server.players.list) if self.mc.server else [])
            return
        client = self.mc.client
        if client is None:
            return
        try:
            entries = await client.player_list(self.mc.server_id, name)
        except Exception as error:
            self.mc.report_error(error)
            return
        self._fill(entries)

    def _fill(self, entries: list[str]) -> None:
        table = self.query_one("#player-table", DataTable)
        table.clear()
        for index, entry in enumerate(entries, 1):
            table.add_row(str(index), sanitize(entry), key=entry)
        if not entries:
            table.add_row("", Text("(empty)", style="dim"))

    def _current_list(self) -> str | None:
        name = self.list_names[self.selected] if self.list_names else None
        if name in (None, "online"):
            self.mc.notify("The online list is read-only. Pick whitelist, ops or a ban list.", severity="warning")
            return None
        return name

    @work
    async def action_add_entry(self) -> None:
        name = self._current_list()
        if name is None or self.mc.client is None:
            return
        value = await self.app.push_screen(PromptDialog(f"Add to {name}", "Player name (or IP for banned-ips)"), wait_for_dismiss=True)
        if not value:
            return
        try:
            await self.mc.client.add_to_player_list(self.mc.server_id, name, [value])
        except Exception as error:
            self.mc.report_error(error)
            return
        self.mc.notify(f"Added {value} to {name}.")
        self._load_entries()

    @work
    async def action_remove_entry(self) -> None:
        name = self._current_list()
        table = self.query_one("#player-table", DataTable)
        if name is None or self.mc.client is None or table.row_count == 0 or table.cursor_row is None:
            return
        entry = str(table.get_row_at(table.cursor_row)[1])
        if not entry or entry == "(empty)":
            return
        ok = await self.app.push_screen(ConfirmDialog(f"Remove from {name}?", f"Remove {entry} from the {name} list on the server.", "Remove", danger=True), wait_for_dismiss=True)
        if not ok:
            return
        try:
            await self.mc.client.remove_from_player_list(self.mc.server_id, name, [entry])
        except Exception as error:
            self.mc.report_error(error)
            return
        self.mc.notify(f"Removed {entry} from {name}.")
        self._load_entries()


class ChunkyPage(Page):
    KEY, TITLE = "chunky", "Chunky"
    BINDINGS = [
        Binding("n,enter", "configure", "Configure & start"),
        Binding("g", "progress", "Progress"),
        Binding("p", "pause", "Pause"),
        Binding("u", "resume", "Continue"),
        Binding("x", "cancel", "Cancel task"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._last_config: ChunkyConfiguration | None = None
        self._messages: deque[str] = deque(maxlen=200)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="card-row"):
            yield StatCard("Pregeneration task", CardBody(), id="chunky-card")
            yield StatCard("About", CardBody(), id="chunky-controls")
        with Horizontal(classes="button-row", id="chunky-buttons"):
            yield Button("Configure & start", variant="primary", id="chunky-configure", action="configure")
            yield Button("Progress", id="chunky-progress", action="progress")
            yield Button("Pause", id="chunky-pause", action="pause")
            yield Button("Continue", id="chunky-continue", action="resume")
            yield Button("Cancel", variant="error", id="chunky-cancel", action="cancel")
        yield ProgressBar(total=100, show_eta=False, id="chunky-bar")
        yield RichLog(highlight=False, markup=False, wrap=True, max_lines=200, id="chunky-log")
        yield Toolbar("n configure · g progress · p pause · u continue · x cancel")

    def on_mount(self) -> None:
        self.on_chunky(self.mc.chunky)
        self.query_one("#chunky-controls", StatCard).body.update(Text("Needs the Chunky mod. Commands go through the console and its output is parsed live.", style="dim"))

    def focus_primary(self) -> None:
        self.query_one("#chunky-configure", Button).focus()

    def on_show_page(self) -> None:
        if self.mc.is_online:
            self.mc.send_command(ChunkyCommand.STATUS, quiet=True)

    def on_chunky(self, progress: ChunkyProgress) -> None:
        colors = {"running": "green", "paused": "yellow", "completed": "cyan", "cancelled": "red", "error": "bold red", "idle": "dim"}
        info = KeyValue()
        info.row("Status", Text(progress.lifecycle.upper(), style=colors.get(progress.lifecycle, "")))
        info.row("Dimension", progress.world or "—")
        info.row("Progress", f"{progress.percentage:.2f}%" if progress.percentage is not None else "—")
        info.row("Chunks", f"{progress.processed_chunks:,}" if progress.processed_chunks is not None else "—")
        info.row("Speed", f"{progress.chunks_per_second:.1f} chunks/s" if progress.chunks_per_second is not None else "—")
        info.row("ETA", progress.eta or "—")
        self.query_one("#chunky-card", StatCard).body.update(info)
        self.query_one("#chunky-bar", ProgressBar).update(progress=progress.percentage or 0.0)
        if progress.message and (not self._messages or self._messages[-1] != progress.message):
            self._messages.append(progress.message)
            self.query_one("#chunky-log", RichLog).write(Text(progress.message, style=colors.get(progress.lifecycle, "")))

    @work
    async def action_configure(self) -> None:
        if not self.mc.require_online("Chunky"):
            return
        config = await self.app.push_screen(ChunkyDialog(self._last_config), wait_for_dismiss=True)
        if config is None:
            return
        self._last_config = config
        self.mc.send_command(config.start_command())

    def action_progress(self) -> None:
        if self.mc.require_online("Chunky"):
            self.mc.send_command(ChunkyCommand.STATUS)

    def action_pause(self) -> None:
        if self.mc.require_online("Chunky"):
            self.mc.send_command(ChunkyCommand.pause())

    def action_resume(self) -> None:
        if self.mc.require_online("Chunky"):
            self.mc.send_command(ChunkyCommand.resume())

    @work
    async def action_cancel(self) -> None:
        if not self.mc.require_online("Chunky"):
            return
        ok = await self.app.push_screen(ConfirmDialog("Cancel the Chunky task?", "Saved task progress is deleted. Generated chunks are kept.", "Cancel task", danger=True), wait_for_dismiss=True)
        if ok:
            self.mc.send_command(ChunkyCommand.cancel())


class AdvancementsPage(Page):
    KEY, TITLE = "advancements", "Advancements"
    BINDINGS = [
        Binding("f5", "refresh", "Refresh"),
        Binding("left", "switch_player(-1)", "Prev player", show=False),
        Binding("right", "switch_player(1)", "Next player", show=False),
        Binding("slash", "search", "Search"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="page-toolbar"):
            yield Static("", id="adv-player", classes="page-banner")
            yield Input(placeholder="filter advancement IDs…", id="adv-search")
        with Horizontal():
            yield DataTable(id="adv-table", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="adv-details-scroll"):
                yield Static("", id="adv-details")
        yield Toolbar("←/→ switch player · / search · F5 refresh")

    def on_mount(self) -> None:
        self.query_one("#adv-table", DataTable).add_columns("Advancement", "Progress")
        self._render_player()

    def focus_primary(self) -> None:
        self.query_one("#adv-table", DataTable).focus()

    def on_show_page(self) -> None:
        if not self.mc.adv.summaries and not self.mc.adv.message:
            self.action_refresh()
        else:
            self.refresh_view()

    def action_search(self) -> None:
        self.query_one("#adv-search", Input).focus()

    def action_switch_player(self, delta: int) -> None:
        adv = self.mc.adv
        if not adv.players:
            return
        adv.selected_player = (adv.selected_player + delta) % len(adv.players)
        self.action_refresh()

    @on(Input.Changed, "#adv-search")
    def _filter(self, event: Input.Changed) -> None:
        self.mc.adv.search = event.value.strip().lower()
        self.refresh_view()

    @on(Input.Submitted, "#adv-search")
    def _search_done(self) -> None:
        self.query_one("#adv-table", DataTable).focus()

    @on(DataTable.RowHighlighted, "#adv-table")
    def _row(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value if event.row_key else None
        summary = next((s for s in self.mc.adv.summaries if s.progress.id == key), None)
        self._details(summary)

    def action_refresh(self) -> None:
        self.mc.refresh_advancements()
        self._render_player(loading=True)

    def _render_player(self, loading: bool = False) -> None:
        adv = self.mc.adv
        text = Text()
        if adv.players:
            player = adv.players[adv.selected_player]
            text.append("Player ", style="dim")
            text.append(player.label, style="bold")
            if player.display_name:
                text.append(f"  {player.uuid}", style="dim")
            text.append(f"   ({adv.selected_player + 1}/{len(adv.players)})", style="dim")
        else:
            text.append("No player advancement files discovered yet.", style="dim")
        if loading:
            text.append("   loading…", style="yellow")
        self.query_one("#adv-player", Static).update(text)

    def refresh_view(self) -> None:
        adv = self.mc.adv
        self._render_player()
        table = self.query_one("#adv-table", DataTable)
        table.clear()
        if adv.message:
            self._details(None)
            self.query_one("#adv-details", Static).update(Text(adv.message, style="red"))
            return
        completed = sum(1 for s in adv.summaries if s.progress.done)
        table.border_title = f"{completed}/{len(adv.summaries)} completed"
        for summary in adv.filtered:
            style = "green" if summary.progress.done else ""
            table.add_row(Text(summary.progress.id, style=style), Text(summary.progress_label, style=style), key=summary.progress.id)
        if table.row_count:
            table.move_cursor(row=0)
        else:
            self._details(None)

    def _details(self, summary: AdvancementSummary | None) -> None:
        widget = self.query_one("#adv-details", Static)
        if summary is None:
            widget.update(Text("Select an advancement to inspect it.", style="dim"))
            return
        text = Text()
        text.append(summary.progress.id + "\n", style="bold")
        text.append("COMPLETED\n" if summary.progress.done else "INCOMPLETE\n", style="green" if summary.progress.done else "yellow")
        text.append(f"Completed criteria: {summary.completed_count}\n")
        text.append(f"Required criteria:  {summary.required_count if summary.required_count is not None else 'definition unavailable'}\n")
        missing = summary.missing
        if missing is not None:
            text.append("\nMissing\n", style="bold red" if missing else "bold green")
            for item in sorted(missing):
                text.append(f"  · {item}\n")
            if not missing:
                text.append("  nothing\n", style="dim")
        else:
            text.append("\nNo definition readable for this advancement; only completed criteria are known.\n", style="dim")
        text.append("\nCompleted\n", style="bold")
        for criterion in summary.progress.criteria:
            text.append(f"  {icons().ok} {criterion.id}", style="green")
            text.append(f"  {criterion.completed_at or ''}\n", style="dim")
        widget.update(text)


class ExplorationPage(Page):
    KEY, TITLE = "exploration", "Exploration"
    BINDINGS = [
        Binding("f5", "refresh", "Refresh"),
        Binding("l,enter", "locate", "Locate"),
        Binding("w", "save", "Save waypoint"),
        Binding("ctrl+s", "save", "Save waypoint", show=False, priority=True),
        Binding("left", "switch_player(-1)", "Prev player", show=False),
        Binding("right", "switch_player(1)", "Next player", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Static("", id="exp-summary", classes="page-banner")
        yield ProgressBar(total=100, show_eta=False, id="exp-bar")
        with Horizontal():
            yield OptionList(id="exp-missing")
            yield DataTable(id="exp-results", cursor_type="row", zebra_stripes=True)
        yield Toolbar("l locate selected biome · w save latest result as waypoint · ←/→ player · F5 refresh")

    def on_mount(self) -> None:
        self.query_one("#exp-results", DataTable).add_columns("Biome", "X", "Y", "Z", "Distance")
        self.refresh_view()

    def focus_primary(self) -> None:
        self.query_one("#exp-missing", OptionList).focus()

    def on_show_page(self) -> None:
        if not self.mc.adv.summaries and not self.mc.adv.message:
            self.mc.refresh_advancements()
        self.refresh_view()

    def action_refresh(self) -> None:
        self.mc.refresh_advancements()

    def action_switch_player(self, delta: int) -> None:
        adv = self.mc.adv
        if adv.players:
            adv.selected_player = (adv.selected_player + delta) % len(adv.players)
            self.mc.refresh_advancements()

    def refresh_view(self) -> None:
        adv = self.mc.adv
        summary = adv.adventuring_time
        text = Text()
        bar = self.query_one("#exp-bar", ProgressBar)
        options = self.query_one("#exp-missing", OptionList)
        options.clear_options()
        if summary is None:
            text.append(adv.message or "No Adventuring Time progress. Press F5 once advancement files are readable.", style="dim")
            bar.update(progress=0)
        else:
            player = adv.players[adv.selected_player].label if adv.players else "?"
            text.append("Adventuring Time ", style="bold")
            text.append(f"for {player}  ", style="dim")
            text.append(f"{summary.completed_count} / {summary.required_count if summary.required_count is not None else '?'} biomes")
            if summary.progress.done:
                text.append(f"   {icons().ok} completed", style="green")
            bar.update(progress=summary.percentage or 0)
            for biome in sorted(summary.missing or ()):
                options.add_option(Option(biome, id=biome))
            if summary.missing is None:
                version = self.mc.server.software.version if self.mc.server and self.mc.server.software else "unknown"
                text.append(f"   exact biome list unknown for Minecraft {version}", style="yellow")
                options.add_option(Option(Text(
                    f"No biome list for Minecraft {version}, and none readable from the server's\n"
                    f"datapacks. The {summary.completed_count} completed criteria are on the Advancements page.",
                    style="dim"), disabled=True))
            elif not summary.missing:
                options.add_option(Option(Text("All biomes visited!", style="green"), disabled=True))
            if options.option_count and options.highlighted is None:
                options.highlighted = 0
        self.query_one("#exp-summary", Static).update(text)
        self._render_results()

    def _render_results(self) -> None:
        table = self.query_one("#exp-results", DataTable)
        table.clear()
        for result in [r for r in self.mc.locate_results if r.kind == "biome"][:50]:
            table.add_row(result.target_id, str(result.x), "~" if result.y is None else str(result.y), str(result.z), f"{result.distance:,}" if result.distance is not None else "—")

    def on_locate(self, result: LocateResult) -> None:
        self._render_results()

    def action_locate(self) -> None:
        options = self.query_one("#exp-missing", OptionList)
        if options.highlighted is None or options.option_count == 0:
            self.mc.notify("No missing biome selected.", severity="warning")
            return
        option = options.get_option_at_index(options.highlighted)
        if option.id:
            self.mc.request_locate("biome", option.id)

    @on(OptionList.OptionSelected, "#exp-missing")
    def _selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.mc.request_locate("biome", event.option.id)

    def action_save(self) -> None:
        self.mc.save_locate_as_waypoint("biome")


class StructuresPage(Page):
    KEY, TITLE = "structures", "Structures"
    BINDINGS = [
        Binding("ctrl+s", "save", "Save waypoint", priority=True),
        Binding("w", "save", "Save waypoint", show=False),
        Binding("slash", "focus_input", "Locate", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Static(Text("Enter a namespaced structure ID and press Enter to run /locate structure on the server.", style="dim"), classes="page-banner")
        yield Input(placeholder="minecraft:ancient_city  ·  nova_structures:lone_citadel", id="structure-input")
        yield DataTable(id="structure-results", cursor_type="row", zebra_stripes=True)
        yield Toolbar("Enter locate · Ctrl+S save latest result as waypoint")

    def on_mount(self) -> None:
        self.query_one("#structure-results", DataTable).add_columns("Structure", "X", "Y", "Z", "Distance")
        self.refresh_view()

    def focus_primary(self) -> None:
        self.query_one("#structure-input", Input).focus()

    def action_focus_input(self) -> None:
        self.focus_primary()

    @on(Input.Submitted, "#structure-input")
    def _submit(self, event: Input.Submitted) -> None:
        target = event.value.strip()
        if target:
            self.mc.request_locate("structure", target)

    def refresh_view(self) -> None:
        table = self.query_one("#structure-results", DataTable)
        table.clear()
        for result in [r for r in self.mc.locate_results if r.kind == "structure"][:50]:
            table.add_row(result.target_id, str(result.x), "~" if result.y is None else str(result.y), str(result.z), f"{result.distance:,}" if result.distance is not None else "—")

    def on_locate(self, result: LocateResult) -> None:
        self.refresh_view()

    def action_save(self) -> None:
        self.mc.save_locate_as_waypoint("structure")


class WaypointsPage(Page):
    KEY, TITLE = "waypoints", "Waypoints"
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("e", "rename", "Rename"),
        Binding("d", "delete", "Delete"),
        Binding("t", "teleport", "Copy /tp"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(Text("Waypoints are local to this computer and never touch the server.", style="dim"), classes="page-banner")
        yield DataTable(id="wp-table", cursor_type="row", zebra_stripes=True)
        yield Toolbar("a add · e rename · d delete · t copy /tp command into the console")

    def on_mount(self) -> None:
        self.query_one("#wp-table", DataTable).add_columns("Name", "Dimension", "X", "Y", "Z", "Source", "Target")
        self.on_waypoints()

    def focus_primary(self) -> None:
        self.query_one("#wp-table", DataTable).focus()

    def on_waypoints(self) -> None:
        table = self.query_one("#wp-table", DataTable)
        table.clear()
        waypoints = self.mc.waypoints.all()
        for wp in waypoints:
            table.add_row(wp.name, wp.dimension, str(wp.x), "~" if wp.y is None else str(wp.y), str(wp.z), wp.source or "manual", wp.target_id or "", key=wp.id)
        table.border_title = f"{len(waypoints)} saved" if waypoints else "no waypoints yet"
        table.border_subtitle = "" if waypoints else "press a to add one, or save a locate result from Exploration"

    def _selected(self) -> Waypoint | None:
        table = self.query_one("#wp-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return None
        key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        return self.mc.waypoints.get(key) if key else None

    @work
    async def action_add(self) -> None:
        waypoint = await self.app.push_screen(WaypointDialog(), wait_for_dismiss=True)
        if waypoint:
            self.mc.waypoints.add(waypoint)
            self.mc.broadcast("on_waypoints")
            self.mc.refresh_sidebar()

    @work
    async def action_rename(self) -> None:
        waypoint = self._selected()
        if waypoint is None:
            return
        name = await self.app.push_screen(PromptDialog("Rename waypoint", initial=waypoint.name), wait_for_dismiss=True)
        if name and self.mc.waypoints.rename(waypoint.id, name):
            self.mc.broadcast("on_waypoints")

    @work
    async def action_delete(self) -> None:
        waypoint = self._selected()
        if waypoint is None:
            return
        ok = await self.app.push_screen(ConfirmDialog("Delete waypoint?", f"Remove “{waypoint.name}” ({waypoint.coordinates}) from the local list.", "Delete", danger=True), wait_for_dismiss=True)
        if ok and self.mc.waypoints.delete(waypoint.id):
            self.mc.broadcast("on_waypoints")
            self.mc.refresh_sidebar()

    def action_teleport(self) -> None:
        waypoint = self._selected()
        if waypoint is None:
            return
        y = waypoint.y if waypoint.y is not None else "~"
        command = f"tp @p {waypoint.x} {y} {waypoint.z}"
        self.mc.show_page("console")
        self.mc.console_page.prefill(command)
        self.mc.notify("Command ready in the console. Edit the selector, then press Enter.")


class FilesPage(Page):
    KEY, TITLE = "files", "Files"
    BINDINGS = [Binding("f5", "refresh", "Refresh"), Binding("backspace", "parent", "Parent", show=False)]

    def compose(self) -> ComposeResult:
        with Horizontal():
            tree: Tree[FileInfo] = Tree("/", id="file-tree")
            tree.guide_depth = 3
            yield tree
            with Vertical(id="file-preview-pane"):
                yield Static(Text("Select a readable text file to preview it (first 64 KiB).", style="dim"), id="file-preview-title", classes="page-banner")
                yield RichLog(highlight=False, markup=False, wrap=True, id="file-preview")
        yield Toolbar("Enter open · Backspace parent · F5 refresh (read-only)")

    def on_mount(self) -> None:
        self._loaded: set[str] = set()

    def focus_primary(self) -> None:
        self.query_one("#file-tree", Tree).focus()

    def on_show_page(self) -> None:
        tree = self.query_one("#file-tree", Tree)
        if not tree.root.children and "" not in self._loaded:
            self._load(tree.root, "")

    def action_refresh(self) -> None:
        tree = self.query_one("#file-tree", Tree)
        node = tree.cursor_node or tree.root
        while node.data is not None and not node.data.is_directory and node.parent is not None:
            node = node.parent
        path = node.data.path if node.data else ""
        self._loaded.discard(path)
        self._load(node, path)

    def action_parent(self) -> None:
        tree = self.query_one("#file-tree", Tree)
        node = tree.cursor_node
        if node is not None and node.parent is not None:
            tree.select_node(node.parent)
            node.parent.collapse()

    @on(Tree.NodeExpanded, "#file-tree")
    def _expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        path = node.data.path if node.data else ""
        if path not in self._loaded:
            self._load(node, path)

    @on(Tree.NodeSelected, "#file-tree")
    def _selected(self, event: Tree.NodeSelected) -> None:
        info = event.node.data
        if info is None or info.is_directory:
            return
        if not info.is_readable or not info.is_text_file:
            self.mc.notify("exaroton will not serve this file as readable text.", severity="warning")
            return
        self._preview(info)

    @work(group="files")
    async def _load(self, node: TreeNode, path: str) -> None:
        client = self.mc.client
        if client is None:
            return
        try:
            info = await client.file_info(self.mc.server_id, path)
        except Exception as error:
            self.mc.report_error(error)
            return
        self._loaded.add(path)
        node.remove_children()
        for child in info.sorted_children:
            label = Text(child.name + ("/" if child.is_directory else ""))
            if child.is_directory:
                node.add(label, data=child, allow_expand=True)
            else:
                label.append(f"  {format_bytes(child.size)}", style="dim")
                if not child.is_readable:
                    label.stylize("dim")
                node.add_leaf(label, data=child)
        node.expand()

    @work(exclusive=True, group="file-preview")
    async def _preview(self, info: FileInfo) -> None:
        client = self.mc.client
        if client is None:
            return
        log = self.query_one("#file-preview", RichLog)
        self.query_one("#file-preview-title", Static).update(Text(f"/{info.path}  ·  {format_bytes(info.size)}  ·  loading…", style="dim"))
        try:
            data = await client.file_data(self.mc.server_id, info.path)
        except Exception as error:
            self.mc.report_error(error)
            return
        log.clear()
        text = data[:PREVIEW_LIMIT].decode("utf-8", "replace")
        for line in text.splitlines():
            log.write(to_rich(line))
        if len(data) > PREVIEW_LIMIT:
            log.write(Text(f"… preview truncated at {PREVIEW_LIMIT:,} bytes …", style="yellow"))
        self.query_one("#file-preview-title", Static).update(Text(f"/{info.path}  ·  {format_bytes(info.size)}", style="bold"))


class LogsPage(Page):
    KEY, TITLE = "logs", "Logs"
    BINDINGS = [Binding("f5", "refresh", "Refresh"), Binding("u", "share", "Share to mclo.gs")]

    def compose(self) -> ComposeResult:
        yield Static("", id="logs-banner", classes="page-banner")
        yield RichLog(highlight=False, markup=False, wrap=True, id="logs-log")
        yield Toolbar("F5 refresh snapshot · u upload to mclo.gs (external share)")

    def focus_primary(self) -> None:
        self.query_one("#logs-log", RichLog).focus()

    def on_show_page(self) -> None:
        if not getattr(self, "_loaded", False):
            self.action_refresh()

    @work(exclusive=True, group="logs")
    async def action_refresh(self) -> None:
        client = self.mc.client
        if client is None:
            return
        banner = self.query_one("#logs-banner", Static)
        banner.update(Text("Loading current log…", style="yellow"))
        try:
            content = await client.log(self.mc.server_id)
        except Exception as error:
            self.mc.report_error(error)
            banner.update(Text(f"Failed: {error}", style="red"))
            return
        log = self.query_one("#logs-log", RichLog)
        log.clear()
        lines = (content or "").splitlines()
        for line in lines:
            log.write(to_rich(line))
        self._loaded = True
        banner.update(Text(f"Current server log snapshot · {len(lines):,} lines", style="dim"))

    @work
    async def action_share(self) -> None:
        client = self.mc.client
        if client is None:
            return
        ok = await self.app.push_screen(ConfirmDialog("Upload the log to mclo.gs?", "This publishes the current log publicly.", "Upload"), wait_for_dismiss=True)
        if not ok:
            return
        try:
            url = await client.share_log(self.mc.server_id)
        except Exception as error:
            self.mc.report_error(error)
            return
        try:
            self.app.copy_to_clipboard(url)
        except Exception:
            pass
        self.mc.notify(f"Log shared: {url} (copied to clipboard)", timeout=15)


PAGE_CLASSES: list[type[Page]] = [OverviewPage, ConsolePage, PlayersPage, ChunkyPage, AdvancementsPage, ExplorationPage, StructuresPage, WaypointsPage, FilesPage, LogsPage]
