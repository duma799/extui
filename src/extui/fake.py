from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator

from extui.api.models import (
    Account,
    ConnectionEvent,
    ConsoleEvent,
    ConsoleLine,
    FileInfo,
    HeapEvent,
    Server,
    ServerAction,
    ServerStatus,
    StatsEvent,
    StatusEvent,
    StreamEvent,
    TickEvent,
)

_DEMO_ADVANCEMENTS = {
    "DataVersion": 3953,
    "minecraft:adventure/adventuring_time": {"criteria": {f"minecraft:{b}": "2026-09-10 10:00:00 +0000" for b in ("plains", "desert", "forest", "taiga", "swamp", "jungle", "ocean", "beach", "river", "meadow")}, "done": False},
    "minecraft:story/mine_stone": {"criteria": {"get_stone": "2026-09-01 10:00:00 +0000"}, "done": True},
    "minecraft:story/root": {"criteria": {"crafting_table": "2026-09-01 09:00:00 +0000"}, "done": True},
    "minecraft:nether/root": {"criteria": {"entered_nether": "2026-09-05 10:00:00 +0000"}, "done": True},
    "examplemod:journey/root": {"criteria": {"entered_custom_biome": "2026-09-10 12:00:00 +0000"}, "done": True},
}


def _file(path: str, name: str, *, directory: bool = False, size: int = 0, text: bool = True, readable: bool = True, children: list | None = None) -> dict:
    return {
        "path": path, "name": name, "isTextFile": text and not directory, "isConfigFile": name.endswith(".properties"),
        "isDirectory": directory, "isLog": name.endswith(".log"), "isReadable": readable, "isWritable": False,
        "size": size, "children": children,
    }


