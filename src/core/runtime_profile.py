from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import request as url_request
from urllib.error import URLError

from core.models import RunConfig


@dataclass(slots=True)
class DependencyStatus:
    enabled: bool
    ready: bool
    reason: str


def derive_profile_flags(
    runtime_profile: str,
    *,
    enable_distributed: bool | None = None,
    enable_observability: bool | None = None,
    enable_storage: bool | None = None,
) -> dict[str, bool]:
    profile = (runtime_profile or "minimal").strip().lower()
    if profile not in {"minimal", "balanced", "full"}:
        profile = "minimal"

    defaults = {
        "minimal": {"enable_distributed": False, "enable_observability": False, "enable_storage": False},
        "balanced": {"enable_distributed": True, "enable_observability": False, "enable_storage": True},
        "full": {"enable_distributed": True, "enable_observability": True, "enable_storage": True},
    }[profile]

    return {
        "enable_distributed": defaults["enable_distributed"]
        if enable_distributed is None
        else enable_distributed,
        "enable_observability": defaults["enable_observability"]
        if enable_observability is None
        else enable_observability,
        "enable_storage": defaults["enable_storage"] if enable_storage is None else enable_storage,
    }


def _distributed_status(config: RunConfig) -> DependencyStatus:
    if not config.enable_distributed:
        return DependencyStatus(enabled=False, ready=True, reason="disabled by runtime profile")
    try:
        from graph.distributed import is_distributed_ready
    except Exception as exc:  # noqa: BLE001
        return DependencyStatus(enabled=True, ready=False, reason=f"distributed module unavailable: {exc}")
    ready, reason = is_distributed_ready(timeout_seconds=config.distributed_health_timeout_seconds)
    return DependencyStatus(enabled=True, ready=ready, reason=reason or "ready")


def _observability_status(config: RunConfig) -> DependencyStatus:
    if not config.enable_observability:
        return DependencyStatus(enabled=False, ready=True, reason="disabled by runtime profile")
    if config.metrics_enabled or config.otel_enabled or bool(config.langsmith_api_key):
        return DependencyStatus(enabled=True, ready=True, reason="configured")
    return DependencyStatus(enabled=True, ready=False, reason="enabled but no telemetry sink configured")


def _storage_status(config: RunConfig) -> DependencyStatus:
    if not config.enable_storage:
        return DependencyStatus(enabled=False, ready=True, reason="disabled by runtime profile")
    if config.database_url:
        return DependencyStatus(enabled=True, ready=True, reason="database configured")
    return DependencyStatus(enabled=True, ready=False, reason="DATABASE_URL is not set")


def _probe_ollama(endpoint: str, timeout_seconds: int) -> tuple[bool, str]:
    if not endpoint:
        return False, "OLLAMA_ENDPOINT is not set"
    url = endpoint.rstrip("/") + "/api/tags"
    try:
        with url_request.urlopen(url, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                return False, f"ollama returned HTTP {status}"
            raw = response.read().decode("utf-8") or "{}"
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return False, "ollama response was not JSON"
            return True, "ready"
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        return False, f"ollama unreachable: {exc}"


def _ollama_status(config: RunConfig) -> DependencyStatus:
    timeout_seconds = max(1, int(getattr(config, "ollama_probe_timeout_seconds", 2)))
    ready, reason = _probe_ollama(config.ollama_endpoint, timeout_seconds)
    enabled = bool(config.ollama_endpoint)
    return DependencyStatus(enabled=enabled, ready=ready, reason=reason)


def dependency_health(config: RunConfig) -> dict[str, Any]:
    distributed = _distributed_status(config)
    observability = _observability_status(config)
    storage = _storage_status(config)
    ollama = _ollama_status(config)
    return {
        "runtime_profile": config.runtime_profile,
        "subsystems": {
            "distributed": {
                "enabled": distributed.enabled,
                "ready": distributed.ready,
                "reason": distributed.reason,
            },
            "observability": {
                "enabled": observability.enabled,
                "ready": observability.ready,
                "reason": observability.reason,
            },
            "storage": {
                "enabled": storage.enabled,
                "ready": storage.ready,
                "reason": storage.reason,
            },
            "ollama": {
                "enabled": ollama.enabled,
                "ready": ollama.ready,
                "reason": ollama.reason,
            },
        },
    }
