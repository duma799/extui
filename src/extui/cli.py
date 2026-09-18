from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from typing import Any

from rich.console import Console

from extui import __version__
from extui.api.client import ExarotonClient, perform_and_follow
from extui.api.models import Server, ServerStatus
from extui.api.text import motd_to_rich, to_rich
from extui.config import Configuration, ConfigurationStore
from extui.credentials import CredentialStore
from extui.minecraft.advancements import ADVENTURING_TIME_ID, AdvancementSource, build_summaries
from extui.minecraft.chunky import ChunkyCommand, ChunkyConfiguration
from extui.minecraft.locate import locate_command
from extui.minecraft.waypoints import Waypoint, WaypointStore

console = Console()
err = Console(stderr=True, style="red")


def row(text: str) -> None:
    console.print(text, highlight=False, soft_wrap=True)


class CLIError(RuntimeError):
    pass


def _client(credentials: CredentialStore) -> ExarotonClient:
    token = credentials.read_token()
    if not token:
        raise CLIError("No API token found. Run 'extui login' or set EXAROTON_TOKEN.")
    return ExarotonClient(token)


def _server_id(config: Configuration) -> str:
    if not config.selected_server_id:
        raise CLIError("No server selected. Run 'extui servers', then 'extui select <server-id>'.")
    return config.selected_server_id


def _status_markup(status: ServerStatus) -> str:
    color = {ServerStatus.ONLINE: "green", ServerStatus.OFFLINE: "red", ServerStatus.CRASHED: "bold red"}.get(status, "yellow")
    return f"[{color}]{status.label}[/]"


async def cmd_servers(client: ExarotonClient, _: argparse.Namespace, __: Configuration) -> None:
    servers = await client.servers()
    if not servers:
        console.print("No servers available.")
    for server in servers:
        row(f"{server.id}\t{_status_markup(server.status)}\t{server.name}\t{server.address}")


async def cmd_select(client: ExarotonClient, args: argparse.Namespace, config: Configuration) -> None:
    server = await client.server(args.server_id)
    config.selected_server_id = server.id
    ConfigurationStore().save(config)
    console.print(f"Selected {server.name} ({server.id}).")


async def cmd_status(client: ExarotonClient, _: argparse.Namespace, config: Configuration) -> None:
    server = await client.server(_server_id(config))
    console.print(f"[bold]{server.name}[/] — {_status_markup(server.status)}", highlight=False)
    console.print(f"Address:  {server.address}")
    console.print(f"Players:  {server.players.count}/{server.players.max}" + (f"  ({', '.join(server.players.list)})" if server.players.list else ""))
    console.print(f"Software: {server.software_label}")
    if server.motd:
        console.print("MOTD:     ", end="")
        console.print(motd_to_rich(server.motd))


async def cmd_balance(client: ExarotonClient, _: argparse.Namespace, __: Configuration) -> None:
    account = await client.account()
    console.print(f"Credits: [gold1]{account.credits:,.2f}[/]  ({account.name})")


async def cmd_lifecycle(client: ExarotonClient, args: argparse.Namespace, config: Configuration) -> None:
    trail: list[str] = []

    async def observe(server: Server, _: float) -> None:
        trail.append(server.status.label)
        console.print(" → ".join(trail), highlight=False)

    final = await perform_and_follow(client, args.command, _server_id(config), on_observation=observe)
    if final.status == ServerStatus.CRASHED:
        raise CLIError("The server entered CRASHED while waiting for the action to finish.")


async def cmd_console(client: ExarotonClient, args: argparse.Namespace, config: Configuration) -> None:
    server_id = _server_id(config)
    if args.command_words:
        await client.send_command(server_id, " ".join(args.command_words))
        console.print("Command sent.")
        return
    server = await client.server(server_id)
    if server.status != ServerStatus.ONLINE:
        raise CLIError(f"Console unavailable while server is {server.status.label}.")
    console.print(f"Connected to [bold]{server.name}[/]. Type commands; Ctrl-D exits.")
    stream = client.stream(server_id, tail=100, initial_status=server.status)

    async def reader() -> None:
        from extui.api.models import ConnectionEvent, ConsoleEvent

        async for event in stream:
            if isinstance(event, ConsoleEvent):
                console.print(to_rich(event.line.raw))
            elif isinstance(event, ConnectionEvent) and event.state in ("reconnecting", "disconnected"):
                console.print(f"[dim][extui] {event.state}{': ' + event.detail if event.detail else ''}[/]")

    task = asyncio.create_task(reader())
    loop = asyncio.get_running_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            command = line.strip()
            if command:
                await client.send_command(server_id, command)
    finally:
        stream.close()
        task.cancel()


