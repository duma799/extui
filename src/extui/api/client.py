from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from .models import (
    Account,
    ConnectionEvent,
    ConsoleEvent,
    ConsoleLine,
    FileInfo,
    HeapEvent,
    Server,
    ServerAction,
    ServerActionError,
    ServerStatus,
    StatsEvent,
    StatusEvent,
    StreamEvent,
    TickEvent,
)

DEFAULT_BASE_URL = "https://api.exaroton.com/v1/"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class ExarotonError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def safe_id(value: str) -> str:
    if not value or not _SAFE_ID.match(value):
        raise ExarotonError("Invalid identifier.")
    return value


def safe_file_path(value: str) -> str:
    parts = [part for part in value.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise ExarotonError("Invalid file path.")
    return "/".join(quote(part, safe="") for part in parts)


class ExarotonClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 20.0) -> None:
        self._token = token
        self._base_url = base_url if base_url.endswith("/") else base_url + "/"
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "extui"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "ExarotonClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


    async def _request(self, method: str, path: str, *, json_body: Any = None) -> Any:
        try:
            response = await self._http.request(method, path, json=json_body)
        except httpx.HTTPError as error:
            raise ExarotonError(f"Network error: {error.__class__.__name__}: {error}") from error
        if response.status_code == 401:
            raise ExarotonError("exaroton rejected the API token (HTTP 401).", 401)
        if response.status_code == 429:
            raise ExarotonError("exaroton rate limit reached (HTTP 429).", 429)
        try:
            envelope = response.json()
        except ValueError as error:
            raise ExarotonError(f"exaroton returned a non-JSON response (HTTP {response.status_code}).", response.status_code) from error
        if not isinstance(envelope, dict):
            raise ExarotonError("exaroton returned an invalid response.", response.status_code)
        if not envelope.get("success", False):
            raise ExarotonError(str(envelope.get("error") or f"exaroton API error (HTTP {response.status_code})"), response.status_code)
        if response.status_code >= 400:
            raise ExarotonError(f"exaroton returned HTTP {response.status_code}.", response.status_code)
        return envelope.get("data")

    async def _raw(self, path: str) -> bytes:
        try:
            response = await self._http.get(path, headers={"Accept": "*/*"})
        except httpx.HTTPError as error:
            raise ExarotonError(f"Network error: {error}") from error
        if response.status_code >= 400:
            raise ExarotonError(f"exaroton returned HTTP {response.status_code} for file data.", response.status_code)
        return response.content


    async def account(self) -> Account:
        return Account.from_dict(await self._request("GET", "account/") or {})

    async def servers(self) -> list[Server]:
        return [Server.from_dict(item) for item in (await self._request("GET", "servers/") or [])]

    async def server(self, server_id: str) -> Server:
        return Server.from_dict(await self._request("GET", f"servers/{safe_id(server_id)}/") or {})

    async def ram(self, server_id: str) -> float:
        data = await self._request("GET", f"servers/{safe_id(server_id)}/options/ram/") or {}
        return float(data.get("ram") or 0.0)

    async def set_ram(self, server_id: str, gigabytes: int) -> float:
        data = await self._request("POST", f"servers/{safe_id(server_id)}/options/ram/", json_body={"ram": int(gigabytes)}) or {}
        return float(data.get("ram") or 0.0)

    async def motd(self, server_id: str) -> str:
        data = await self._request("GET", f"servers/{safe_id(server_id)}/options/motd/") or {}
        return str(data.get("motd") or "")

    async def set_motd(self, server_id: str, motd: str) -> str:
        data = await self._request("POST", f"servers/{safe_id(server_id)}/options/motd/", json_body={"motd": motd}) or {}
        return str(data.get("motd") or "")

    async def log(self, server_id: str) -> str | None:
        data = await self._request("GET", f"servers/{safe_id(server_id)}/logs/") or {}
        content = data.get("content")
        return str(content) if content is not None else None

    async def share_log(self, server_id: str) -> str:
        data = await self._request("GET", f"servers/{safe_id(server_id)}/logs/share/") or {}
        return str(data.get("url") or "")

    async def player_lists(self, server_id: str) -> list[str]:
        return [str(name) for name in (await self._request("GET", f"servers/{safe_id(server_id)}/playerlists/") or [])]

    async def player_list(self, server_id: str, name: str) -> list[str]:
        return [str(entry) for entry in (await self._request("GET", f"servers/{safe_id(server_id)}/playerlists/{safe_id(name)}/") or [])]

    async def add_to_player_list(self, server_id: str, name: str, entries: list[str]) -> list[str]:
        data = await self._request("PUT", f"servers/{safe_id(server_id)}/playerlists/{safe_id(name)}/", json_body={"entries": entries})
        return [str(entry) for entry in (data or [])]

    async def remove_from_player_list(self, server_id: str, name: str, entries: list[str]) -> list[str]:
        data = await self._request("DELETE", f"servers/{safe_id(server_id)}/playerlists/{safe_id(name)}/", json_body={"entries": entries})
        return [str(entry) for entry in (data or [])]

    async def file_info(self, server_id: str, path: str) -> FileInfo:
        return FileInfo.from_dict(await self._request("GET", f"servers/{safe_id(server_id)}/files/info/{safe_file_path(path)}") or {})

    async def file_data(self, server_id: str, path: str) -> bytes:
        return await self._raw(f"servers/{safe_id(server_id)}/files/data/{safe_file_path(path)}")


    async def perform(self, action: str, server_id: str, *, use_own_credits: bool = False) -> None:
        if action not in ServerAction.ALL:
            raise ServerActionError(f"Unknown action {action!r}.")
        path = f"servers/{safe_id(server_id)}/{action}/"
        if action == "start" and use_own_credits:
            await self._request("POST", path, json_body={"useOwnCredits": True})
        else:
            await self._request("GET", path)

    async def send_command(self, server_id: str, command: str) -> None:
        command = command.strip()
        if not command:
            raise ExarotonError("Console command cannot be empty.")
        await self._request("POST", f"servers/{safe_id(server_id)}/command/", json_body={"command": command})


    def stream(self, server_id: str, *, tail: int = 200, initial_status: ServerStatus | None = None) -> "ServerStream":
        return ServerStream(self._token, self._base_url, safe_id(server_id), tail=tail, initial_status=initial_status)


