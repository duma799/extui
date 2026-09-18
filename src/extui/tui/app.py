from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.theme import Theme
from textual.widgets import ContentSwitcher, Footer, OptionList
from textual.widgets.option_list import Option

from extui.api.client import ExarotonClient, perform_and_follow
from extui.api.models import (
    ConnectionEvent,
    ConsoleEvent,
    ConsoleLine,
    HeapEvent,
    Server,
    ServerAction,
    ServerStatus,
    StatsEvent,
    StatusEvent,
    TickEvent,
)
from extui.config import Configuration, ConfigurationStore
from extui.credentials import CredentialStore
from extui.minecraft.advancements import ADVENTURING_TIME_ID, AdvancementError, AdvancementPlayer, AdvancementSource, AdvancementSummary, build_summaries
from extui.minecraft.chunky import ChunkyProgress, parse_chunky_line
from extui.minecraft.locate import LocateResult, is_locate_failure, locate_command, parse_locate_line
from extui.minecraft.waypoints import WaypointStore

from .dialogs import ConfirmDialog, HelpDialog, PromptDialog, ServerPickerDialog, WaypointDialog
from .icons import icons, use as use_icons
from .pages import PAGE_CLASSES, ConsolePage, Page
from .widgets import HeaderBar

TOKYO_NIGHT = Theme(
    name="tokyo-night",
    primary="#7aa2f7",
    secondary="#bb9af7",
    accent="#ff9e64",
    warning="#e0af68",
    error="#f7768e",
    success="#9ece6a",
    foreground="#c0caf5",
    background="#1a1b26",
    surface="#1f2335",
    panel="#24283b",
    dark=True,
    variables={
        "footer-key-foreground": "#ff9e64",
        "footer-description-foreground": "#a9b1d6",
        "block-cursor-background": "#7aa2f7",
        "block-cursor-foreground": "#1a1b26",
        "border": "#3b4261",
        "border-blurred": "#292e42",
        "text-muted": "#565f89",
        "scrollbar": "#292e42",
        "scrollbar-hover": "#3b4261",
        "scrollbar-active": "#7aa2f7",
        "input-selection-background": "#33467c",
    },
)

MINECRAFT_THEME = Theme(
    name="minecraft",
    primary="#5cb85c",
    secondary="#8b5a2b",
    accent="#ffaa00",
    warning="#ffd75f",
    error="#ff5555",
    success="#55ff55",
    foreground="#e6e6e6",
    background="#0f1317",
    surface="#161c22",
    panel="#1d252e",
    dark=True,
    variables={"footer-key-foreground": "#ffaa00", "block-cursor-background": "#5cb85c", "block-cursor-foreground": "#0f1317"},
)

DEFAULT_THEME = "tokyo-night"


@dataclass
class AdvancementState:
    world_path: str = ""
    players: list[AdvancementPlayer] = field(default_factory=list)
    selected_player: int = 0
    summaries: list[AdvancementSummary] = field(default_factory=list)
    search: str = ""
    message: str | None = None

    @property
    def filtered(self) -> list[AdvancementSummary]:
        if not self.search:
            return self.summaries
        return [s for s in self.summaries if self.search in s.progress.id.lower()]

    @property
    def adventuring_time(self) -> AdvancementSummary | None:
        return next((s for s in self.summaries if s.progress.id == ADVENTURING_TIME_ID), None)


class Sidebar(OptionList):
    BINDINGS = [Binding("j", "cursor_down", "Down", show=False), Binding("k", "cursor_up", "Up", show=False)]