class FakeExarotonService:
    def __init__(self, *, status: ServerStatus = ServerStatus.ONLINE, transition_delay: float = 1.5) -> None:
        self.status = status
        self.transition_delay = transition_delay
        self.credits = 1234.56
        self.commands: list[str] = []
        self.actions: list[str] = []
        self.players = ["duma_n1", "Havar887", "Steve"]
        self._queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self.files = {
            "": _file("", "", directory=True, children=[
                _file("server.properties", "server.properties", size=1200),
                _file("logs", "logs", directory=True),
                _file("world", "world", directory=True),
            ]),
            "logs": _file("logs", "logs", directory=True, children=[_file("logs/latest.log", "latest.log", size=45000)]),
            "world": _file("world", "world", directory=True, children=[
                _file("world/advancements", "advancements", directory=True),
                _file("world/datapacks", "datapacks", directory=True),
                _file("world/level.dat", "level.dat", size=4096, text=False, readable=False),
            ]),
            "world/advancements": _file("world/advancements", "advancements", directory=True, children=[
                _file("world/advancements/069a79f4-44e9-4726-a5be-fca90e38aaf5.json", "069a79f4-44e9-4726-a5be-fca90e38aaf5.json", size=9000),
            ]),
            "world/advancements/069a79f4-44e9-4726-a5be-fca90e38aaf5.json": _file("world/advancements/069a79f4-44e9-4726-a5be-fca90e38aaf5.json", "069a79f4-44e9-4726-a5be-fca90e38aaf5.json", size=9000),
            "world/datapacks": _file("world/datapacks", "datapacks", directory=True, children=[]),
            "server.properties": _file("server.properties", "server.properties", size=1200),
            "logs/latest.log": _file("logs/latest.log", "latest.log", size=45000),
        }
        self.data = {
            "server.properties": b"motd=\\u00a77Welcome to the server of \\u00a79duma799\\u00a77!\nmax-players=20\nview-distance=10\nlevel-name=world\n",
            "logs/latest.log": self._log_text().encode(),
            "world/advancements/069a79f4-44e9-4726-a5be-fca90e38aaf5.json": json.dumps(_DEMO_ADVANCEMENTS).encode(),
        }


    def _server(self) -> Server:
        return Server.from_dict({
            "id": "demo-server", "name": "Duma's Survival", "address": "duma.exaroton.me",
            "motd": "§7Welcome to the server of §9duma799§7!", "status": int(self.status),
            "host": None, "port": None,
            "players": {"max": 20, "count": len(self.players) if self.status == ServerStatus.ONLINE else 0, "list": self.players if self.status == ServerStatus.ONLINE else []},
            "software": {"id": "fabric", "name": "Fabric", "version": "1.21.4"}, "shared": False,
        })

    def _log_text(self) -> str:
        lines = [f"[10:00:{i:02d}] [Server thread/INFO]: Preparing spawn area: {i * 4}%" for i in range(25)]
        lines.append("[10:00:26] [Server thread/INFO]: Done (12.345s)! For help, type \"help\"")
        lines.append("[10:00:27] [Server thread/WARN]: Can't keep up! Is the server overloaded?")
        lines.append("[10:00:28] [Server thread/INFO]: duma_n1 joined the game")
        return "\n".join(lines)

    async def _emit(self, event: StreamEvent) -> None:
        await self._queue.put(event)

    async def _transition(self, action: str) -> None:
        steps = {"start": [ServerStatus.LOADING, ServerStatus.STARTING, ServerStatus.ONLINE], "stop": [ServerStatus.STOPPING, ServerStatus.OFFLINE], "restart": [ServerStatus.RESTARTING, ServerStatus.STARTING, ServerStatus.ONLINE]}[action]
        for step in steps:
            await asyncio.sleep(self.transition_delay)
            self.status = step
            await self._emit(StatusEvent(self._server()))
        if self.status == ServerStatus.ONLINE:
            await self._emit(ConnectionEvent("live"))
            await self._emit(ConsoleEvent(ConsoleLine('[10:00:26] [Server thread/INFO]: Done (12.345s)! For help, type "help"')))


    async def aclose(self) -> None:
        pass

    async def account(self) -> Account:
        self.credits -= 0.01
        return Account("demo", "demo@example.com", True, self.credits)

    async def servers(self) -> list[Server]:
        return [self._server()]

    async def server(self, server_id: str) -> Server:
        return self._server()

    async def ram(self, server_id: str) -> float:
        return 4.0

    async def log(self, server_id: str) -> str | None:
        return self._log_text()

    async def share_log(self, server_id: str) -> str:
        return "https://mclo.gs/demo"

    async def player_lists(self, server_id: str) -> list[str]:
        return ["whitelist", "ops", "banned-players", "banned-ips"]

    async def player_list(self, server_id: str, name: str) -> list[str]:
        return {"whitelist": ["duma_n1", "Havar887", "Steve", "Alex"], "ops": ["duma_n1"], "banned-players": ["Griefer42"], "banned-ips": []}.get(name, [])

    async def file_info(self, server_id: str, path: str) -> FileInfo:
        path = path.strip("/")
        if path not in self.files:
            raise RuntimeError(f"File not found: /{path}")
        return FileInfo.from_dict(self.files[path])

    async def file_data(self, server_id: str, path: str) -> bytes:
        path = path.strip("/")
        if path not in self.data:
            raise RuntimeError("This file cannot be read.")
        return self.data[path]

    async def perform(self, action: str, server_id: str, *, use_own_credits: bool = False) -> None:
        ServerAction.validate(action, self.status)
        self.actions.append(action)
        asyncio.get_running_loop().create_task(self._transition(action))

    async def send_command(self, server_id: str, command: str) -> None:
        self.commands.append(command)
        await self._emit(ConsoleEvent(ConsoleLine(f"[{time.strftime('%H:%M:%S')}] [Server thread/INFO]: [Console] issued command: /{command}")))
        await asyncio.sleep(0.2)
        lower = command.lower()
        if lower.startswith("locate biome"):
            target = command.split()[-1]
            await self._emit(ConsoleEvent(ConsoleLine(f"[{time.strftime('%H:%M:%S')}] [Server thread/INFO]: The nearest {target} is at [{random.randint(-5000, 5000)} ~ {random.randint(-5000, 5000)}] ({random.randint(100, 4000):,} blocks away)")))
        elif lower.startswith("locate structure"):
            target = command.split()[-1]
            await self._emit(ConsoleEvent(ConsoleLine(f"[{time.strftime('%H:%M:%S')}] [Server thread/INFO]: The nearest {target} is at [{random.randint(-5000, 5000)} 64 {random.randint(-5000, 5000)}] ({random.randint(100, 4000):,} blocks away)")))
        elif lower.startswith("chunky start"):
            asyncio.get_running_loop().create_task(self._chunky_run())
        elif lower.startswith("chunky progress") or lower.startswith("chunky pause") or lower.startswith("chunky continue") or lower.startswith("chunky cancel"):
            verb = lower.split()[1]
            text = {"progress": "[Chunky] Task running for world. Processed: 182430 chunks (37.4%), ETA: 0:41:23, Rate: 124.5 cps, Current: 1, 2",
                    "pause": "[Chunky] Task paused for world.", "continue": "[Chunky] Task continuing for world.", "cancel": "[Chunky] Task cancelled for world."}[verb]
            await self._emit(ConsoleEvent(ConsoleLine(f"[{time.strftime('%H:%M:%S')}] [Server thread/INFO]: {text}")))
        elif lower.startswith("say "):
            await self._emit(ConsoleEvent(ConsoleLine(f"[{time.strftime('%H:%M:%S')}] [Server thread/INFO]: [Server] {command[4:]}")))
        else:
            await self._emit(ConsoleEvent(ConsoleLine(f"[{time.strftime('%H:%M:%S')}] [Server thread/INFO]: §aOK§r ({command})")))

    async def _chunky_run(self) -> None:
        for step in range(1, 11):
            await asyncio.sleep(1.0)
            await self._emit(ConsoleEvent(ConsoleLine(f"[{time.strftime('%H:%M:%S')}] [Server thread/INFO]: [Chunky] Task running for world. Processed: {step * 4000} chunks ({step * 10:.1f}%), ETA: 0:0{10 - step}:00, Rate: 130.2 cps, Current: {step}, {step}")))
        await self._emit(ConsoleEvent(ConsoleLine(f"[{time.strftime('%H:%M:%S')}] [Server thread/INFO]: [Chunky] Task finished for world. Processed: 40000 chunks (100%), Total time: 0:00:10")))

    def stream(self, server_id: str, *, tail: int = 200, initial_status: ServerStatus | None = None) -> "FakeStream":
        return FakeStream(self, tail)


