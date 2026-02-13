from __future__ import annotations

import asyncio
import json
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from core.models import RunConfig


def _parse_command(command: str) -> tuple[str, list[str]]:
    parts = shlex.split(command, posix=False)
    if not parts:
        raise ValueError("MCP command string is empty.")
    executable = parts[0]
    if executable.lower() in {"python", "python3", "py"}:
        executable = sys.executable
    return executable, parts[1:]


def _wait_for_tcp(host: str, port: int, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                time.sleep(0.2)
    return False


def _decode_call_result(result: Any) -> Any:
    if getattr(result, "isError", False):
        raise RuntimeError(f"MCP tool returned error: {result}")

    def _unwrap(value: Any) -> Any:
        if isinstance(value, dict) and "result" in value and len(value) == 1:
            return value["result"]
        return value

    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return _unwrap(structured)

    content = getattr(result, "content", None) or []
    texts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            texts.append(text)
    if not texts:
        return None
    if len(texts) == 1:
        value = texts[0]
        try:
            return _unwrap(json.loads(value))
        except Exception:  # noqa: BLE001
            return value
    return texts


@asynccontextmanager
async def _streamable_http_context(
    url: str,
    *,
    headers: dict[str, str] | None,
    timeout_seconds: int,
):
    timeout = max(1, timeout_seconds)
    async with httpx.AsyncClient(headers=headers or None, timeout=timeout) as http_client:
        async with streamable_http_client(url, http_client=http_client) as context:
            yield context


class _ServerProcess:
    def __init__(self, command: str, env: dict[str, str] | None = None):
        self.command = command
        self.env = env or {}
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        exe, args = _parse_command(self.command)
        merged_env = dict(os.environ)
        merged_env.update(self.env)
        self.process = subprocess.Popen(  # noqa: S603
            [exe, *args],  # noqa: S607
            env=merged_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None


class _ManagedSession:
    def __init__(
        self,
        context_factory: Callable[[], AbstractAsyncContextManager[tuple[Any, ...]]],
        call_timeout_seconds: int,
    ):
        self.context_factory = context_factory
        self.call_timeout_seconds = call_timeout_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready_event = threading.Event()
        self._start_error: Exception | None = None
        self._session: ClientSession | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._call_lock: asyncio.Lock | None = None

    @property
    def is_running(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
            and self._loop is not None
            and self._session is not None
        )

    def start(self, startup_timeout_seconds: int) -> None:
        if self.is_running:
            return
        self._ready_event.clear()
        self._start_error = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        ready = self._ready_event.wait(timeout=max(1, startup_timeout_seconds))
        if not ready:
            raise TimeoutError("MCP session startup timed out.")
        if self._start_error is not None:
            raise RuntimeError(f"MCP session failed to start: {self._start_error}")
        if self._session is None:
            raise RuntimeError("MCP session did not initialize.")

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session_main())
        finally:
            self._loop.close()

    async def _session_main(self) -> None:
        try:
            async with self.context_factory() as context:
                read_stream, write_stream = context[0], context[1]
                timeout = timedelta(seconds=max(1, self.call_timeout_seconds))
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timeout,
                ) as session:
                    await session.initialize()
                    self._session = session
                    self._call_lock = asyncio.Lock()
                    self._shutdown_event = asyncio.Event()
                    self._ready_event.set()
                    await self._shutdown_event.wait()
        except Exception as exc:  # noqa: BLE001
            self._start_error = exc
            self._ready_event.set()
        finally:
            self._session = None
            self._call_lock = None
            self._shutdown_event = None
            self._ready_event.set()

    async def _list_tools_async(self) -> list[str]:
        assert self._session is not None
        assert self._call_lock is not None
        async with self._call_lock:
            result = await self._session.list_tools()
        return [tool.name for tool in result.tools]

    async def _call_tool_async(self, name: str, arguments: dict[str, Any]) -> Any:
        assert self._session is not None
        assert self._call_lock is not None
        timeout = timedelta(seconds=max(1, self.call_timeout_seconds))
        async with self._call_lock:
            result = await self._session.call_tool(
                name=name,
                arguments=arguments,
                read_timeout_seconds=timeout,
            )
        return _decode_call_result(result)

    def list_tools(self) -> list[str]:
        if not self.is_running or self._loop is None:
            raise RuntimeError("MCP session is not running.")
        future = asyncio.run_coroutine_threadsafe(self._list_tools_async(), self._loop)
        return future.result(timeout=max(1, self.call_timeout_seconds + 1))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self.is_running or self._loop is None:
            raise RuntimeError("MCP session is not running.")
        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(name, arguments),
            self._loop,
        )
        return future.result(timeout=max(1, self.call_timeout_seconds + 2))

    def close(self) -> None:
        if self._loop is not None and self._shutdown_event is not None:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._loop = None
        self._session = None
        self._shutdown_event = None
        self._call_lock = None
        self._start_error = None


@dataclass(slots=True)
class TransportStatus:
    web_connected: bool
    local_connected: bool
    web_tools: list[str]
    local_tools: list[str]
    web_endpoint: str
    local_endpoint: str


