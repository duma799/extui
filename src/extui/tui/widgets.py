from __future__ import annotations

from collections import deque
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Input, Static

from extui.api.models import Server, ServerStatus

from .dialogs import status_style
from .icons import icons


def format_bytes(value: float) -> str:
    if value < 1024:
        return f"{value:.0f} B"
    if value < 1024**2:
        return f"{value / 1024:.1f} KB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} MB"
    return f"{value / 1024**3:.2f} GB"


def status_text(status: ServerStatus | None, *, dot: bool = True) -> Text:
    label = status.label if status else "UNKNOWN"
    text = Text()
    if dot:
        marker = icons().dot_on if status is ServerStatus.ONLINE else icons().dot_off
        text.append(f"{marker} ", style=status_style(status))
    text.append(label, style=f"bold {status_style(status)}")
    return text


class HeaderBar(Static):
    DEFAULT_CSS = """
    HeaderBar { height: 1; padding: 0 1; background: $panel; color: $foreground; }
    """

    def __init__(self) -> None:
        super().__init__("")
        self.server: Server | None = None
        self.credits: float | None = None
        self.tps: float | None = None
        self.memory_percent: float | None = None
        self.memory_usage: float | None = None
        self.stream_state: str = "connecting"
        self.api_error: str | None = None
        self.active_action: str | None = None

    def refresh_bar(self) -> None:
        ic = icons()
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append(f" {ic.server} extui ", style="bold reverse")
        text.append("  ")
        if self.server:
            text.append(self.server.name, style="bold")
            text.append("  ")
            text.append_text(status_text(self.server.status))
            if self.active_action:
                text.append(f" ({self.active_action})", style="yellow")
            text.append("   ")
            online = self.server.status == ServerStatus.ONLINE
            text.append(f"{ic.player_count} ", style="dim")
            text.append(f"{self.server.players.count}/{self.server.players.max}", style="" if online else "dim")
            if online and self.tps is not None:
                tps_style = "green" if self.tps >= 19 else ("yellow" if self.tps >= 15 else "red")
                text.append(f"   {ic.tps} ", style="dim")
                text.append(f"{self.tps:.1f} TPS", style=tps_style)
            if online and self.memory_percent is not None:
                mem_style = "green" if self.memory_percent < 75 else ("yellow" if self.memory_percent < 90 else "red")
                text.append(f"   {ic.memory} ", style="dim")
                text.append(f"{self.memory_percent:.0f}%", style=mem_style)
                if self.memory_usage:
                    text.append(f" ({format_bytes(self.memory_usage)})", style="dim")
        else:
            text.append("connecting…", style="dim")
        if self.credits is not None:
            text.append(f"   {ic.credits} ", style="dim")
            text.append(f"{self.credits:,.2f}", style="gold1")
        stream_symbol = {
            "live": (f"{ic.stream} live", "green"),
            "connected": (f"{ic.stream} connected", "yellow"),
            "connecting": (f"{ic.stream} connecting", "dim"),
            "reconnecting": (f"{ic.stream} reconnecting", "yellow"),
            "disconnected": (f"{ic.stream} offline", "red"),
        }
        symbol, style = stream_symbol.get(self.stream_state, (f"{ic.stream} ?", "dim"))
        text.append("   ")
        text.append(symbol, style=style)
        if self.api_error:
            text.append(f"   {ic.warning} API error", style="bold red")
        text.append("   ")
        text.append(datetime.now().strftime("%H:%M:%S"), style="dim")
        self.update(text)


class CardBody(Static):
    def __init__(self) -> None:
        super().__init__("", classes="card-body")


class StatCard(Vertical):
    DEFAULT_CSS = """
    StatCard {
        border: round $primary-darken-2;
        border-title-color: $accent;
        border-title-style: bold;
        padding: 0 1;
        height: auto;
        background: $surface;
    }
    StatCard > .card-body { height: auto; }
    """

    def __init__(self, title: str, *children: Widget, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(*children, id=id, classes=classes)
        self.border_title = title

    @property
    def body(self) -> Static:
        return self.query_one(".card-body", Static)


class KeyValue(Text):
    def __init__(self, width: int = 12) -> None:
        super().__init__()
        self._width = width

    def row(self, key: str, value: str | Text, style: str = "") -> "KeyValue":
        if len(self) > 0:
            self.append("\n")
        self.append(f"{key:<{self._width}}", style="dim")
        if isinstance(value, Text):
            self.append_text(value)
        else:
            self.append(value, style=style)
        return self


class CommandInput(Input):
    BINDINGS = [
        Binding("up", "history_previous", "Older", show=False),
        Binding("down", "history_next", "Newer", show=False),
        Binding("escape", "leave", "Sidebar", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(placeholder="Type a server command and press Enter…", **kwargs)
        self.history: deque[str] = deque(maxlen=200)
        self._cursor: int | None = None
        self._draft = ""

    def remember(self, command: str) -> None:
        if not self.history or self.history[-1] != command:
            self.history.append(command)
        self._cursor = None
        self._draft = ""

    def action_history_previous(self) -> None:
        if not self.history:
            return
        if self._cursor is None:
            self._draft = self.value
            self._cursor = len(self.history)
        self._cursor = max(0, self._cursor - 1)
        self.value = self.history[self._cursor]
        self.cursor_position = len(self.value)

    def action_history_next(self) -> None:
        if self._cursor is None:
            return
        self._cursor += 1
        if self._cursor >= len(self.history):
            self._cursor = None
            self.value = self._draft
        else:
            self.value = self.history[self._cursor]
        self.cursor_position = len(self.value)

    def action_leave(self) -> None:
        self.app.action_focus_sidebar()


class Toolbar(Horizontal):
    DEFAULT_CSS = """
    Toolbar { height: 1; color: $text-muted; padding: 0 1; }
    """

    def __init__(self, hint: str) -> None:
        super().__init__()
        self._hint = hint

    def compose(self) -> ComposeResult:
        yield Static(self._hint, markup=False)