class ExtuiApp(App[None]):
    TITLE = "extui"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("escape", "focus_sidebar", "Sidebar", show=False),
        Binding("s", "start_stop", "Start/Stop"),
        Binding("r", "restart", "Restart"),
        Binding("c", "show_page('console')", "Console"),
        Binding("ctrl+t", "change_theme", "Theme", show=False),
    ] + [Binding(str((i + 1) % 10), f"show_page('{cls.KEY}')", cls.TITLE, show=False) for i, cls in enumerate(PAGE_CLASSES)]

    def __init__(
        self,
        *,
        service: Any | None = None,
        server_id: str | None = None,
        config_store: ConfigurationStore | None = None,
        credential_store: CredentialStore | None = None,
        waypoint_store: WaypointStore | None = None,
        demo: bool = False,
    ) -> None:
        super().__init__()
        self.demo = demo
        self.config_store = config_store or ConfigurationStore()
        self.config: Configuration = self.config_store.load()
        self.credential_store = credential_store or CredentialStore()
        self.waypoints = waypoint_store or WaypointStore()
        self.client: Any | None = service
        self.server_id: str = server_id or (self.config.selected_server_id or "")
        self.refresh_interval = self.config.refresh_interval_seconds
        self.aliases = dict(self.config.player_aliases)

        self.server: Server | None = None
        self._server_observed = 0.0
        self.credits: float | None = None
        self.ram_gb: float | None = None
        self.tps_history: deque[float] = deque(maxlen=60)
        self.mem_history: deque[float] = deque(maxlen=60)
        self.memory_usage: float | None = None
        self.heap_usage: float | None = None
        self.stream_state = "connecting"
        self.stream_detail: str | None = None
        self.api_error: str | None = None
        self.active_action: str | None = None
        self.console_lines: deque[ConsoleLine] = deque(maxlen=2000)
        self.chunky = ChunkyProgress()
        self.locate_results: list[LocateResult] = []
        self._pending_locate: tuple[str, str] | None = None
        self._pending_locate_since = 0.0
        self.adv = AdvancementState()
        self._stream: Any | None = None
        self._pages: dict[str, Page] = {}
        self._compact = False
        self._console_alerts = 0


    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Horizontal(id="body"):
            options = [Option(self._sidebar_label(cls, i), id=cls.KEY) for i, cls in enumerate(PAGE_CLASSES)]
            yield Sidebar(*options, id="sidebar")
            with ContentSwitcher(initial="overview", id="pages"):
                for cls in PAGE_CLASSES:
                    page = cls(id=cls.KEY)
                    self._pages[cls.KEY] = page
                    yield page
        yield Footer()

    def _sidebar_label(self, cls: type[Page], index: int, compact: bool = False) -> Text:
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append(f"{(index + 1) % 10} ", style="dim")
        text.append(cls.icon())
        if compact:
            marker, style = self._sidebar_badge(cls.KEY)
            if marker:
                text.append(icons().dot_on, style=style)
            return text
        text.append(f" {cls.TITLE}")
        marker, style = self._sidebar_badge(cls.KEY)
        if marker:
            text.append(f"  {marker}", style=style)
        return text

    def _sidebar_badge(self, key: str) -> tuple[str, str]:
        if key == "players" and self.server is not None and self.is_online:
            count = self.server.players.count
            return (str(count), "bold" if count else "dim")
        if key == "chunky" and self.chunky.lifecycle in ("running", "paused"):
            if self.chunky.percentage is not None:
                return (f"{self.chunky.percentage:.0f}%", "green" if self.chunky.lifecycle == "running" else "yellow")
            return (self.chunky.lifecycle[:3], "yellow")
        if key == "console" and self._console_alerts:
            return (str(min(self._console_alerts, 99)), "bold red")
        if key == "waypoints":
            count = len(self.waypoints.all())
            return (str(count), "dim") if count else ("", "")
        return ("", "")

    def refresh_sidebar(self) -> None:
        if not self.is_running or self._exit:
            return
        try:
            sidebar = self.query_one(Sidebar)
        except NoMatches:
            return
        for index, cls in enumerate(PAGE_CLASSES):
            label = self._sidebar_label(cls, index, self._compact)
            if str(sidebar.get_option_at_index(index).prompt) != str(label):
                sidebar.replace_option_prompt_at_index(index, label)

    COMPACT_WIDTH = 100

    def on_resize(self, event: events.Resize) -> None:
        self._set_compact(event.size.width < self.COMPACT_WIDTH)

    def _set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        try:
            sidebar = self.query_one(Sidebar)
        except NoMatches:
            return
        highlighted = sidebar.highlighted
        sidebar.clear_options()
        sidebar.add_options([Option(self._sidebar_label(cls, i, compact), id=cls.KEY)
                             for i, cls in enumerate(PAGE_CLASSES)])
        sidebar.highlighted = highlighted
        sidebar.set_class(compact, "compact")
        self.screen.set_class(compact, "compact-layout")

    def on_mount(self) -> None:
        use_icons(self.config.icons)
        self.register_theme(TOKYO_NIGHT)
        self.register_theme(MINECRAFT_THEME)
        try:
            self.theme = self.config.theme or DEFAULT_THEME
        except Exception:
            self.theme = DEFAULT_THEME
        self.set_interval(1.0, self._tick_header)
        self.query_one(Sidebar).focus()
        self._bootstrap()

    @property
    def console_page(self) -> ConsolePage:
        return self._pages["console"]

    @property
    def current_page(self) -> Page:
        return self._pages[self._visible_page()]

    def _visible_page(self) -> str:
        try:
            return self.query_one("#pages", ContentSwitcher).current or "overview"
        except NoMatches:
            return "overview"

    @property
    def is_online(self) -> bool:
        return self.server is not None and self.server.status == ServerStatus.ONLINE

    @property
    def active_action_label(self) -> str:
        return ServerAction.progress_label(self.active_action) if self.active_action else ""

    def broadcast(self, method: str, *args: Any) -> None:
        if not self.is_running or self._exit:
            return
        for page in self._pages.values():
            try:
                getattr(page, method)(*args)
            except NoMatches:
                pass


    @work(exclusive=True, group="bootstrap")
    async def _bootstrap(self) -> None:
        if self.client is None:
            token = None
            try:
                token = self.credential_store.read_token()
            except Exception as error:
                self.notify(str(error), severity="error", timeout=10)
            while not token:
                token = await self.push_screen(PromptDialog("exaroton API token", "Paste the token from https://exaroton.com/account/", password=True), wait_for_dismiss=True)
                if token is None:
                    self.exit(message="extui needs an exaroton API token.")
                    return
                try:
                    self.credential_store.save_token(token)
                except Exception as error:
                    self.notify(str(error), severity="error", timeout=10)
            self.client = ExarotonClient(token)
        if not self.server_id:
            try:
                servers = await self.client.servers()
            except Exception as error:
                self.exit(message=f"Could not list servers: {error}")
                return
            if not servers:
                self.exit(message="This exaroton account has no servers.")
                return
            chosen = await self.push_screen(ServerPickerDialog(servers, allow_cancel=False), wait_for_dismiss=True)
            if not chosen:
                self.exit()
                return
            self.server_id = chosen
            self.config.selected_server_id = chosen
            self._save_config()
        self._poll_loop()
        self._stream_loop()

    def _save_config(self) -> None:
        try:
            self.config_store.save(self.config)
        except OSError as error:
            self.notify(f"Could not save config: {error}", severity="warning")


    @work(exclusive=True, group="poll")
    async def _poll_loop(self) -> None:
        account_due = 0.0
        ram_loaded = False
        while True:
            observed = time.monotonic()
            try:
                server = await self.client.server(self.server_id)
                self._apply_server(server, observed)
                if self._stream is not None:
                    await self._stream.set_online(server.status == ServerStatus.ONLINE)
                if not ram_loaded or (server.status == ServerStatus.ONLINE and self.ram_gb is None):
                    self.ram_gb = await self.client.ram(self.server_id)
                    ram_loaded = True
                    self.broadcast("on_account")
                if time.monotonic() >= account_due:
                    account = await self.client.account()
                    self.credits = account.credits
                    account_due = time.monotonic() + max(60.0, self.refresh_interval * 3)
                    self.broadcast("on_account")
                self._set_api_error(None)
            except Exception as error:
                self._set_api_error(str(error))
            await asyncio.sleep(self.refresh_interval)

    @work(exclusive=True, group="stream")
    async def _stream_loop(self) -> None:
        stream = self.client.stream(self.server_id, tail=200, initial_status=self.server.status if self.server else None)
        self._stream = stream
        try:
            async for event in stream:
                if isinstance(event, ConnectionEvent):
                    self.stream_state, self.stream_detail = event.state, event.detail
                    self.broadcast("on_stream_state", event.state, event.detail)
                    self._tick_header()
                elif isinstance(event, StatusEvent):
                    self._apply_server(event.server, time.monotonic())
                elif isinstance(event, ConsoleEvent):
                    self._console_line(event.line)
                elif isinstance(event, TickEvent):
                    self.tps_history.append(event.tps)
                    self.broadcast("on_telemetry")
                elif isinstance(event, StatsEvent):
                    self.mem_history.append(event.memory_percent)
                    self.memory_usage = event.memory_usage_bytes
                    self.broadcast("on_telemetry")
                elif isinstance(event, HeapEvent):
                    self.heap_usage = event.usage_bytes
        finally:
            stream.close()

    def _apply_server(self, server: Server, observed_at: float) -> bool:
        if observed_at < self._server_observed:
            return False
        self._server_observed = observed_at
        previous = self.server
        self.server = server
        if previous is None or previous.status != server.status:
            if server.status != ServerStatus.ONLINE:
                self.tps_history.clear()
                self.mem_history.clear()
                self.memory_usage = self.heap_usage = None
                self.chunky = ChunkyProgress()
                self.broadcast("on_chunky", self.chunky)
            self.sub_title = f"{server.name} · {server.status.label}"
        self.broadcast("on_server", server)
        self.refresh_sidebar()
        self._tick_header()
        return True

    def _console_line(self, line: ConsoleLine) -> None:
        self.console_lines.append(line)
        self.broadcast("on_console_line", line)
        if line.level in ("WARN", "ERROR", "FATAL") and self._visible_page() != "console":
            self._console_alerts += 1
            self.refresh_sidebar()
        if parsed := parse_chunky_line(line.raw, self.chunky):
            self.chunky = parsed
            self.broadcast("on_chunky", parsed)
            self.refresh_sidebar()
        if self._pending_locate and time.monotonic() - self._pending_locate_since < 30:
            kind, target = self._pending_locate
            if result := parse_locate_line(line.raw, kind, target):
                self._pending_locate = None
                self.locate_results.insert(0, result)
                del self.locate_results[100:]
                self.broadcast("on_locate", result)
                self.notify(f"{target} located at {result.coordinates}" + (f" ({result.distance:,} blocks away)" if result.distance is not None else ""), title="Locate")
            elif is_locate_failure(line.raw):
                self._pending_locate = None
                self.notify(f"The server could not find {target} nearby.", severity="warning", title="Locate")

    def _set_api_error(self, message: str | None) -> None:
        changed = (message is not None) != (self.api_error is not None)
        self.api_error = message
        if message and changed:
            self.notify(message, title="exaroton API", severity="error", timeout=8)
        if changed:
            self.broadcast("on_account")
        self._tick_header()

    def _tick_header(self) -> None:
        if not self.is_running or self._exit:
            return
        try:
            header = self.query_one(HeaderBar)
        except NoMatches:
            return
        header.server = self.server
        header.credits = self.credits
        header.tps = self.tps_history[-1] if self.tps_history else None
        header.memory_percent = self.mem_history[-1] if self.mem_history else None
        header.memory_usage = self.memory_usage
        header.stream_state = self.stream_state
        header.api_error = self.api_error
        header.active_action = self.active_action_label or None
        header.refresh_bar()


    def report_error(self, error: BaseException | str) -> None:
        self.notify(str(error), severity="error", timeout=8)

    def require_online(self, feature: str) -> bool:
        if self.is_online:
            return True
        status = self.server.status.label if self.server else "UNKNOWN"
        self.notify(f"{feature} requires an online server (currently {status}).", severity="warning")
        return False

    def refresh_now(self) -> None:
        self._poll_loop()

    @work(group="commands")
    async def send_command(self, command: str, *, quiet: bool = False) -> None:
        if self.client is None:
            return
        if not self.is_online:
            if not quiet:
                self.require_online("The console")
            return
        try:
            await self.client.send_command(self.server_id, command)
        except Exception as error:
            self.report_error(error)

    def request_locate(self, kind: str, target: str) -> None:
        if not self.require_online("Locate"):
            return
        try:
            command = locate_command(kind, target)
        except ValueError as error:
            self.report_error(error)
            return
        self._pending_locate = (kind, target)
        self._pending_locate_since = time.monotonic()
        self.send_command(command)
        self.notify(f"Sent {command}; waiting for the server's answer…", timeout=4)

    @work
    async def save_locate_as_waypoint(self, kind: str) -> None:
        result = next((r for r in self.locate_results if r.kind == kind), None)
        if result is None:
            self.notify("No parsed locate result is available yet.", severity="warning")
            return
        name = result.target_id.split(":")[-1].replace("_", " ").title()
        waypoint = await self.push_screen(
            WaypointDialog("Save locate result as waypoint", name=name, dimension="overworld", x=result.x, y=result.y, z=result.z, source=kind, target_id=result.target_id),
            wait_for_dismiss=True,
        )
        if waypoint:
            self.waypoints.add(waypoint)
            self.broadcast("on_waypoints")
            self.refresh_sidebar()
            self.notify(f"Saved waypoint “{waypoint.name}”.")

    @work(exclusive=True, group="advancements")
    async def refresh_advancements(self) -> None:
        if self.client is None:
            return
        source = AdvancementSource(self.client, self.server_id, self.aliases)
        adv = self.adv
        try:
            if not adv.players:
                discovery = await source.discover()
                adv.world_path, adv.players = discovery.world_path, discovery.players
                adv.selected_player = 0
            player = adv.players[adv.selected_player]
            document = await source.progress(player.uuid, adv.world_path)
            definitions = {}
            try:
                definition = await source.definition(ADVENTURING_TIME_ID, adv.world_path)
                if definition:
                    definitions[definition.id] = definition
            except AdvancementError:
                pass
            version = self.server.software.version if self.server and self.server.software else None
            adv.summaries = build_summaries(document, version, definitions)
            adv.message = None
        except Exception as error:
            adv.summaries = []
            adv.message = str(error)
        for key in ("advancements", "exploration"):
            self._pages[key].refresh_view()


    def action_show_page(self, key: str) -> None:
        self.show_page(key)

    def show_page(self, key: str, *, focus: bool = True) -> None:
        switcher = self.query_one("#pages", ContentSwitcher)
        if switcher.current != key:
            switcher.current = key
            self._pages[key].on_show_page()
        if key == "console" and self._console_alerts:
            self._console_alerts = 0
            self.refresh_sidebar()
        sidebar = self.query_one(Sidebar)
        index = next(i for i, cls in enumerate(PAGE_CLASSES) if cls.KEY == key)
        if sidebar.highlighted != index:
            sidebar.highlighted = index
        if focus:
            self._pages[key].focus_primary()

    @on(OptionList.OptionHighlighted, "#sidebar")
    def _sidebar_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self.show_page(event.option.id, focus=False)

    @on(OptionList.OptionSelected, "#sidebar")
    def _sidebar_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.show_page(event.option.id, focus=True)

    def action_focus_sidebar(self) -> None:
        self.query_one(Sidebar).focus()

    def action_help(self) -> None:
        self.push_screen(HelpDialog())

    def watch_theme(self, theme: str) -> None:
        if getattr(self, "config", None) is None or self.config.theme == theme:
            return
        self.config.theme = theme
        self._save_config()

    @work(exclusive=True, group="lifecycle")
    async def action_start_stop(self) -> None:
        if self.server is None or self.client is None:
            return
        if self.active_action:
            self.notify(f"{self.active_action_label} already in progress.", severity="warning")
            return
        status = self.server.status
        if status == ServerStatus.ONLINE:
            action, verb = "stop", "Stop"
        elif status.can_start:
            action, verb = "start", "Start"
        else:
            self.notify(f"Server is {status.label}; wait for it to settle.", severity="warning")
            return
        body = Text()
        body.append(f"{verb} ", style="bold")
        body.append(self.server.name, style="bold")
        body.append(f" ({self.server.address})?")
        if action == "stop" and self.server.players.count:
            body.append(f"\n{self.server.players.count} player(s) are online right now.", style="yellow")
        if not await self.push_screen(ConfirmDialog(f"{verb} server?", body, verb, danger=action == "stop"), wait_for_dismiss=True):
            return
        await self._run_action(action)

    @work(exclusive=True, group="lifecycle")
    async def action_restart(self) -> None:
        if self.server is None or self.client is None:
            return
        if self.active_action:
            self.notify(f"{self.active_action_label} already in progress.", severity="warning")
            return
        if self.server.status != ServerStatus.ONLINE:
            self.notify(f"Cannot restart while the server is {self.server.status.label}.", severity="warning")
            return
        if not await self.push_screen(ConfirmDialog("Restart server?", f"Restart {self.server.name}? Players will be disconnected.", "Restart", danger=True), wait_for_dismiss=True):
            return
        await self._run_action("restart")

    async def _run_action(self, action: str) -> None:
        self.active_action = action
        self.broadcast("on_server", self.server)
        self._tick_header()
        try:
            async def observe(server: Server, observed_at: float) -> None:
                self._apply_server(server, observed_at)

            final = await perform_and_follow(self.client, action, self.server_id, on_observation=observe, use_own_credits=bool(self.server and self.server.shared))
            if final.status == ServerStatus.CRASHED:
                self.notify("The server CRASHED during the action. Check the logs.", severity="error", timeout=10)
            else:
                self.notify(f"Server is now {final.status.label}.", severity="information")
                if action != "stop":
                    self.ram_gb = None
        except Exception as error:
            self.report_error(error)
        finally:
            self.active_action = None
            if self.server:
                self.broadcast("on_server", self.server)
            self._tick_header()

    async def on_unmount(self) -> None:
        if self._stream is not None:
            self._stream.close()
        if self.client is not None and not self.demo:
            try:
                await self.client.aclose()
            except Exception:
                pass