class FakeStream:
    def __init__(self, service: FakeExarotonService, tail: int) -> None:
        self._service = service
        self._tail = tail
        self._closed = False

    def close(self) -> None:
        self._closed = True

    async def set_online(self, online: bool) -> None:
        return None

    async def send_command(self, command: str) -> bool:
        return False

    async def __aiter__(self) -> AsyncIterator[StreamEvent]:
        yield ConnectionEvent("connecting")
        await asyncio.sleep(0.2)
        yield ConnectionEvent("connected")
        if self._service.status == ServerStatus.ONLINE:
            yield ConnectionEvent("live")
            for line in self._service._log_text().splitlines()[-self._tail:]:
                yield ConsoleEvent(ConsoleLine(line))
        tick = 0
        while not self._closed:
            try:
                event = await asyncio.wait_for(self._service._queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                tick += 1
                if self._service.status == ServerStatus.ONLINE:
                    yield TickEvent(random.uniform(20.0, 60.0))
                    usage = random.uniform(1.6e9, 2.6e9)
                    yield StatsEvent(usage / 4.0e9 * 100, usage)
                    yield HeapEvent(random.uniform(0.9e9, 1.8e9))
                    if tick % 7 == 0:
                        yield ConsoleEvent(ConsoleLine(f"[{time.strftime('%H:%M:%S')}] [Server thread/INFO]: {random.choice(self._service.players)} moved too quickly!"))