class TransportRuntime:
    def __init__(self, config: RunConfig):
        self.config = config
        self.web_process: _ServerProcess | None = None
        self.local_process: _ServerProcess | None = None
        self.web_session: _ManagedSession | None = None
        self.local_session: _ManagedSession | None = None

        if config.mcp_transport == "stdio":
            web_cmd, web_args = _parse_command(config.mcp_web_server_cmd)
            local_cmd, local_args = _parse_command(config.mcp_local_server_cmd)
            self.web_session = _ManagedSession(
                context_factory=lambda: stdio_client(
                    StdioServerParameters(command=web_cmd, args=web_args)
                ),
                call_timeout_seconds=config.mcp_call_timeout_seconds,
            )
            self.local_session = _ManagedSession(
                context_factory=lambda: stdio_client(
                    StdioServerParameters(command=local_cmd, args=local_args)
                ),
                call_timeout_seconds=config.mcp_call_timeout_seconds,
            )
            self.web_endpoint = f"stdio:{config.mcp_web_server_cmd}"
            self.local_endpoint = f"stdio:{config.mcp_local_server_cmd}"
            return

        web_url = config.mcp_http_web_url or (
            f"http://{config.mcp_http_host}:{config.mcp_http_port_web}/mcp"
        )
        local_url = config.mcp_http_local_url or (
            f"http://{config.mcp_http_host}:{config.mcp_http_port_local}/mcp"
        )
        headers: dict[str, str] = {}
        client_token = config.mcp_client_auth_token or config.mcp_auth_token
        if client_token:
            headers["Authorization"] = f"Bearer {client_token}"
        self.web_session = _ManagedSession(
            context_factory=lambda: _streamable_http_context(
                web_url,
                headers=headers or None,
                timeout_seconds=config.mcp_call_timeout_seconds,
            ),
            call_timeout_seconds=config.mcp_call_timeout_seconds,
        )
        self.local_session = _ManagedSession(
            context_factory=lambda: _streamable_http_context(
                local_url,
                headers=headers or None,
                timeout_seconds=config.mcp_call_timeout_seconds,
            ),
            call_timeout_seconds=config.mcp_call_timeout_seconds,
        )
        self.web_endpoint = web_url
        self.local_endpoint = local_url

        if not config.mcp_http_external:
            env = {
                "MCP_HTTP_HOST": config.mcp_http_host,
                "MCP_HTTP_PORT_WEB": str(config.mcp_http_port_web),
                "MCP_HTTP_PORT_LOCAL": str(config.mcp_http_port_local),
                "MCP_AUTH_TOKEN": config.mcp_auth_token or "",
                "MCP_ALLOW_INSECURE_HTTP": "true"
                if config.mcp_allow_insecure_http
                else "false",
                "MCP_ALLOW_EXTERNAL_BIND": "true"
                if config.mcp_allow_external_bind
                else "false",
            }
            self.web_process = _ServerProcess(config.mcp_web_http_server_cmd, env=env)
            self.local_process = _ServerProcess(config.mcp_local_http_server_cmd, env=env)

    def start(self) -> None:
        assert self.web_session is not None
        assert self.local_session is not None

        if self.config.mcp_transport == "streamable-http":
            if self.web_process is not None and self.local_process is not None:
                self.web_process.start()
                self.local_process.start()
                ready_web = _wait_for_tcp(
                    host=self.config.mcp_http_host,
                    port=self.config.mcp_http_port_web,
                    timeout_seconds=self.config.mcp_startup_timeout_seconds,
                )
                ready_local = _wait_for_tcp(
                    host=self.config.mcp_http_host,
                    port=self.config.mcp_http_port_local,
                    timeout_seconds=self.config.mcp_startup_timeout_seconds,
                )
                if not (ready_web and ready_local):
                    raise RuntimeError("HTTP MCP server processes failed to bind ports.")
        self.web_session.start(self.config.mcp_startup_timeout_seconds)
        self.local_session.start(self.config.mcp_startup_timeout_seconds)

    def startup_probe(self) -> TransportStatus:
        assert self.web_session is not None
        assert self.local_session is not None
        web_ok = False
        local_ok = False
        web_tools: list[str] = []
        local_tools: list[str] = []
        try:
            web_tools = self.web_session.list_tools()
            web_ok = True
        except Exception:  # noqa: BLE001
            web_ok = False
        try:
            local_tools = self.local_session.list_tools()
            local_ok = True
        except Exception:  # noqa: BLE001
            local_ok = False
        return TransportStatus(
            web_connected=web_ok,
            local_connected=local_ok,
            web_tools=web_tools,
            local_tools=local_tools,
            web_endpoint=self.web_endpoint,
            local_endpoint=self.local_endpoint,
        )

    def call_web_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        assert self.web_session is not None
        return self.web_session.call_tool(tool_name, arguments)

    def call_local_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        assert self.local_session is not None
        return self.local_session.call_tool(tool_name, arguments)

    def close(self) -> None:
        if self.web_session is not None:
            self.web_session.close()
        if self.local_session is not None:
            self.local_session.close()
        if self.web_process is not None:
            self.web_process.close()
        if self.local_process is not None:
            self.local_process.close()