async def cmd_chunky(client: ExarotonClient, args: argparse.Namespace, config: Configuration) -> None:
    server_id = _server_id(config)
    if args.action == "start":
        conf = ChunkyConfiguration(args.dimension, args.center_x, args.center_z, args.radius).validated()
        console.print(f"Dimension: {conf.dimension}; center: {conf.center_x}, {conf.center_z}; radius: {conf.radius}")
        console.print(f"Estimated square chunks: {conf.estimated_square_chunks:,}. This may use a lot of server storage.")
        await client.send_command(server_id, conf.start_command())
    else:
        command = {"status": ChunkyCommand.STATUS, "pause": ChunkyCommand.pause(), "resume": ChunkyCommand.resume(), "cancel": ChunkyCommand.cancel()}[args.action]
        await client.send_command(server_id, command)
    console.print(f"Chunky {args.action} requested. Watch it with 'extui console'.")


async def cmd_advancements(client: ExarotonClient, args: argparse.Namespace, config: Configuration) -> None:
    server_id = _server_id(config)
    source = AdvancementSource(client, server_id, config.player_aliases)
    discovery = await source.discover()
    player = next((p for p in discovery.players if args.player in (p.uuid, p.display_name)), None) if args.player else discovery.players[0]
    if player is None:
        raise CLIError("Player not found in the advancement files.")
    document = await source.progress(player.uuid, discovery.world_path)
    server = await client.server(server_id)
    definitions = {}
    if definition := await source.definition(ADVENTURING_TIME_ID, discovery.world_path):
        definitions[definition.id] = definition
    summaries = build_summaries(document, server.software.version if server.software else None, definitions)
    if args.command == "biomes":
        summary = next((s for s in summaries if s.progress.id == ADVENTURING_TIME_ID), None)
        if summary is None:
            raise CLIError("No Adventuring Time progress found for this player.")
        if summary.missing is None:
            raise CLIError(f"Adventuring Time definition unavailable for version {server.software.version if server.software else 'unknown'}.")
        console.print(f"Adventuring Time: {summary.completed_count}/{summary.required_count}")
        for biome in sorted(summary.missing):
            console.print(biome)
        return
    console.print(f"Player: {player.label}")
    for summary in summaries:
        mark = "[green]✓[/]" if summary.progress.done else "[dim]·[/]"
        row(f"{mark} {summary.progress.id} ({summary.completed_count} criteria)")


async def cmd_locate(client: ExarotonClient, args: argparse.Namespace, config: Configuration) -> None:
    await client.send_command(_server_id(config), locate_command(args.kind, args.target))
    console.print("Locate requested. Open the TUI or console to receive the server result.")


