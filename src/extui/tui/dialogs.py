from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Markdown, OptionList, Static
from textual.widgets.option_list import Option

from extui.api.models import Server, ServerStatus
from extui.minecraft.chunky import ChunkyConfiguration, ChunkyError
from extui.minecraft.waypoints import Waypoint

STATUS_COLORS = {
    ServerStatus.ONLINE: "green",
    ServerStatus.OFFLINE: "red",
    ServerStatus.CRASHED: "bright_red",
}


def status_style(status: ServerStatus | None) -> str:
    if status is None:
        return "dim"
    return STATUS_COLORS.get(status, "yellow")


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape,n", "cancel", "Cancel"),
        Binding("y", "confirm", "Confirm"),
    ]

    def __init__(self, title: str, body: str | Text, confirm_label: str = "Confirm", *, danger: bool = False) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._confirm_label = confirm_label
        self._danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog dialog-confirm"):
            yield Label(self._title, classes="dialog-title")
            yield Static(self._body, classes="dialog-body")
            with Horizontal(classes="dialog-buttons"):
                yield Button(self._confirm_label, variant="error" if self._danger else "primary", id="confirm")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#confirm", Button).focus()

    @on(Button.Pressed, "#confirm")
    def action_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(False)


class PromptDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, label: str = "", *, initial: str = "", placeholder: str = "", password: bool = False) -> None:
        super().__init__()
        self._title = title
        self._label = label
        self._initial = initial
        self._placeholder = placeholder
        self._password = password

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog dialog-prompt"):
            yield Label(self._title, classes="dialog-title")
            if self._label:
                yield Static(self._label, classes="dialog-body")
            yield Input(value=self._initial, placeholder=self._placeholder, password=self._password, id="value")
            with Horizontal(classes="dialog-buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def action_ok(self) -> None:
        self.dismiss(self.query_one("#value", Input).value.strip())

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class ChunkyDialog(ModalScreen[ChunkyConfiguration | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, initial: ChunkyConfiguration | None = None) -> None:
        super().__init__()
        self._initial = initial or ChunkyConfiguration()

    def compose(self) -> ComposeResult:
        c = self._initial
        with Vertical(classes="dialog dialog-chunky"):
            yield Label("Configure Chunky pregeneration", classes="dialog-title")
            with Grid(classes="form-grid"):
                yield Label("Dimension")
                yield Input(value=c.dimension, placeholder="world / minecraft:the_nether", id="dimension")
                yield Label("Center X")
                yield Input(value=str(c.center_x), type="integer", id="center_x")
                yield Label("Center Z")
                yield Input(value=str(c.center_z), type="integer", id="center_z")
                yield Label("Radius (blocks)")
                yield Input(value=str(c.radius), type="integer", id="radius")
            yield Static("", id="estimate", classes="dialog-body")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Start pregeneration", variant="primary", id="start")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#dimension", Input).focus()
        self._update_estimate()

    def _read(self) -> ChunkyConfiguration:
        def integer(widget_id: str) -> int:
            raw = self.query_one(f"#{widget_id}", Input).value.strip()
            try:
                return int(raw)
            except ValueError as error:
                raise ChunkyError(f"{widget_id.replace('_', ' ').title()} must be a whole number.") from error

        return ChunkyConfiguration(
            dimension=self.query_one("#dimension", Input).value.strip(),
            center_x=integer("center_x"),
            center_z=integer("center_z"),
            radius=integer("radius"),
        )

    @on(Input.Changed)
    def _update_estimate(self) -> None:
        estimate = self.query_one("#estimate", Static)
        try:
            config = self._read().validated()
        except ChunkyError as error:
            estimate.update(Text(str(error), style="red"))
            return
        text = Text()
        text.append(f"Command: {config.start_command()}\n", style="dim")
        text.append(f"Estimated square chunks: {config.estimated_square_chunks:,}\n")
        if config.is_large_job:
            text.append("Large job. This may use a lot of exaroton storage.", style="bold yellow")
        else:
            text.append("Estimate is geometric, not disk usage.", style="dim")
        estimate.update(text)

    @on(Input.Submitted)
    @on(Button.Pressed, "#start")
    def action_start(self) -> None:
        try:
            self.dismiss(self._read().validated())
        except ChunkyError as error:
            self.app.notify(str(error), severity="error")

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class WaypointDialog(ModalScreen[Waypoint | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str = "New waypoint", *, name: str = "", dimension: str = "overworld", x: int | None = None, y: int | None = None, z: int | None = None, source: str | None = None, target_id: str | None = None) -> None:
        super().__init__()
        self._title = title
        self._fields = dict(name=name, dimension=dimension, x=x, y=y, z=z)
        self._source = source
        self._target_id = target_id

    def compose(self) -> ComposeResult:
        f = self._fields
        with Vertical(classes="dialog dialog-waypoint"):
            yield Label(self._title, classes="dialog-title")
            with Grid(classes="form-grid"):
                yield Label("Name")
                yield Input(value=f["name"], placeholder="Ice Spikes", id="name")
                yield Label("Dimension")
                yield Input(value=f["dimension"], placeholder="overworld", id="dimension")
                yield Label("X")
                yield Input(value="" if f["x"] is None else str(f["x"]), type="integer", id="x")
                yield Label("Y (optional)")
                yield Input(value="" if f["y"] is None else str(f["y"]), type="integer", id="y")
                yield Label("Z")
                yield Input(value="" if f["z"] is None else str(f["z"]), type="integer", id="z")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        dimension = self.query_one("#dimension", Input).value.strip() or "overworld"
        try:
            x = int(self.query_one("#x", Input).value.strip())
            z = int(self.query_one("#z", Input).value.strip())
            y_raw = self.query_one("#y", Input).value.strip()
            y = int(y_raw) if y_raw else None
        except ValueError:
            self.app.notify("X and Z must be whole numbers.", severity="error")
            return
        if not name:
            self.app.notify("Name cannot be empty.", severity="error")
            return
        self.dismiss(Waypoint(name=name, dimension=dimension, x=x, z=z, y=y, source=self._source, target_id=self._target_id))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class ServerPickerDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, servers: list[Server], *, allow_cancel: bool = True) -> None:
        super().__init__()
        self._servers = servers
        self._allow_cancel = allow_cancel

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog dialog-picker"):
            yield Label("Select a server", classes="dialog-title")
            options = []
            for server in self._servers:
                prompt = Text()
                prompt.append(f"{server.name}\n", style="bold")
                prompt.append(f"  {server.address}  ", style="dim")
                prompt.append(server.status.label, style=status_style(server.status))
                prompt.append(f"  {server.players.count}/{server.players.max} players", style="dim")
                options.append(Option(prompt, id=server.id))
            yield OptionList(*options, id="servers")
            if self._allow_cancel:
                with Horizontal(classes="dialog-buttons"):
                    yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        options = self.query_one("#servers", OptionList)
        if options.option_count:
            options.highlighted = 0
        options.focus()

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        if self._allow_cancel:
            self.dismiss(None)


HELP_MARKDOWN = """
## Global
| Key | Action |
|---|---|
| `1`‥`9`, `0` | Jump to a page |
| `↑`/`↓`, `j`/`k` in sidebar | Move between pages |
| `Enter` | Focus the page content |
| `Esc` | Back to the sidebar / dismiss |
| `Tab` / `Shift+Tab` | Cycle focus |
| `s` | Start an offline server / stop an online one |
| `r` | Restart an online server |
| `c` | Jump to the console |
| `F5` | Refresh the current page |
| `?` | This help |
| `Ctrl+P` | Command palette (themes, screenshots…) |
| `q` / `Ctrl+C` | Quit |

## Console
`Enter` sends, `↑`/`↓` browse history, `Esc` back to sidebar, `PgUp`/`PgDn` scroll.

## Players
`←`/`→` switch lists · `a` add entry · `d` remove entry · `F5` refresh.

## Chunky
`n` configure & start · `g` progress · `p` pause · `u` continue · `x` cancel.

## Advancements / Exploration / Structures
`←`/`→` switch player · `/` search · `l` or `Enter` locate · `w` save latest locate as waypoint.

## Waypoints
`a` add · `e` rename · `d` delete · `t` copy `/tp` command into the console.

## Files / Logs
`Enter` open · `Backspace` parent · `F5` refresh · `u` (Logs) share to mclo.gs.
"""


class HelpDialog(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,q", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog dialog-help"):
            yield Label("extui key bindings", classes="dialog-title")
            with VerticalScroll():
                yield Markdown(HELP_MARKDOWN)
            with Horizontal(classes="dialog-buttons"):
                yield Button("Close", variant="primary", id="close")

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        self.dismiss(None)
