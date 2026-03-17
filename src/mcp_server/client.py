from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from core.metrics import record_mcp_call, record_transport_fallback
from core.models import RetrievedDoc, RunConfig
from core.rate_limit import CircuitBreaker
from mcp_server.local_server import LocalMCPServer
from mcp_server.transport_runtime import TransportRuntime
from mcp_server.web_server import WebMCPServer


@dataclass
class ServerStatus:
    web_healthy: bool
    local_healthy: bool
    transport_enabled: bool
    transport_active: bool
    fallback_active: bool
    fallback_reason: str
    web_endpoint: str
    local_endpoint: str


def _web_tool_arguments(tool_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    if kwargs:
        return dict(kwargs)
    if tool_name in {"tavily_search", "ddg_search"}:
        query = args[0] if len(args) > 0 else ""
        k = args[1] if len(args) > 1 else 5
        return {"query": query, "k": k}
    if tool_name == "firecrawl_extract":
        url_or_query = args[0] if len(args) > 0 else ""
        mode = args[1] if len(args) > 1 else "extract"
        return {"url_or_query": url_or_query, "mode": mode}
    return {}


def _local_tool_arguments(tool_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    if kwargs:
        return dict(kwargs)
    if tool_name == "read_local_file":
        return {"path": args[0] if args else ""}
    if tool_name == "list_project_files":
        return {"pattern": args[0] if args else "*"}
    if tool_name == "code_search":
        pattern = args[0] if len(args) > 0 else ""
        max_results = args[1] if len(args) > 1 else 20
        return {"pattern": pattern, "max_results": max_results}
    if tool_name == "write_report_output":
        run_id = args[0] if len(args) > 0 else "fallback-run"
        content = args[1] if len(args) > 1 else ""
        return {"run_id": run_id, "content": content}
    return {}


class MultiServerClient:
    """Transport-first MCP client with in-process fallback path."""

    def __init__(
        self,
        config: RunConfig,
        web_server: WebMCPServer,
        local_server: LocalMCPServer,
        transport_runtime: TransportRuntime | None = None,
    ):
        self.config = config
        self.web_server = web_server
        self.local_server = local_server
        self.transport_runtime = transport_runtime
        self.web_breaker = CircuitBreaker(threshold=3, recovery_seconds=45)
        self.local_breaker = CircuitBreaker(threshold=3, recovery_seconds=45)
        self.transport_active = False
        self.fallback_active = config.mcp_mode == "inprocess"
        self.fallback_reason = "forced inprocess mode" if self.fallback_active else ""

    @classmethod
    def from_config(cls, config: RunConfig) -> MultiServerClient:
        web = WebMCPServer(config)
        local = LocalMCPServer(config)
        transport = None
        if config.mcp_mode in {"auto", "transport"} and config.mcp_transport in {
            "stdio",
            "streamable-http",
        }:
            transport = TransportRuntime(config)
        return cls(config, web, local, transport_runtime=transport)

    def close(self) -> None:
        if self.transport_runtime is not None:
            self.transport_runtime.close()
        self.transport_active = False

    def _enable_transport(self) -> None:
        if self.transport_runtime is None:
            raise RuntimeError("Transport runtime is not configured.")
        self.transport_runtime.start()
        probe = self.transport_runtime.startup_probe()
        if not (probe.web_connected and probe.local_connected):
            raise RuntimeError("MCP transport probe failed.")
        self.transport_active = True
        self.fallback_active = False
        self.fallback_reason = ""

    def startup_probe(self) -> ServerStatus:
        if self.config.mcp_mode == "inprocess":
            web_ok = self.web_server.health().get("status") == "ok"
            local_ok = self.local_server.health().get("status") == "ok"
            self.transport_active = False
            self.fallback_active = True
            self.fallback_reason = "forced inprocess mode"
            return ServerStatus(
                web_healthy=web_ok,
                local_healthy=local_ok,
                transport_enabled=False,
                transport_active=False,
                fallback_active=True,
                fallback_reason=self.fallback_reason,
                web_endpoint="inprocess:web_server",
                local_endpoint="inprocess:local_server",
            )

        transport_error = ""
        try:
            self._enable_transport()
            web_ok = True
            local_ok = True
            web_endpoint = (
                self.transport_runtime.web_endpoint if self.transport_runtime else "unknown"
            )
            local_endpoint = (
                self.transport_runtime.local_endpoint if self.transport_runtime else "unknown"
            )
        except Exception as exc:  # noqa: BLE001
            transport_error = str(exc)
            if self.transport_runtime is not None:
                self.transport_runtime.close()
            self.transport_active = False
            if self.config.mcp_mode == "transport":
                web_ok = False
                local_ok = False
            else:
                web_ok = self.web_server.health().get("status") == "ok"
                local_ok = self.local_server.health().get("status") == "ok"
                self.fallback_active = True
                self.fallback_reason = transport_error or "transport startup failed"
                record_transport_fallback(self.fallback_reason)
            web_endpoint = (
                self.transport_runtime.web_endpoint
                if self.transport_runtime is not None
                else "inprocess:web_server"
            )
            local_endpoint = (
                self.transport_runtime.local_endpoint
                if self.transport_runtime is not None
                else "inprocess:local_server"
            )
        return ServerStatus(
            web_healthy=web_ok,
            local_healthy=local_ok,
            transport_enabled=self.transport_runtime is not None,
            transport_active=self.transport_active,
            fallback_active=self.fallback_active,
            fallback_reason=self.fallback_reason,
            web_endpoint=web_endpoint,
            local_endpoint=local_endpoint,
        )

    def _invoke(
        self,
        breaker: CircuitBreaker,
        primary: Callable[..., Any],
        fallback: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not breaker.allow():
            return fallback(*args, **kwargs)
        try:
            value = primary(*args, **kwargs)
            breaker.success()
            return value
        except Exception:  # noqa: BLE001
            breaker.failure()
            return fallback(*args, **kwargs)

    @staticmethod
    def _fallback_web_tool(tool_name: str) -> Callable[..., list[RetrievedDoc]]:
        if tool_name == "tavily_search":
            return lambda query="", k=5: WebMCPServer._fallback_docs("tavily", query)
        if tool_name == "ddg_search":
            return lambda query="", k=5: WebMCPServer._fallback_docs("ddg", query)
        if tool_name == "firecrawl_extract":
            return lambda target="", mode="extract": WebMCPServer._fallback_docs(
                "firecrawl", target
            )
        return lambda *args, **kwargs: []

    def _fallback_local_tool(self, tool_name: str) -> Callable[..., Any]:
        if tool_name in {"list_project_files", "code_search"}:
            return lambda *args, **kwargs: []
        if tool_name == "read_local_file":
            return lambda *args, **kwargs: ""
        if tool_name == "write_report_output":
            def writer(run_id: str = "fallback-run", content: str = "") -> str:
                return self.local_server.write_report_output(run_id, content)

            return writer
        return lambda *args, **kwargs: None

    @staticmethod
    def _as_retrieved_docs(payload: Any) -> list[RetrievedDoc]:
        if payload is None:
            return []
        if isinstance(payload, list):
            docs: list[RetrievedDoc] = []
            for item in payload:
                if isinstance(item, RetrievedDoc):
                    docs.append(item)
                elif isinstance(item, dict):
                    docs.append(RetrievedDoc.model_validate(item))
            return docs
        return []

    def _call_transport_web(self, tool_name: str, *args: Any, **kwargs: Any) -> list[RetrievedDoc]:
        if not self.transport_active or self.transport_runtime is None:
            raise RuntimeError("Transport is not active.")
        arguments = _web_tool_arguments(tool_name, args, kwargs)
        payload = self.transport_runtime.call_web_tool(tool_name, arguments)
        return self._as_retrieved_docs(payload)

    def _call_transport_local(self, tool_name: str, *args: Any, **kwargs: Any) -> Any:
        if not self.transport_active or self.transport_runtime is None:
            raise RuntimeError("Transport is not active.")
        arguments = _local_tool_arguments(tool_name, args, kwargs)
        return self.transport_runtime.call_local_tool(tool_name, arguments)

    def _call_inprocess_web(self, tool_name: str, *args: Any, **kwargs: Any) -> list[RetrievedDoc]:
        primary = getattr(self.web_server, tool_name)
        fallback = self._fallback_web_tool(tool_name)
        return self._invoke(self.web_breaker, primary, fallback, *args, **kwargs)

    def _call_inprocess_local(self, tool_name: str, *args: Any, **kwargs: Any) -> Any:
        primary = getattr(self.local_server, tool_name)
        fallback = self._fallback_local_tool(tool_name)
        return self._invoke(self.local_breaker, primary, fallback, *args, **kwargs)

    def call_web_tool(self, tool_name: str, *args: Any, **kwargs: Any) -> list[RetrievedDoc]:
        started = perf_counter()
        transport_name = (
            self.config.mcp_transport
            if self.transport_active
            else "inprocess"
        )
        status = "success"
        if self.config.mcp_mode == "inprocess":
            value = self._call_inprocess_web(tool_name, *args, **kwargs)
            record_mcp_call(
                server="web",
                tool=tool_name,
                transport="inprocess",
                status=status,
                duration_seconds=perf_counter() - started,
            )
            return value
        try:
            if self.transport_active:
                value = self._call_transport_web(tool_name, *args, **kwargs)
                record_mcp_call(
                    server="web",
                    tool=tool_name,
                    transport=transport_name,
                    status=status,
                    duration_seconds=perf_counter() - started,
                )
                return value
            if self.config.mcp_mode == "transport":
                status = "error"
                raise RuntimeError("Transport mode is enabled but transport is not active.")
            self.fallback_active = True
            self.fallback_reason = "transport inactive, using inprocess fallback"
            record_transport_fallback(self.fallback_reason)
            value = self._call_inprocess_web(tool_name, *args, **kwargs)
            record_mcp_call(
                server="web",
                tool=tool_name,
                transport="inprocess",
                status="fallback",
                duration_seconds=perf_counter() - started,
            )
            return value
        except Exception as exc:  # noqa: BLE001
            if self.transport_active and self.config.mcp_mode != "transport":
                self.fallback_active = True
                self.fallback_reason = f"transport web call failed: {exc}"
                record_transport_fallback(self.fallback_reason)
                value = self._call_inprocess_web(tool_name, *args, **kwargs)
                record_mcp_call(
                    server="web",
                    tool=tool_name,
                    transport="inprocess",
                    status="fallback",
                    duration_seconds=perf_counter() - started,
                )
                return value
            record_mcp_call(
                server="web",
                tool=tool_name,
                transport=transport_name,
                status="error",
                duration_seconds=perf_counter() - started,
            )
            raise

    def call_local_tool(self, tool_name: str, *args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        transport_name = (
            self.config.mcp_transport
            if self.transport_active
            else "inprocess"
        )
        if self.config.mcp_mode == "inprocess":
            value = self._call_inprocess_local(tool_name, *args, **kwargs)
            record_mcp_call(
                server="local",
                tool=tool_name,
                transport="inprocess",
                status="success",
                duration_seconds=perf_counter() - started,
            )
            return value
        try:
            if self.transport_active:
                value = self._call_transport_local(tool_name, *args, **kwargs)
                record_mcp_call(
                    server="local",
                    tool=tool_name,
                    transport=transport_name,
                    status="success",
                    duration_seconds=perf_counter() - started,
                )
                return value
            if self.config.mcp_mode == "transport":
                raise RuntimeError("Transport mode is enabled but transport is not active.")
            self.fallback_active = True
            self.fallback_reason = "transport inactive, using inprocess fallback"
            record_transport_fallback(self.fallback_reason)
            value = self._call_inprocess_local(tool_name, *args, **kwargs)
            record_mcp_call(
                server="local",
                tool=tool_name,
                transport="inprocess",
                status="fallback",
                duration_seconds=perf_counter() - started,
            )
            return value
        except Exception as exc:  # noqa: BLE001
            if self.transport_active and self.config.mcp_mode != "transport":
                self.fallback_active = True
                self.fallback_reason = f"transport local call failed: {exc}"
                record_transport_fallback(self.fallback_reason)
                value = self._call_inprocess_local(tool_name, *args, **kwargs)
                record_mcp_call(
                    server="local",
                    tool=tool_name,
                    transport="inprocess",
                    status="fallback",
                    duration_seconds=perf_counter() - started,
                )
                return value
            record_mcp_call(
                server="local",
                tool=tool_name,
                transport=transport_name,
                status="error",
                duration_seconds=perf_counter() - started,
            )
            raise