class ServerStream:
    OPTIONAL_STREAMS = ("console", "tick", "stats", "heap")

    def __init__(self, token: str, base_url: str, server_id: str, *, tail: int = 200, initial_status: ServerStatus | None = None) -> None:
        self._token = token
        self._server_id = server_id
        self._tail = max(0, min(int(tail), 500))
        self._online = initial_status == ServerStatus.ONLINE
        self._closed = False
        self._socket: ClientConnection | None = None
        self._started: set[str] = set()
        http = base_url.rstrip("/")
        ws_base = "wss://" + http[len("https://"):] if http.startswith("https://") else "ws://" + http[len("http://"):]
        self._url = f"{ws_base}/servers/{server_id}/websocket"

    def close(self) -> None:
        self._closed = True

    async def set_online(self, online: bool) -> None:
        if online == self._online:
            return
        self._online = online
        if not online:
            self._started.clear()
            return
        socket = self._socket
        if socket is not None and not self._started:
            try:
                await self._start_optional(socket)
            except Exception:
                pass

    async def send_command(self, command: str) -> bool:
        socket = self._socket
        if socket is None or "console" not in self._started:
            return False
        try:
            await socket.send(json.dumps({"stream": "console", "type": "command", "data": command}))
            return True
        except Exception:
            return False

    async def __aiter__(self) -> AsyncIterator[StreamEvent]:
        attempt = 0
        while not self._closed:
            yield ConnectionEvent("connecting" if attempt == 0 else "reconnecting", attempt=attempt)
            try:
                async for event in self._run_once():
                    yield event
                    if isinstance(event, ConnectionEvent) and event.state == "live":
                        attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as error:
                yield ConnectionEvent("disconnected", detail=f"{error.__class__.__name__}: {error}"[:200])
            if self._closed:
                break
            attempt += 1
            await asyncio.sleep(min(2.0 * attempt, 15.0))

    async def _run_once(self) -> AsyncIterator[StreamEvent]:
        self._started.clear()
        async with websockets.connect(
            self._url,
            additional_headers={"Authorization": f"Bearer {self._token}", "User-Agent": "extui"},
            ping_interval=20,
            ping_timeout=20,
            max_size=4 * 1024 * 1024,
        ) as socket:
            self._socket = socket
            try:
                async for message in socket:
                    if isinstance(message, bytes):
                        message = message.decode("utf-8", "replace")
                    for event in await self._handle(socket, message):
                        yield event
                    if self._closed:
                        return
            finally:
                self._socket = None

    async def _handle(self, socket: ClientConnection, raw: str) -> list[StreamEvent]:
        try:
            payload = json.loads(raw)
        except ValueError:
            return []
        if not isinstance(payload, dict):
            return []
        kind = payload.get("type")
        stream = payload.get("stream")
        data = payload.get("data")
        events: list[StreamEvent] = []

        if kind == "ready":
            events.append(ConnectionEvent("connected"))
            if self._online:
                await self._start_optional(socket)
        elif kind == "connected":
            events.append(ConnectionEvent("connected"))
        elif kind == "disconnected":
            if data == "invalid-status":
                self._online = False
            self._started.clear()
            raise ExarotonError(f"exaroton closed the stream: {data}")
        elif kind == "keep-alive":
            pass
        elif kind == "status" and isinstance(data, dict):
            server = Server.from_dict(data)
            was_online = self._online
            self._online = server.status == ServerStatus.ONLINE
            events.append(StatusEvent(server))
            if self._online and not was_online:
                await self._start_optional(socket)
            elif not self._online:
                self._started.clear()
        elif kind == "started" and stream:
            self._started.add(str(stream))
            if stream == "console":
                events.append(ConnectionEvent("live"))
        elif kind == "stopped" and stream:
            self._started.discard(str(stream))
        elif stream == "console" and kind == "line" and isinstance(data, str):
            events.append(ConsoleEvent(ConsoleLine(data)))
        elif stream == "tick" and kind == "tick" and isinstance(data, dict):
            events.append(TickEvent(float(data.get("averageTickTime") or 0.0)))
        elif stream == "stats" and kind == "stats" and isinstance(data, dict):
            memory = data.get("memory") or {}
            events.append(StatsEvent(float(memory.get("percent") or 0.0), float(memory.get("usage") or 0.0)))
        elif stream == "heap" and kind == "heap" and isinstance(data, dict):
            events.append(HeapEvent(float(data.get("usage") or 0.0)))
        return events

    async def _start_optional(self, socket: ClientConnection) -> None:
        for name in self.OPTIONAL_STREAMS:
            if name in self._started:
                continue
            body: dict[str, Any] = {"stream": name, "type": "start"}
            if name == "console":
                body["data"] = {"tail": self._tail}
            await socket.send(json.dumps(body))


async def perform_and_follow(
    client: ExarotonClient,
    action: str,
    server_id: str,
    *,
    on_observation: Callable[[Server, float], Awaitable[None]] | None = None,
    poll_interval: float = 2.0,
    timeout: float = 180.0,
    use_own_credits: bool = False,
) -> Server:
    observed = time.monotonic()
    initial = await client.server(server_id)
    ServerAction.validate(action, initial.status)
    if on_observation:
        await on_observation(initial, observed)
    await client.perform(action, server_id, use_own_credits=use_own_credits)
    target = ServerAction.target(action)
    deadline = time.monotonic() + timeout
    previous = initial.status
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval)
        observed = time.monotonic()
        current = await client.server(server_id)
        if current.status != previous:
            previous = current.status
            if on_observation:
                await on_observation(current, observed)
        if current.status == target:
            return current
        if current.status == ServerStatus.CRASHED and action != "stop":
            return current
    raise ServerActionError(f"Timed out waiting for {action} (last state: {previous.label}).")