def cmd_waypoint(args: argparse.Namespace) -> None:
    store = WaypointStore()
    if args.action == "list":
        for wp in store.all(dimension=args.dimension, source=args.type):
            row(f"{wp.id}\t{wp.name}\t{wp.dimension}\t{wp.coordinates}")
    elif args.action == "add":
        y = None if args.y in ("~", None) else int(args.y)
        store.add(Waypoint(args.name, args.dimension, args.x, args.z, y))
        console.print("Waypoint added.")
    elif args.action == "rename":
        console.print("Renamed." if store.rename(args.id, args.name) else "Waypoint not found.")
    elif args.action == "delete":
        console.print("Deleted." if store.delete(args.id) else "Waypoint not found.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="extui", description="Terminal control center for Minecraft servers on exaroton. Run without a command to open the TUI.")
    parser.add_argument("--version", action="version", version=f"extui {__version__}")
    parser.add_argument("--demo", action="store_true", help="open the TUI against a built-in fake server (no token needed)")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("login", help="store an exaroton API token in the system keychain")
    sub.add_parser("logout", help="remove the stored API token")
    sub.add_parser("servers", help="list accessible servers")
    sub.add_parser("select", help="select the default server").add_argument("server_id")
    sub.add_parser("status", help="show selected server status")
    sub.add_parser("balance", help="show current account credits")
    for name in ("start", "stop", "restart"):
        sub.add_parser(name, help=f"{name} the selected server and follow its state")
    sub.add_parser("console", help="send a command, or open console-only mode").add_argument("command_words", nargs="*")
    chunky = sub.add_parser("chunky", help="control Chunky pregeneration")
    chunky_sub = chunky.add_subparsers(dest="action", required=True)
    for name in ("status", "pause", "resume", "cancel"):
        chunky_sub.add_parser(name)
    start = chunky_sub.add_parser("start")
    start.add_argument("--dimension", default="world")
    start.add_argument("--center-x", dest="center_x", type=int, required=True)
    start.add_argument("--center-z", dest="center_z", type=int, required=True)
    start.add_argument("--radius", type=int, required=True)
    for name in ("advancements", "biomes"):
        sub.add_parser(name, help="file-backed advancement progress" if name == "advancements" else "missing Adventuring Time biomes").add_argument("--player")
    locate = sub.add_parser("locate", help="locate a biome or structure through the console")
    locate.add_argument("kind", choices=("biome", "structure"))
    locate.add_argument("target")
    waypoint = sub.add_parser("waypoint", help="manage local waypoints")
    wp_sub = waypoint.add_subparsers(dest="action", required=True)
    wp_list = wp_sub.add_parser("list")
    wp_list.add_argument("--dimension")
    wp_list.add_argument("--type", choices=("biome", "structure"))
    wp_add = wp_sub.add_parser("add")
    for name, kind in (("name", str), ("dimension", str), ("x", int), ("y", str), ("z", int)):
        wp_add.add_argument(name, type=kind)
    wp_rename = wp_sub.add_parser("rename")
    wp_rename.add_argument("id")
    wp_rename.add_argument("name")
    wp_sub.add_parser("delete").add_argument("id")
    player = sub.add_parser("player", help="associate a player name with an advancement UUID")
    player_sub = player.add_subparsers(dest="action", required=True)
    assoc = player_sub.add_parser("associate")
    assoc.add_argument("name")
    assoc.add_argument("uuid")
    return parser


ASYNC_COMMANDS: dict[str, Any] = {
    "servers": cmd_servers, "select": cmd_select, "status": cmd_status, "balance": cmd_balance,
    "start": cmd_lifecycle, "stop": cmd_lifecycle, "restart": cmd_lifecycle, "console": cmd_console,
    "chunky": cmd_chunky, "advancements": cmd_advancements, "biomes": cmd_advancements, "locate": cmd_locate,
}


def run_tui(demo: bool) -> int:
    from extui.tui.app import ExtuiApp

    if demo:
        from extui.api.models import ServerStatus
        from extui.fake import FakeExarotonService
        from pathlib import Path
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="extui-demo-"))
        app = ExtuiApp(service=FakeExarotonService(status=ServerStatus.ONLINE), server_id="demo-server", config_store=ConfigurationStore(tmp / "config.json"), waypoint_store=WaypointStore(tmp / "waypoints.json"), demo=True)
    else:
        app = ExtuiApp()
    app.run()
    if app.return_code:
        return app.return_code
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    credentials = CredentialStore()
    store = ConfigurationStore()
    try:
        if args.command is None:
            return run_tui(args.demo)
        if args.command == "login":
            token = getpass.getpass("Paste exaroton API token (input is hidden): ")
            credentials.save_token(token)
            console.print("Token saved in the system keychain.")
            return 0
        if args.command == "logout":
            credentials.delete_token()
            console.print("Logged out.")
            return 0
        if args.command == "waypoint":
            cmd_waypoint(args)
            return 0
        if args.command == "player":
            config = store.load()
            config.player_aliases[args.uuid] = args.name
            store.save(config)
            console.print(f"Associated {args.name} with {args.uuid}.")
            return 0
        config = store.load()

        async def runner() -> None:
            async with _client(credentials) as client:
                await ASYNC_COMMANDS[args.command](client, args, config)

        asyncio.run(runner())
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        err.print(f"extui: {error}")
        return 1
