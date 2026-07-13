#!/usr/bin/env python3
"""Small MeSH RDF helper for the pubmed-search-builder skill."""

from __future__ import annotations

import argparse
import errno
import hashlib
import http.client
import json
import math
import os
import random
import re
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


# Keep the real wall clock available even when sweep tests replace the module-level ``time``
# object with a deterministic monotonic clock.
SYSTEM_WALL_TIME = time.time


LOOKUP_BASE = "https://id.nlm.nih.gov/mesh/lookup"
MESH_BASE = "http://id.nlm.nih.gov/mesh/"
SPARQL_URL = "https://id.nlm.nih.gov/mesh/sparql"
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_MAX_TERM_DESCRIPTOR_LOOKUPS = 40
DEFAULT_MAX_DETAIL_CANDIDATES = 30
DEFAULT_MAX_TREE_DESCENDANTS = 100
DEFAULT_MAX_TREE_SIBLINGS = 100
DEFAULT_SWEEP_MAX_SECONDS = 120.0
DEFAULT_EMAIL = ""
DEFAULT_TOOL = "codex-search-strategy-check"
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_BACKOFF_SECONDS = 1.0
REQUEST_CACHE: dict[tuple[str, tuple[tuple[str, str], ...]], object] = {}
ENV_FILE_CACHE: dict[str, str] | None = None
CACHE_SCHEMA_VERSION = 1
RESILIENCE_STATE_VERSION = 1
DEFAULT_CACHE_TTL_DAYS = 1.0
DEFAULT_RATE_LIMIT = 2.0
DEFAULT_EUTILS_RATE_WITHOUT_KEY = 3.0
DEFAULT_EUTILS_RATE_WITH_KEY = 10.0
DEFAULT_EUTILS_CANDIDATE_POOL = 100
DEFAULT_THROTTLE_RETRIES = 1
DEFAULT_TRANSIENT_RETRIES = 3
DEFAULT_CIRCUIT_THRESHOLD = 3
DEFAULT_CIRCUIT_COOLDOWN_SECONDS = 120.0
DEFAULT_CIRCUIT_MAX_COOLDOWN_SECONDS = 900.0
DEFAULT_STATE_LOCK_TIMEOUT_SECONDS = 5.0
DEFAULT_STATE_LOCK_STALE_SECONDS = 30.0
ERROR_RATE_LIMIT_LIKE = "rate_limit_like"
ERROR_TRANSIENT = "transient"
ERROR_HARD = "hard"
CACHE_BYPASS = False
NETWORK_METRICS: defaultdict[str, float] = defaultdict(float)
FALLBACK_HOST_STATE: dict[str, dict[str, object]] = {}
FALLBACK_STATE_LOCK = threading.Lock()
CACHE_MISS = object()
RDF_DEGRADED_FOR_RUN = False
TRANSPORT_METRIC_NAMES = (
    "logical_requests",
    "logical_successes",
    "logical_failures",
    "memory_cache_hits",
    "persistent_cache_hits",
    "persistent_cache_stale",
    "cache_corrupt_or_unreadable",
    "cache_misses",
    "persistent_cache_writes",
    "cache_write_errors",
    "network_requests",
    "retry_attempts",
    "retry_sleep_seconds",
    "pacing_wait_seconds",
    "rate_limit_like_events",
    "transient_events",
    "hard_events",
    "circuit_open_events",
    "backend_fallback_events",
    "resilience_state_errors",
)


class MeshError(Exception):
    pass


class MeshRequestError(MeshError):
    def __init__(self, message: str, *, classification: str, host: str, attempts: int):
        self.classification = classification
        self.host = host
        self.attempts = attempts
        super().__init__(message)


class BackendFallbackError(MeshError):
    """Both the primary RDF request and the eligible EUtils fallback failed."""

    def __init__(self, operation: str, primary: MeshError, fallback: MeshError):
        self.operation = operation
        self.primary = primary
        self.fallback = fallback
        super().__init__(
            f"{operation} could not use either MeSH backend: RDF failed ({primary}); "
            f"E-utilities fallback failed ({fallback})."
        )


class CircuitOpenError(MeshError):
    def __init__(
        self,
        host: str,
        cooldown_until: float,
        *,
        half_open_probe: bool = False,
        service_name: str = "MeSH RDF",
    ):
        self.host = host
        self.cooldown_until = cooldown_until
        self.half_open_probe = half_open_probe
        if cooldown_until > 0:
            until = datetime.fromtimestamp(cooldown_until, timezone.utc).isoformat().replace("+00:00", "Z")
            detail = f" until {until}"
        else:
            detail = ""
        reason = "another half-open probe is already running" if half_open_probe else "the host is cooling down"
        super().__init__(
            f"{service_name} circuit is open for {host}{detail}: {reason}. Fresh cached responses remain "
            "available; retry after the cooldown or inspect `mesh_tool.py circuit status`."
        )


class TransientResponseError(Exception):
    """A successful HTTP response whose body cannot yet be used as JSON."""


def parse_env_file(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}

    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def env_file_values() -> dict[str, str]:
    global ENV_FILE_CACHE
    if ENV_FILE_CACHE is not None:
        return ENV_FILE_CACHE

    values: dict[str, str] = {}
    seen: set[Path] = set()
    candidates = [
        Path(__file__).resolve().parents[1] / ".env",
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        values.update(parse_env_file(candidate))

    ENV_FILE_CACHE = values
    return values


def read_env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value:
        return value
    value = env_file_values().get(name)
    if value:
        return value
    if os.name != "nt":
        return default
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value) if value else default
    except OSError:
        return default


def mesh_user_agent() -> str:
    tool = read_env("NCBI_TOOL", DEFAULT_TOOL)
    email = read_env("NCBI_EMAIL", DEFAULT_EMAIL)
    user_agent = f"{tool}/1.0 pubmed-search-builder-mesh/1.0"
    if email:
        user_agent = f"{user_agent} ({email})"
    return user_agent


def env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = read_env(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if math.isfinite(value) and value >= minimum else default


def env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = read_env(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def wall_time() -> float:
    return SYSTEM_WALL_TIME()


def monotonic_time() -> float:
    return time.monotonic()


def sleep_seconds(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def cache_enabled() -> bool:
    if CACHE_BYPASS:
        return False
    return read_env("MESH_CACHE", "on").strip().casefold() not in {"0", "false", "no", "off", "disabled"}


def mesh_cache_dir() -> Path:
    configured = read_env("MESH_CACHE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    codex_home = read_env("CODEX_HOME", "").strip()
    root = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return (root / "cache" / "pubmed-search-builder" / "mesh-rdf").resolve()


def response_cache_dir() -> Path:
    return mesh_cache_dir() / "responses"


def resilience_state_path() -> Path:
    return mesh_cache_dir() / "resilience_state.json"


def resilience_lock_path() -> Path:
    return mesh_cache_dir() / "resilience_state.lock"


def metric_add(name: str, value: float = 1.0) -> None:
    NETWORK_METRICS[name] += value


def metrics_snapshot() -> dict[str, float]:
    return dict(NETWORK_METRICS)


def metrics_delta(start: dict[str, float]) -> dict[str, int | float]:
    keys = set(TRANSPORT_METRIC_NAMES) | set(start) | set(NETWORK_METRICS)
    result: dict[str, int | float] = {}
    for key in sorted(keys):
        value = NETWORK_METRICS.get(key, 0.0) - start.get(key, 0.0)
        result[key] = round(value, 3) if not float(value).is_integer() else int(value)
    return result


def request_cache_key(url: str, params: dict[str, str]) -> str:
    canonical = json.dumps(
        {
            "schema_version": CACHE_SCHEMA_VERSION,
            "url": url,
            "params": sorted((str(key), str(value)) for key, value in params.items()),
            "accept": "application/json",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def cache_entry_path(url: str, params: dict[str, str]) -> Path:
    digest = request_cache_key(url, params)
    return response_cache_dir() / digest[:2] / f"{digest}.json"


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass


def persistent_cache_get(url: str, params: dict[str, str]) -> object:
    path = cache_entry_path(url, params)
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return CACHE_MISS
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        metric_add("cache_corrupt_or_unreadable")
        return CACHE_MISS
    if not isinstance(entry, dict) or entry.get("schema_version") != CACHE_SCHEMA_VERSION:
        metric_add("cache_corrupt_or_unreadable")
        return CACHE_MISS
    request = entry.get("request")
    expected_request = {"url": url, "params": {str(key): str(value) for key, value in sorted(params.items())}}
    if request != expected_request:
        metric_add("cache_corrupt_or_unreadable")
        return CACHE_MISS
    fetched_epoch = entry.get("fetched_epoch")
    if not isinstance(fetched_epoch, (int, float)):
        metric_add("cache_corrupt_or_unreadable")
        return CACHE_MISS
    ttl_seconds = env_float("MESH_CACHE_TTL_DAYS", DEFAULT_CACHE_TTL_DAYS) * 86400.0
    if ttl_seconds <= 0 or wall_time() - float(fetched_epoch) > ttl_seconds:
        metric_add("persistent_cache_stale")
        return CACHE_MISS
    if "payload" not in entry:
        metric_add("cache_corrupt_or_unreadable")
        return CACHE_MISS
    metric_add("persistent_cache_hits")
    return entry["payload"]


def persistent_cache_put(url: str, params: dict[str, str], payload: object) -> None:
    now = wall_time()
    entry = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "request": {"url": url, "params": {str(key): str(value) for key, value in sorted(params.items())}},
        "fetched_epoch": now,
        "fetched_utc": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }
    try:
        atomic_write_json(cache_entry_path(url, params), entry)
        metric_add("persistent_cache_writes")
    except OSError:
        metric_add("cache_write_errors")


def cache_stats() -> dict[str, object]:
    root = response_cache_dir()
    now = wall_time()
    ttl_seconds = env_float("MESH_CACHE_TTL_DAYS", DEFAULT_CACHE_TTL_DAYS) * 86400.0
    counts = {"fresh": 0, "stale": 0, "corrupt": 0, "bytes": 0}
    for path in root.rglob("*.json") if root.is_dir() else []:
        try:
            counts["bytes"] += path.stat().st_size
            entry = json.loads(path.read_text(encoding="utf-8"))
            fetched = entry.get("fetched_epoch") if isinstance(entry, dict) else None
            if not isinstance(fetched, (int, float)) or entry.get("schema_version") != CACHE_SCHEMA_VERSION:
                counts["corrupt"] += 1
            elif ttl_seconds <= 0 or now - float(fetched) > ttl_seconds:
                counts["stale"] += 1
            else:
                counts["fresh"] += 1
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            counts["corrupt"] += 1
    return {
        "operation": "mesh-cache-stats",
        "cache_dir": str(mesh_cache_dir()),
        "enabled": cache_enabled(),
        "ttl_days": env_float("MESH_CACHE_TTL_DAYS", DEFAULT_CACHE_TTL_DAYS),
        **counts,
    }


def clear_cache() -> dict[str, object]:
    before = cache_stats()
    root = response_cache_dir()
    if root.exists():
        shutil.rmtree(root)
    REQUEST_CACHE.clear()
    return {
        "operation": "mesh-cache-clear",
        "cache_dir": str(mesh_cache_dir()),
        "removed_entries": int(before["fresh"]) + int(before["stale"]) + int(before["corrupt"]),
        "removed_bytes": before["bytes"],
    }


def default_host_state() -> dict[str, object]:
    return {
        "state": "closed",
        "consecutive_rate_limit_failures": 0,
        "cooldown_until": 0.0,
        "open_count": 0,
        "half_open_probe_until": 0.0,
        "next_allowed_at": 0.0,
        "updated_epoch": 0.0,
    }


def default_resilience_state() -> dict[str, object]:
    return {"schema_version": RESILIENCE_STATE_VERSION, "hosts": {}}


def normalized_host_state(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    normalized = default_host_state()
    state = str(source.get("state") or "closed")
    normalized["state"] = state if state in {"closed", "open", "half-open"} else "closed"
    for name in ("cooldown_until", "half_open_probe_until", "next_allowed_at", "updated_epoch"):
        try:
            numeric = float(source.get(name) or 0.0)
        except (TypeError, ValueError, OverflowError):
            numeric = 0.0
        normalized[name] = numeric if math.isfinite(numeric) and numeric >= 0 else 0.0
    for name in ("consecutive_rate_limit_failures", "open_count"):
        try:
            numeric = int(source.get(name) or 0)
        except (TypeError, ValueError, OverflowError):
            numeric = 0
        normalized[name] = max(0, numeric)
    return normalized


def read_resilience_state() -> dict[str, object]:
    try:
        state = json.loads(resilience_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default_resilience_state()
    if not isinstance(state, dict) or state.get("schema_version") != RESILIENCE_STATE_VERSION:
        return default_resilience_state()
    if not isinstance(state.get("hosts"), dict):
        state["hosts"] = {}
    return state


@contextmanager
def resilience_state_lock():
    path = resilience_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout = DEFAULT_STATE_LOCK_TIMEOUT_SECONDS
    stale_after = DEFAULT_STATE_LOCK_STALE_SECONDS
    deadline = monotonic_time() + timeout
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(descriptor, f"pid={os.getpid()} epoch={wall_time()}\n".encode("ascii", errors="replace"))
            except OSError:
                os.close(descriptor)
                descriptor = None
                path.unlink(missing_ok=True)
                raise
        except FileExistsError:
            try:
                stale = wall_time() - path.stat().st_mtime > stale_after
            except OSError:
                stale = False
            if stale:
                try:
                    path.unlink()
                    continue
                except OSError:
                    pass
            if monotonic_time() >= deadline:
                raise OSError(f"Timed out acquiring MeSH resilience state lock: {path}")
            sleep_seconds(0.05)
    try:
        yield
    finally:
        try:
            os.close(descriptor)
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def mutate_host_state(host: str, mutation):
    try:
        with resilience_state_lock():
            state = read_resilience_state()
            hosts = state.setdefault("hosts", {})
            current = hosts.get(host)
            current = normalized_host_state(current)
            result = mutation(current)
            current["updated_epoch"] = wall_time()
            hosts[host] = current
            atomic_write_json(resilience_state_path(), state)
            return result
    except OSError:
        metric_add("resilience_state_errors")
        with FALLBACK_STATE_LOCK:
            current = normalized_host_state(FALLBACK_HOST_STATE.get(host, {}))
            result = mutation(current)
            current["updated_epoch"] = wall_time()
            FALLBACK_HOST_STATE[host] = current
            return result


def current_host_state(host: str) -> dict[str, object]:
    state = read_resilience_state()
    hosts = state.get("hosts", {})
    current = hosts.get(host) if isinstance(hosts, dict) else None
    if isinstance(current, dict):
        return normalized_host_state(current)
    with FALLBACK_STATE_LOCK:
        return normalized_host_state(FALLBACK_HOST_STATE.get(host, {}))


def circuit_before_request(host: str, *, service_name: str = "MeSH RDF") -> bool:
    now = wall_time()
    probe_window = max(10.0, REQUEST_TIMEOUT_SECONDS * 2.0)

    def mutation(current: dict[str, object]) -> dict[str, object]:
        state = str(current.get("state") or "closed")
        cooldown_until = float(current.get("cooldown_until") or 0.0)
        probe_until = float(current.get("half_open_probe_until") or 0.0)
        if state == "open" and cooldown_until > now:
            return {"allowed": False, "cooldown_until": cooldown_until, "half_open_probe": False}
        if state in {"open", "half-open"}:
            if state == "half-open" and probe_until > now:
                return {"allowed": False, "cooldown_until": probe_until, "half_open_probe": True}
            current["state"] = "half-open"
            current["half_open_probe_until"] = now + probe_window
            return {"allowed": True, "half_open_owner": True}
        return {"allowed": True, "half_open_owner": False}

    result = mutate_host_state(host, mutation)
    if not result.get("allowed"):
        metric_add("circuit_open_events")
        raise CircuitOpenError(
            host,
            float(result.get("cooldown_until") or 0.0),
            half_open_probe=bool(result.get("half_open_probe")),
            service_name=service_name,
        )
    return bool(result.get("half_open_owner"))


def circuit_success(host: str) -> None:
    def mutation(current: dict[str, object]) -> None:
        current.update(
            {
                "state": "closed",
                "consecutive_rate_limit_failures": 0,
                "cooldown_until": 0.0,
                "open_count": 0,
                "half_open_probe_until": 0.0,
            }
        )

    mutate_host_state(host, mutation)


def circuit_rate_limit_failure(host: str) -> dict[str, object]:
    now = wall_time()
    threshold = env_int("MESH_CIRCUIT_THRESHOLD", DEFAULT_CIRCUIT_THRESHOLD, minimum=1)
    base_cooldown = env_float("MESH_CIRCUIT_COOLDOWN", DEFAULT_CIRCUIT_COOLDOWN_SECONDS)
    max_cooldown = env_float("MESH_CIRCUIT_MAX_COOLDOWN", DEFAULT_CIRCUIT_MAX_COOLDOWN_SECONDS)

    def mutation(current: dict[str, object]) -> dict[str, object]:
        was_half_open = current.get("state") == "half-open"
        failures = int(current.get("consecutive_rate_limit_failures") or 0) + 1
        current["consecutive_rate_limit_failures"] = failures
        should_open = was_half_open or failures >= threshold
        if should_open:
            open_count = int(current.get("open_count") or 0) + 1
            cooldown = min(max_cooldown, base_cooldown * (2 ** max(0, open_count - 1)))
            current.update(
                {
                    "state": "open",
                    "open_count": open_count,
                    "cooldown_until": now + cooldown,
                    "half_open_probe_until": 0.0,
                }
            )
        return {"opened": should_open, "state": current.get("state"), "cooldown_until": current.get("cooldown_until")}

    return mutate_host_state(host, mutation)


def circuit_transient_failure(host: str, *, half_open_owner: bool) -> None:
    now = wall_time()
    base_cooldown = env_float("MESH_CIRCUIT_COOLDOWN", DEFAULT_CIRCUIT_COOLDOWN_SECONDS)
    max_cooldown = env_float("MESH_CIRCUIT_MAX_COOLDOWN", DEFAULT_CIRCUIT_MAX_COOLDOWN_SECONDS)

    def mutation(current: dict[str, object]) -> None:
        if not half_open_owner:
            current["consecutive_rate_limit_failures"] = 0
            return
        open_count = int(current.get("open_count") or 0) + 1
        cooldown = min(max_cooldown, base_cooldown * (2 ** max(0, open_count - 1)))
        current.update(
            {
                "state": "open",
                "open_count": open_count,
                "cooldown_until": now + cooldown,
                "half_open_probe_until": 0.0,
            }
        )

    mutate_host_state(host, mutation)


def circuit_hard_failure(host: str, *, half_open_owner: bool) -> None:
    if half_open_owner:
        circuit_success(host)
        return

    def mutation(current: dict[str, object]) -> None:
        current["consecutive_rate_limit_failures"] = 0

    mutate_host_state(host, mutation)


def reserve_request_slot(host: str, requests_per_second: float | None = None) -> float:
    if requests_per_second is None:
        requests_per_second = env_float("MESH_RATE_LIMIT", DEFAULT_RATE_LIMIT)
    if requests_per_second <= 0:
        return 0.0
    now = wall_time()
    interval = 1.0 / requests_per_second
    jitter = random.uniform(0.0, interval * 0.1)

    def mutation(current: dict[str, object]) -> float:
        scheduled = max(now, float(current.get("next_allowed_at") or 0.0))
        current["next_allowed_at"] = scheduled + interval + jitter
        return scheduled

    scheduled = float(mutate_host_state(host, mutation))
    wait = max(0.0, scheduled - now)
    if wait:
        metric_add("pacing_wait_seconds", wait)
        sleep_seconds(wait)
    return wait


def eutils_rate_limit() -> float:
    return DEFAULT_EUTILS_RATE_WITH_KEY if read_env("NCBI_API_KEY", "") else DEFAULT_EUTILS_RATE_WITHOUT_KEY


def eutils_common_params() -> dict[str, str]:
    params = {"tool": read_env("NCBI_TOOL", DEFAULT_TOOL)}
    email = read_env("NCBI_EMAIL", DEFAULT_EMAIL)
    api_key = read_env("NCBI_API_KEY", "")
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    return params


def circuit_status(host: str = "id.nlm.nih.gov") -> dict[str, object]:
    current = current_host_state(host)
    return {
        "operation": "mesh-circuit-status",
        "host": host,
        **current,
        "now_epoch": wall_time(),
        "state_file": str(resilience_state_path()),
    }


def reset_circuit(host: str = "id.nlm.nih.gov") -> dict[str, object]:
    def mutation(current: dict[str, object]) -> None:
        next_allowed = current.get("next_allowed_at", 0.0)
        current.clear()
        current.update(default_host_state())
        current["next_allowed_at"] = next_allowed

    mutate_host_state(host, mutation)
    return {"operation": "mesh-circuit-reset", "host": host, "state": "closed"}


def retry_after_seconds(exc: Exception) -> float | None:
    if not isinstance(exc, urllib.error.HTTPError):
        return None
    value = exc.headers.get("Retry-After") if exc.headers else None
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, retry_at.timestamp() - wall_time())
        except (TypeError, ValueError, OverflowError):
            return None


def retry_delay(attempt: int, retry_after: float | None = None) -> float:
    if retry_after is not None:
        return retry_after
    base = REQUEST_BACKOFF_SECONDS * (2**attempt)
    return base + random.uniform(0.0, base * 0.25)


def classify_request_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429 or (exc.code == 403 and retry_after_seconds(exc) is not None):
            return ERROR_RATE_LIMIT_LIKE
        if exc.code in {408, 500, 502, 503, 504}:
            return ERROR_TRANSIENT
        return ERROR_HARD
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return classify_request_error(reason) if isinstance(reason, Exception) else ERROR_TRANSIENT
    if isinstance(exc, ssl.SSLCertVerificationError):
        return ERROR_HARD
    if isinstance(exc, (ConnectionResetError, http.client.RemoteDisconnected)):
        return ERROR_RATE_LIMIT_LIKE
    if isinstance(exc, (TimeoutError, socket.timeout, socket.gaierror, http.client.IncompleteRead, TransientResponseError)):
        return ERROR_TRANSIENT
    if isinstance(exc, ssl.SSLError):
        return ERROR_TRANSIENT
    if isinstance(exc, OSError):
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
        message = str(exc).casefold()
        if code in {errno.ECONNRESET, 10054} or any(
            marker in message for marker in ("reset by peer", "forcibly closed", "recv failure", "connection reset")
        ):
            return ERROR_RATE_LIMIT_LIKE
        return ERROR_TRANSIENT
    return ERROR_HARD


def error_detail(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="replace")[:2000]
        except OSError:
            body = ""
        suffix = f": {body}" if body else ""
        return f"HTTP {exc.code}{suffix}"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    return str(exc)


def close_request_error(exc: Exception) -> None:
    if isinstance(exc, urllib.error.HTTPError):
        exc.close()
    elif isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, urllib.error.HTTPError):
        exc.reason.close()


def transport_settings(backend: str, url: str) -> tuple[str, str, float, dict[str, str]]:
    host = urllib.parse.urlparse(url).hostname or "id.nlm.nih.gov"
    if backend == "rdf":
        return host, "MeSH RDF", env_float("MESH_RATE_LIMIT", DEFAULT_RATE_LIMIT), {}
    if backend == "eutils":
        return host, "MeSH E-utilities", eutils_rate_limit(), eutils_common_params()
    raise MeshError(f"Unsupported MeSH backend transport: {backend}")


def parse_json_response(raw: bytes) -> object:
    if not raw:
        raise TransientResponseError("empty JSON response body")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransientResponseError(f"invalid JSON response: {exc}") from exc


def parse_text_response(raw: bytes) -> str:
    if not raw:
        raise TransientResponseError("empty response body")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransientResponseError(f"invalid UTF-8 response: {exc}") from exc


def request_payload(
    url: str,
    params: dict[str, str],
    *,
    backend: str,
    accept: str,
    parser,
) -> object:
    memory_key = (url, tuple(sorted(params.items())))
    use_cache = cache_enabled()
    if use_cache and memory_key in REQUEST_CACHE:
        metric_add("memory_cache_hits")
        return REQUEST_CACHE[memory_key]
    if use_cache:
        persisted = persistent_cache_get(url, params)
        if persisted is not CACHE_MISS:
            REQUEST_CACHE[memory_key] = persisted
            return persisted
    metric_add("cache_misses")
    metric_add("logical_requests")

    host, service_name, requests_per_second, additional_params = transport_settings(backend, url)
    request_params = {**params, **additional_params}
    encoded = urllib.parse.urlencode(request_params)
    req = urllib.request.Request(f"{url}?{encoded}", method="GET")
    req.add_header("Accept", accept)
    req.add_header("User-Agent", mesh_user_agent())
    retries = {ERROR_RATE_LIMIT_LIKE: 0, ERROR_TRANSIENT: 0}
    limits = {
        ERROR_RATE_LIMIT_LIKE: env_int("MESH_THROTTLE_RETRIES", DEFAULT_THROTTLE_RETRIES),
        ERROR_TRANSIENT: env_int("MESH_TRANSIENT_RETRIES", DEFAULT_TRANSIENT_RETRIES),
    }
    attempts = 0
    half_open_owner = False

    while True:
        if attempts == 0:
            half_open_owner = circuit_before_request(host, service_name=service_name)
        elif not half_open_owner:
            circuit_before_request(host, service_name=service_name)
        reserve_request_slot(host, requests_per_second)
        attempts += 1
        metric_add("network_requests")
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read()
            data = parser(raw)
        except CircuitOpenError:
            raise
        except Exception as exc:
            classification = classify_request_error(exc)
            retry_after = retry_after_seconds(exc)
            metric_add(f"{classification}_events")
            retry_limit = limits.get(classification, 0)
            retry_count = retries.get(classification, 0)
            if classification == ERROR_HARD or retry_count >= retry_limit:
                metric_add("logical_failures")
                if classification == ERROR_RATE_LIMIT_LIKE:
                    circuit_result = circuit_rate_limit_failure(host)
                    if circuit_result.get("opened"):
                        metric_add("circuit_open_events")
                        close_request_error(exc)
                        raise CircuitOpenError(
                            host,
                            float(circuit_result.get("cooldown_until") or 0.0),
                            service_name=service_name,
                        ) from exc
                elif classification == ERROR_TRANSIENT:
                    circuit_transient_failure(host, half_open_owner=half_open_owner)
                else:
                    circuit_hard_failure(host, half_open_owner=half_open_owner)
                detail = error_detail(exc)
                close_request_error(exc)
                raise MeshRequestError(
                    f"{service_name} request failed ({classification}) after {attempts} attempt(s): {detail}",
                    classification=classification,
                    host=host,
                    attempts=attempts,
                ) from exc
            retries[classification] = retry_count + 1
            delay = retry_delay(retry_count, retry_after)
            close_request_error(exc)
            metric_add("retry_attempts")
            metric_add("retry_sleep_seconds", delay)
            sleep_seconds(delay)
            continue

        circuit_success(host)
        metric_add("logical_successes")
        if use_cache:
            REQUEST_CACHE[memory_key] = data
            persistent_cache_put(url, params, data)
        return data


def request_json(url: str, params: dict[str, str], *, backend: str = "rdf") -> object:
    return request_payload(
        url,
        params,
        backend=backend,
        accept="application/json",
        parser=parse_json_response,
    )


def request_text(url: str, params: dict[str, str], *, backend: str = "eutils") -> str:
    value = request_payload(
        url,
        params,
        backend=backend,
        accept="application/xml,text/xml",
        parser=parse_text_response,
    )
    return str(value)


def read_lines(path: str) -> list[str]:
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
    values = []
    for line in text.splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            values.append(value)
    return values


def resource_id(resource: str) -> str:
    return resource.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def mesh_resource(identifier: str) -> str:
    if identifier.startswith("http://") or identifier.startswith("https://"):
        return identifier
    return f"{MESH_BASE}{identifier}"


def tree_number_value(value: str) -> str:
    return resource_id(value)


def binding_value(binding: dict[str, object], name: str) -> str:
    value = binding.get(name, {})
    if not isinstance(value, dict):
        return ""
    return str(value.get("value", ""))


def unique_strings(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def sparql_bindings(data: object) -> list[dict[str, object]]:
    if not isinstance(data, dict):
        return []
    results = data.get("results", {})
    if not isinstance(results, dict):
        return []
    bindings = results.get("bindings", [])
    return bindings if isinstance(bindings, list) else []


BACKEND_NAMES = {"auto", "rdf", "eutils"}


def selected_backend(backend: str | None = None) -> str:
    """Return the requested backend, defaulting to the process environment.

    ``auto`` deliberately keeps RDF first because the RDF lookup API has the best match
    semantics and exposes the term-to-concept graph needed for a complete sweep.
    """
    value = (backend or read_env("MESH_BACKEND", "auto")).strip().casefold()
    if value not in BACKEND_NAMES:
        choices = ", ".join(sorted(BACKEND_NAMES))
        raise MeshError(f"Invalid MeSH backend {value!r}; choose one of: {choices}.")
    return value


def reset_runtime_backend_state() -> None:
    """Reset the process-local auto-backend degradation latch (mainly useful to tests)."""
    global RDF_DEGRADED_FOR_RUN
    RDF_DEGRADED_FOR_RUN = False


def provenance(
    backend: str,
    fidelity: str,
    method: str,
    fallback_reason: str | None = None,
) -> dict[str, str]:
    value = {"backend": backend, "fidelity": fidelity, "method": method}
    if fallback_reason:
        value["fallback_reason"] = fallback_reason
    return value


def annotate_records(
    records: list[dict[str, object]],
    *,
    backend: str,
    fidelity: str,
    method: str,
    fallback_reason: str | None = None,
) -> list[dict[str, object]]:
    marker = provenance(backend, fidelity, method, fallback_reason)
    annotated: list[dict[str, object]] = []
    for record in records:
        value = dict(record)
        value.update(
            {
                "source_backend": backend,
                "fidelity": fidelity,
                "provenance": marker,
            }
        )
        annotated.append(value)
    return annotated


def fallback_reason_for(exc: MeshError) -> str | None:
    if isinstance(exc, CircuitOpenError):
        return "rdf_circuit_open"
    if isinstance(exc, MeshRequestError) and exc.classification in {
        ERROR_RATE_LIMIT_LIKE,
        ERROR_TRANSIENT,
    }:
        return f"rdf_{exc.classification}"
    return None


def use_backend(
    operation: str,
    rdf_call,
    eutils_call,
    *,
    backend: str | None = None,
):
    """Run an operation with RDF-first auto failover for availability failures only."""
    global RDF_DEGRADED_FOR_RUN
    choice = selected_backend(backend)
    if choice == "rdf":
        return rdf_call(None)
    if choice == "eutils":
        return eutils_call(None)
    if RDF_DEGRADED_FOR_RUN:
        return eutils_call("rdf_degraded_for_run")
    try:
        return rdf_call(None)
    except MeshError as primary:
        reason = fallback_reason_for(primary)
        if not reason:
            raise
        RDF_DEGRADED_FOR_RUN = True
        metric_add("backend_fallback_events")
        try:
            return eutils_call(reason)
        except MeshError as fallback:
            raise BackendFallbackError(operation, primary, fallback) from fallback


def match_text(value: object, label: str, match: str) -> bool:
    candidate = normalized_label(value)
    target = normalized_label(label)
    if match == "exact":
        return candidate == target
    if match == "startswith":
        return candidate.startswith(target)
    if match == "contains":
        return target in candidate
    raise MeshError(f"Unsupported MeSH match mode: {match}")


def eutils_search_term(label: str, match: str) -> str:
    cleaned = " ".join(label.split())
    if match == "exact":
        return f'"{cleaned}"'
    if match == "startswith":
        return f"{cleaned}*"
    if match == "contains":
        return cleaned
    raise MeshError(f"Unsupported MeSH match mode: {match}")


def eutils_search_uids(label: str, match: str, limit: int, *, field: str) -> list[str]:
    data = request_json(
        f"{EUTILS_BASE}/esearch.fcgi",
        {
            "db": "mesh",
            "term": eutils_search_term(label, match),
            "field": field,
            "retmode": "json",
            "retmax": str(max(1, min(DEFAULT_EUTILS_CANDIDATE_POOL, limit))),
        },
        backend="eutils",
    )
    if not isinstance(data, dict):
        raise TransientResponseError("unexpected ESearch response shape")
    result = data.get("esearchresult", {})
    if not isinstance(result, dict):
        raise TransientResponseError("EUtils ESearch response has no esearchresult")
    ids = result.get("idlist", [])
    return [str(value) for value in ids] if isinstance(ids, list) else []


def xml_text(element: ET.Element | None, path: str) -> str:
    if element is None:
        return ""
    value = element.findtext(path)
    return " ".join(value.split()) if value else ""


def xml_texts(element: ET.Element, path: str) -> list[str]:
    values = []
    for node in element.findall(path):
        if node.text:
            value = " ".join(node.text.split())
            if value:
                values.append(value)
    return unique_strings(values)


def parse_eutils_summary(raw: bytes) -> list[dict[str, object]]:
    if not raw:
        raise TransientResponseError("empty EUtils ESummary response")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise TransientResponseError(f"invalid EUtils ESummary XML: {exc}") from exc
    records: list[dict[str, object]] = []
    for summary in root.findall(".//DocumentSummary"):
        descriptor = xml_text(summary, "DS_MeSHUI")
        label = xml_text(summary, "DS_MeshTerms/string")
        if not descriptor or not label:
            continue
        records.append(
            {
                "descriptor": descriptor,
                "resource": mesh_resource(descriptor),
                "label": label,
                "terms": xml_texts(summary, "DS_MeshTerms/string"),
                "qualifiers": xml_texts(summary, "DS_Subheading/string"),
                "tree_numbers": xml_texts(summary, "DS_IdxLinks/LinksType/TreeNum"),
                "scope_note": xml_text(summary, "DS_ScopeNote"),
                "previous_indexing": xml_texts(summary, "DS_PreviousIndexing/string"),
                "see_related": xml_texts(summary, "DS_SeeRelated/string"),
                "mapped_to": xml_texts(summary, "DS_HeadingMappedToList/string"),
                "record_type": xml_text(summary, "DS_RecordType"),
                "year_introduced": xml_text(summary, "DS_YearIntroduced"),
            }
        )
    return records


def eutils_summary_records(uids: list[str]) -> list[dict[str, object]]:
    if not uids:
        return []
    value = request_payload(
        f"{EUTILS_BASE}/esummary.fcgi",
        {"db": "mesh", "id": ",".join(uids), "version": "2.0", "retmode": "xml"},
        backend="eutils",
        accept="application/xml,text/xml",
        parser=parse_eutils_summary,
    )
    return value if isinstance(value, list) else []


def eutils_records_for_label(label: str, match: str, limit: int, *, field: str) -> list[dict[str, object]]:
    candidate_pool = max(limit * 5, 25)
    uids = eutils_search_uids(label, match, candidate_pool, field=field)
    return [record for record in eutils_summary_records(uids) if match_text(record.get("label", ""), label, match)][:limit]


def rdf_term_descriptor_candidates(term_resource: str, limit: int) -> list[dict[str, object]]:
    query = f"""
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?descriptor ?descriptorLabel ?concept ?conceptLabel WHERE {{
  ?concept ?p <{term_resource}> .
  OPTIONAL {{ ?concept rdfs:label ?conceptLabel . }}
  {{
    ?descriptor meshv:concept ?concept .
  }}
  UNION
  {{
    ?descriptor meshv:preferredConcept ?concept .
  }}
  ?descriptor rdfs:label ?descriptorLabel .
}}
LIMIT {limit}
""".strip()
    result = sparql(query, limit=limit, offset=0, inference=False)
    candidates: list[dict[str, object]] = []
    for binding in sparql_bindings(result.get("results", {})):
        descriptor = binding.get("descriptor", {})
        descriptor_label = binding.get("descriptorLabel", {})
        concept = binding.get("concept", {})
        concept_label = binding.get("conceptLabel", {})
        if not isinstance(descriptor, dict):
            continue
        descriptor_uri = str(descriptor.get("value", ""))
        if not descriptor_uri:
            continue
        candidates.append(
            {
                "descriptor": resource_id(descriptor_uri),
                "resource": descriptor_uri,
                "label": str(descriptor_label.get("value", "")) if isinstance(descriptor_label, dict) else "",
                "concept": str(concept.get("value", "")) if isinstance(concept, dict) else "",
                "concept_label": str(concept_label.get("value", "")) if isinstance(concept_label, dict) else "",
            }
        )
    return annotate_records(candidates, backend="rdf", fidelity="full", method="rdf_term_to_concept")


def eutils_term_descriptor_candidates(term_label: str, limit: int, fallback_reason: str | None) -> list[dict[str, object]]:
    if not term_label:
        return []
    term_result = eutils_terms(term_label, "exact", limit, fallback_reason=fallback_reason)
    candidates = []
    for item in term_result["results"]:
        if not isinstance(item, dict):
            continue
        descriptor = str(item.get("descriptor", ""))
        if descriptor:
            candidates.append(
                {
                    "descriptor": descriptor,
                    "resource": str(item.get("descriptor_resource", mesh_resource(descriptor))),
                    "label": str(item.get("descriptor_label", "")),
                    "concept": "",
                    "concept_label": "",
                    "source_backend": "eutils",
                    "fidelity": "reduced",
                    "provenance": item.get("provenance"),
                }
            )
    return candidates


def term_descriptor_candidates(
    term_resource: str,
    limit: int,
    *,
    term_label: str = "",
    backend: str | None = None,
) -> list[dict[str, object]]:
    return use_backend(
        "term-to-descriptor resolution",
        lambda _reason: rdf_term_descriptor_candidates(term_resource, limit),
        lambda reason: eutils_term_descriptor_candidates(term_label, limit, reason),
        backend=backend,
    )


def rdf_lookup(label: str, match: str, limit: int, fallback_reason: str | None = None) -> dict[str, object]:
    data = request_json(
        f"{LOOKUP_BASE}/descriptor",
        {"label": label, "match": match, "limit": str(limit)},
        backend="rdf",
    )
    records = data if isinstance(data, list) else []
    return {
        "operation": "lookup",
        "label": label,
        "match": match,
        "results": annotate_records(records, backend="rdf", fidelity="full", method="rdf_lookup", fallback_reason=fallback_reason),
        "provenance": provenance("rdf", "full", "rdf_lookup", fallback_reason),
    }


def eutils_lookup(label: str, match: str, limit: int, fallback_reason: str | None = None) -> dict[str, object]:
    field = "WORD" if match == "contains" else "MESH"
    records = eutils_records_for_label(label, match, limit, field=field)
    results = [{"resource": item["resource"], "label": item["label"]} for item in records]
    fidelity = "full" if match == "exact" else "reduced"
    return {
        "operation": "lookup",
        "label": label,
        "match": match,
        "results": annotate_records(results, backend="eutils", fidelity=fidelity, method="eutils_esearch_esummary", fallback_reason=fallback_reason),
        "provenance": provenance("eutils", fidelity, "eutils_esearch_esummary", fallback_reason),
    }


def lookup(label: str, match: str, limit: int, *, backend: str | None = None) -> dict[str, object]:
    return use_backend(
        "descriptor lookup",
        lambda reason: rdf_lookup(label, match, limit, reason),
        lambda reason: eutils_lookup(label, match, limit, reason),
        backend=backend,
    )


def rdf_terms(label: str, match: str, limit: int, fallback_reason: str | None = None) -> dict[str, object]:
    data = request_json(
        f"{LOOKUP_BASE}/term",
        {"label": label, "match": match, "limit": str(limit)},
        backend="rdf",
    )
    records = data if isinstance(data, list) else []
    return {
        "operation": "terms",
        "label": label,
        "match": match,
        "results": annotate_records(records, backend="rdf", fidelity="full", method="rdf_term_lookup", fallback_reason=fallback_reason),
        "provenance": provenance("rdf", "full", "rdf_term_lookup", fallback_reason),
    }


def eutils_terms(label: str, match: str, limit: int, fallback_reason: str | None = None) -> dict[str, object]:
    records = eutils_records_for_label(label, match, limit, field="WORD")
    results = []
    for record in records:
        for term in record.get("terms", []):
            if match_text(term, label, match):
                results.append(
                    {
                        "resource": "",
                        "label": term,
                        "descriptor": record["descriptor"],
                        "descriptor_resource": record["resource"],
                        "descriptor_label": record["label"],
                    }
                )
    results.sort(key=lambda item: (normalized_label(item["label"]), str(item["descriptor"])))
    return {
        "operation": "terms",
        "label": label,
        "match": match,
        "results": annotate_records(results[:limit], backend="eutils", fidelity="reduced", method="eutils_esearch_esummary", fallback_reason=fallback_reason),
        "provenance": provenance("eutils", "reduced", "eutils_esearch_esummary", fallback_reason),
    }


def terms(label: str, match: str, limit: int, *, backend: str | None = None) -> dict[str, object]:
    return use_backend(
        "entry-term lookup",
        lambda reason: rdf_terms(label, match, limit, reason),
        lambda reason: eutils_terms(label, match, limit, reason),
        backend=backend,
    )


def rdf_details(descriptor: str, include: str, fallback_reason: str | None = None) -> dict[str, object]:
    data = request_json(
        f"{LOOKUP_BASE}/details",
        {"descriptor": descriptor, "includes": include},
        backend="rdf",
    )
    return {
        "operation": "details",
        "descriptor": descriptor,
        "include": include,
        "details": data,
        "provenance": provenance("rdf", "full", "rdf_details", fallback_reason),
    }


def eutils_details(descriptor: str, include: str, fallback_reason: str | None = None) -> dict[str, object]:
    uids = eutils_search_uids(resource_id(descriptor), "exact", 5, field="MHUI")
    records = eutils_summary_records(uids)
    record = next((item for item in records if item.get("descriptor") == resource_id(descriptor)), None)
    if record is None:
        return {
            "operation": "details",
            "descriptor": resource_id(descriptor),
            "include": include,
            "details": {},
            "provenance": provenance("eutils", "reduced", "eutils_esearch_esummary", fallback_reason),
        }
    detail = {
        "descriptor": record["resource"],
        "terms": [
            {"resource": "", "label": term, "preferred": index == 0}
            for index, term in enumerate(record.get("terms", []))
        ],
        "scope_notes": [record["scope_note"]] if record.get("scope_note") else [],
        "qualifiers": [{"resource": "", "label": item} for item in record.get("qualifiers", [])],
        "tree_numbers": record.get("tree_numbers", []),
        "previous_indexing": record.get("previous_indexing", []),
        "seealso": [{"resource": "", "label": item} for item in record.get("see_related", [])],
        "mapped_to": record.get("mapped_to", []),
        "record_type": record.get("record_type", ""),
        "year_introduced": record.get("year_introduced", ""),
    }
    return {
        "operation": "details",
        "descriptor": resource_id(descriptor),
        "include": include,
        "details": detail,
        "provenance": provenance("eutils", "reduced", "eutils_esearch_esummary", fallback_reason),
    }


def details(descriptor: str, include: str, *, backend: str | None = None) -> dict[str, object]:
    return use_backend(
        "descriptor details",
        lambda reason: rdf_details(descriptor, include, reason),
        lambda reason: eutils_details(descriptor, include, reason),
        backend=backend,
    )


def first_value(values: list[str]) -> str:
    return values[0] if values else ""


def descriptor_record_sort_key(record: dict[str, object]) -> tuple[str, int, str, str]:
    tree_numbers = record.get("tree_numbers", [])
    first_tree = tree_numbers[0] if isinstance(tree_numbers, list) and tree_numbers else ""
    return (
        first_tree.split(".", 1)[0],
        first_tree.count("."),
        first_tree,
        normalized_label(record.get("label", "")),
    )


def add_tree_number(record: dict[str, object], tree_number: str) -> None:
    if not tree_number:
        return
    values = record.setdefault("tree_numbers", [])
    if isinstance(values, list) and tree_number not in values:
        values.append(tree_number)
        values.sort(key=lambda value: (str(value).split(".", 1)[0], str(value).count("."), str(value)))


def descriptor_records_from_bindings(
    bindings: list[dict[str, object]],
    descriptor_var: str,
    label_var: str,
    tree_var: str = "tree",
) -> list[dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for binding in bindings:
        descriptor_uri = binding_value(binding, descriptor_var)
        if not descriptor_uri:
            continue
        descriptor_id = resource_id(descriptor_uri)
        record = records.setdefault(
            descriptor_id,
            {
                "descriptor": descriptor_id,
                "resource": descriptor_uri,
                "label": binding_value(binding, label_var),
                "tree_numbers": [],
            },
        )
        if not record.get("label"):
            record["label"] = binding_value(binding, label_var)
        add_tree_number(record, tree_number_value(binding_value(binding, tree_var)))
    return sorted(records.values(), key=descriptor_record_sort_key)


def term_entries(detail_data: object, preferred: bool | None = None) -> list[dict[str, object]]:
    if not isinstance(detail_data, dict):
        return []
    terms_data = detail_data.get("terms", [])
    if not isinstance(terms_data, list):
        return []

    entries = []
    seen = set()
    for item in terms_data:
        if not isinstance(item, dict):
            continue
        is_preferred = bool(item.get("preferred"))
        if preferred is not None and is_preferred is not preferred:
            continue
        resource = str(item.get("resource", ""))
        label = str(item.get("label", ""))
        key = (resource, label)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "term": resource_id(resource) if resource else "",
                "resource": resource,
                "label": label,
                "preferred": is_preferred,
            }
        )
    return entries


def mesh_metadata(descriptor: str) -> dict[str, list[str]]:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?label ?type ?scopeNote ?annotation ?historyNote ?publicMeSHNote WHERE {{
  mesh:{descriptor} rdfs:label ?label .
  OPTIONAL {{ mesh:{descriptor} a ?type . }}
  OPTIONAL {{
    mesh:{descriptor} meshv:preferredConcept ?preferredConcept .
    OPTIONAL {{ ?preferredConcept meshv:scopeNote ?scopeNote . }}
  }}
  OPTIONAL {{ mesh:{descriptor} meshv:annotation ?annotation . }}
  OPTIONAL {{ mesh:{descriptor} meshv:historyNote ?historyNote . }}
  OPTIONAL {{ mesh:{descriptor} meshv:publicMeSHNote ?publicMeSHNote . }}
}}
LIMIT 100
""".strip()
    result = sparql(query, limit=100, offset=0, inference=False)
    metadata: dict[str, list[str]] = {
        "labels": [],
        "types": [],
        "scope_notes": [],
        "annotations": [],
        "history_notes": [],
        "public_mesh_notes": [],
    }
    for binding in sparql_bindings(result.get("results", {})):
        metadata["labels"].append(binding_value(binding, "label"))
        metadata["types"].append(resource_id(binding_value(binding, "type")))
        metadata["scope_notes"].append(binding_value(binding, "scopeNote"))
        metadata["annotations"].append(binding_value(binding, "annotation"))
        metadata["history_notes"].append(binding_value(binding, "historyNote"))
        metadata["public_mesh_notes"].append(binding_value(binding, "publicMeSHNote"))

    return {key: unique_strings(values) for key, values in metadata.items()}


def resource_type(types: list[str], descriptor: str) -> str:
    priorities = [
        "TopicalDescriptor",
        "GeographicalDescriptor",
        "PublicationType",
        "SCR_Chemical",
        "SCR_Disease",
        "SCR_Organism",
        "SCR_Protocol",
    ]
    for candidate in priorities:
        if candidate in types:
            return candidate
    if types:
        return types[0]
    if descriptor.startswith("C"):
        return "SupplementaryConceptRecord"
    if descriptor.startswith("D"):
        return "Descriptor"
    return "unknown"


def tree_numbers_for_descriptor(descriptor: str) -> list[str]:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
SELECT ?treeNumber WHERE {{
  mesh:{descriptor} meshv:treeNumber ?treeNumber .
}}
ORDER BY ?treeNumber
LIMIT 200
""".strip()
    result = sparql(query, limit=200, offset=0, inference=False)
    values = [
        tree_number_value(binding_value(binding, "treeNumber"))
        for binding in sparql_bindings(result.get("results", {}))
    ]
    return sorted(unique_strings(values), key=lambda value: (value.split(".", 1)[0], value.count("."), value))


def broader_descriptors(descriptor: str) -> list[dict[str, object]]:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?broader ?broaderLabel ?tree WHERE {{
  mesh:{descriptor} meshv:broaderDescriptor ?broader .
  ?broader rdfs:label ?broaderLabel .
  OPTIONAL {{ ?broader meshv:treeNumber ?tree . }}
}}
ORDER BY ?broaderLabel ?tree
LIMIT 200
""".strip()
    result = sparql(query, limit=200, offset=0, inference=False)
    return descriptor_records_from_bindings(
        sparql_bindings(result.get("results", {})),
        "broader",
        "broaderLabel",
    )


def narrower_descriptors(descriptor: str) -> list[dict[str, object]]:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?narrower ?narrowerLabel ?tree WHERE {{
  ?narrower meshv:broaderDescriptor mesh:{descriptor} ;
            rdfs:label ?narrowerLabel .
  OPTIONAL {{ ?narrower meshv:treeNumber ?tree . }}
}}
ORDER BY ?narrowerLabel ?tree
LIMIT 500
""".strip()
    result = sparql(query, limit=500, offset=0, inference=False)
    return descriptor_records_from_bindings(
        sparql_bindings(result.get("results", {})),
        "narrower",
        "narrowerLabel",
    )


def descendant_descriptors(descriptor: str, max_descendants: int) -> tuple[list[dict[str, object]], bool]:
    query_limit = max_descendants + 1
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?descendant ?descendantLabel ?tree WHERE {{
  mesh:{descriptor} meshv:treeNumber ?rootTree .
  ?descendant meshv:treeNumber ?tree ;
              rdfs:label ?descendantLabel .
  FILTER(?descendant != mesh:{descriptor})
  FILTER(STRSTARTS(STR(?tree), CONCAT(STR(?rootTree), ".")))
}}
ORDER BY ?tree ?descendantLabel
LIMIT {query_limit}
""".strip()
    result = sparql(query, limit=query_limit, offset=0, inference=False)
    bindings = sparql_bindings(result.get("results", {}))
    records = descriptor_records_from_bindings(bindings, "descendant", "descendantLabel")
    return records[:max_descendants], len(records) > max_descendants or len(bindings) > max_descendants


def sibling_descriptor_groups(
    descriptor: str,
    max_siblings: int,
) -> tuple[list[dict[str, object]], bool]:
    query_limit = max_siblings + 1
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?parent ?parentLabel ?sibling ?siblingLabel ?tree WHERE {{
  mesh:{descriptor} meshv:broaderDescriptor ?parent .
  ?parent rdfs:label ?parentLabel .
  ?sibling meshv:broaderDescriptor ?parent ;
           rdfs:label ?siblingLabel .
  FILTER(?sibling != mesh:{descriptor})
  OPTIONAL {{ ?sibling meshv:treeNumber ?tree . }}
}}
ORDER BY ?parentLabel ?siblingLabel ?tree
LIMIT {query_limit}
""".strip()
    result = sparql(query, limit=query_limit, offset=0, inference=False)
    bindings = sparql_bindings(result.get("results", {}))
    groups: dict[str, dict[str, object]] = {}
    sibling_count = 0

    for binding in bindings:
        parent_uri = binding_value(binding, "parent")
        sibling_uri = binding_value(binding, "sibling")
        if not parent_uri or not sibling_uri:
            continue
        parent_id = resource_id(parent_uri)
        group = groups.setdefault(
            parent_id,
            {
                "broader_descriptor": {
                    "descriptor": parent_id,
                    "resource": parent_uri,
                    "label": binding_value(binding, "parentLabel"),
                },
                "siblings": {},
            },
        )
        siblings = group.get("siblings", {})
        if not isinstance(siblings, dict):
            continue
        sibling_id = resource_id(sibling_uri)
        if sibling_id not in siblings:
            sibling_count += 1
            siblings[sibling_id] = {
                "descriptor": sibling_id,
                "resource": sibling_uri,
                "label": binding_value(binding, "siblingLabel"),
                "tree_numbers": [],
            }
        add_tree_number(siblings[sibling_id], tree_number_value(binding_value(binding, "tree")))

    output = []
    for group in groups.values():
        siblings = group.get("siblings", {})
        sibling_list = []
        if isinstance(siblings, dict):
            sibling_list = sorted(siblings.values(), key=descriptor_record_sort_key)
        output.append(
            {
                "broader_descriptor": group["broader_descriptor"],
                "siblings": sibling_list,
            }
        )

    output.sort(key=lambda item: normalized_label(item["broader_descriptor"].get("label", "")))  # type: ignore[index]
    return output, sibling_count > max_siblings or len(bindings) > max_siblings


def split_descriptor_qualifier_mapping(identifier: str) -> tuple[str, str] | None:
    match = re.match(r"^(D\d+)(Q\d+)$", identifier)
    if not match:
        return None
    return match.group(1), match.group(2)


def resource_label(identifier: str) -> str:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?label WHERE {{
  mesh:{identifier} rdfs:label ?label .
}}
LIMIT 5
""".strip()
    result = sparql(query, limit=5, offset=0, inference=False)
    labels = [
        binding_value(binding, "label")
        for binding in sparql_bindings(result.get("results", {}))
    ]
    return first_value(unique_strings(labels))


def scr_mapping(descriptor: str) -> dict[str, object]:
    if not descriptor.startswith("C"):
        return {"status": "not_applicable"}

    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?mapped ?mappedLabel WHERE {{
  mesh:{descriptor} meshv:preferredMappedTo ?mapped .
  OPTIONAL {{ ?mapped rdfs:label ?mappedLabel . }}
}}
ORDER BY ?mapped
LIMIT 100
""".strip()
    result = sparql(query, limit=100, offset=0, inference=False)
    mappings = []
    for binding in sparql_bindings(result.get("results", {})):
        mapped_uri = binding_value(binding, "mapped")
        if not mapped_uri:
            continue
        mapped_id = resource_id(mapped_uri)
        mapping: dict[str, object] = {
            "mapped_to": mapped_id,
            "resource": mapped_uri,
            "label": binding_value(binding, "mappedLabel"),
        }
        split_mapping = split_descriptor_qualifier_mapping(mapped_id)
        if split_mapping:
            descriptor_id, qualifier_id = split_mapping
            mapping["descriptor"] = {
                "descriptor": descriptor_id,
                "resource": mesh_resource(descriptor_id),
                "label": resource_label(descriptor_id),
            }
            mapping["qualifier"] = {
                "qualifier": qualifier_id,
                "resource": mesh_resource(qualifier_id),
                "label": resource_label(qualifier_id),
            }
        mappings.append(mapping)

    if not mappings:
        return {
            "status": "none_found",
            "mappings": [],
            "review_prompt": "No preferredMappedTo relationship was found in MeSH RDF; review this SCR manually before using it as controlled vocabulary.",
        }
    return {
        "status": "mapped",
        "mappings": mappings,
        "review_prompt": "For SCRs, review preferredMappedTo descriptors and keep the SCR text term in the [tiab]/substance layer when relevant.",
    }


def explosion_review_prompts(
    descriptor: str,
    preferred_label: str,
    resource_type_value: str,
    tree_numbers: list[str],
    broader: list[dict[str, object]],
    narrower: list[dict[str, object]],
    descendants: list[dict[str, object]],
    descendants_truncated: bool,
    sibling_groups: list[dict[str, object]],
    siblings_truncated: bool,
    mapping: dict[str, object],
) -> list[str]:
    label = preferred_label or descriptor
    prompts = []

    if resource_type_value.startswith("SCR") or descriptor.startswith("C"):
        prompts.append("This looks like a Supplementary Concept Record; review scr_mapping before deciding whether to search the SCR, its mapped descriptor, or both.")

    if not tree_numbers:
        prompts.append("No MeSH tree numbers were found, so a descriptor explosion/noexp decision cannot be made from tree context alone.")
    elif descendants:
        prompts.append(f"Review all returned descendants before using \"{label}\"[Mesh]; use explosion only when the descendant branches are in scope.")
        prompts.append(f"If descendant branches would add out-of-scope records, compare \"{label}\"[Mesh:noexp] or more specific descriptors.")
    else:
        prompts.append(f"No descendants were returned for \"{label}\" in the current MeSH tree evidence; [Mesh] and [Mesh:noexp] may retrieve similarly, but count-test if the choice matters.")

    if len(tree_numbers) > 1:
        prompts.append("This descriptor appears in multiple MeSH tree positions; review each branch before treating the explosion as a single-scope decision.")
    if broader:
        prompts.append("Use broader_descriptors and sibling_descriptors to decide whether a parent descriptor would be too broad or whether a sibling should be searched separately.")
    if narrower and not descendants:
        prompts.append("Direct narrower descriptors were returned even though no descendants were returned by tree-number prefix matching; inspect this discrepancy before finalizing explosion notes.")
    if descendants_truncated or siblings_truncated:
        prompts.append("Tree context was truncated by the requested max limit; rerun tree with a higher max before making a final explosion decision.")
    if mapping.get("status") == "mapped":
        prompts.append("For mapped SCRs, PubMed count-test the SCR label, mapped descriptor, and any useful entry terms separately before including or rejecting them.")

    if resource_type_value.startswith("SCR") or descriptor.startswith("C"):
        prompts.append(f"Run PubMed count tests with scripts/pubmed_tool.py search '\"{label}\"[Supplementary Concept]' --retmax 0, plus mapped descriptor and text-word checks when relevant.")
    else:
        prompts.append(f"Run PubMed count tests with scripts/pubmed_tool.py search '\"{label}\"[Mesh]' --retmax 0 and, when descendants or scope uncertainty exist, '\"{label}\"[Mesh:noexp]' --retmax 0.")
    prompts.append("Document accepted and plausible rejected descriptors with scope, descendant, sibling, and count-test rationale.")
    return prompts


def tree(
    descriptor: str,
    max_descendants: int,
    max_siblings: int,
    *,
    backend: str | None = None,
) -> dict[str, object]:
    if selected_backend(backend) == "eutils":
        raise MeshError("The MeSH tree command is RDF-only in Phase 2; use --backend rdf or auto.")
    descriptor_id = resource_id(descriptor)
    detail_data = details(descriptor_id, "terms,seealso,qualifiers", backend="rdf").get("details", {})
    if not isinstance(detail_data, dict):
        detail_data = {}

    metadata = mesh_metadata(descriptor_id)
    preferred_terms = term_entries(detail_data, preferred=True)
    preferred_label = first_value(metadata["labels"])
    if not preferred_label and preferred_terms:
        preferred_label = str(preferred_terms[0].get("label", ""))

    tree_numbers = tree_numbers_for_descriptor(descriptor_id)
    broader = broader_descriptors(descriptor_id)
    narrower = narrower_descriptors(descriptor_id)
    descendants, descendants_truncated = descendant_descriptors(descriptor_id, max_descendants)
    sibling_groups, siblings_truncated = sibling_descriptor_groups(descriptor_id, max_siblings)
    mapping = scr_mapping(descriptor_id)
    resource_type_value = resource_type(metadata["types"], descriptor_id)

    return {
        "operation": "tree",
        "descriptor": descriptor_id,
        "resource": mesh_resource(descriptor_id),
        "resource_type": resource_type_value,
        "preferred_label": preferred_label,
        "scope_note": first_value(metadata["scope_notes"]) or None,
        "annotation": first_value(metadata["annotations"]) or None,
        "history_note": first_value(metadata["history_notes"]) or None,
        "public_mesh_note": first_value(metadata["public_mesh_notes"]) or None,
        "entry_terms": term_entries(detail_data, preferred=False),
        "tree_numbers": tree_numbers,
        "broader_descriptors": broader,
        "narrower_descriptors": narrower,
        "descendants": descendants,
        "descendants_truncated": descendants_truncated,
        "sibling_descriptors": sibling_groups,
        "sibling_descriptors_truncated": siblings_truncated,
        "scr_mapping": mapping,
        "limits": {
            "max_descendants": max_descendants,
            "max_siblings": max_siblings,
        },
        "explosion_review_prompts": explosion_review_prompts(
            descriptor_id,
            preferred_label,
            resource_type_value,
            tree_numbers,
            broader,
            narrower,
            descendants,
            descendants_truncated,
            sibling_groups,
            siblings_truncated,
            mapping,
        ),
    }


def normalized_label(value: object) -> str:
    return " ".join(str(value).casefold().replace("-", " ").split())


def descriptor_type_rank(descriptor_id: str) -> int:
    if descriptor_id.startswith("D"):
        return 0
    if descriptor_id.startswith("C"):
        return 1
    return 2


def source_rank(source: str) -> int:
    parts = source.split(":", 2)
    if len(parts) < 2:
        return 99
    source_type, match = parts[0], parts[1]
    priorities = {
        ("descriptor", "exact"): 0,
        ("term", "exact"): 1,
        ("descriptor", "startswith"): 2,
        ("term", "startswith"): 3,
        ("descriptor", "contains"): 4,
        ("term", "contains"): 5,
    }
    return priorities.get((source_type, match), 99)


def candidate_sort_key(
    item: tuple[str, dict[str, object]],
    candidate_sources: defaultdict[str, list[str]],
    label_positions: dict[str, int],
) -> tuple[int, int, int, int, str]:
    descriptor_id, candidate = item
    sources = set(candidate_sources[descriptor_id])
    best_source = min((source_rank(source) for source in sources), default=99)
    label_position = label_positions.get(normalized_label(candidate.get("label", "")), 999)
    return (
        best_source,
        descriptor_type_rank(descriptor_id),
        label_position,
        -len(sources),
        normalized_label(candidate.get("label", "")),
    )


def assemble_candidates(
    candidates: dict[str, dict[str, object]],
    candidate_sources: "defaultdict[str, list[str]]",
    labels_normalized: dict[str, int],
    details_map: dict[str, object],
    details_skipped_ids: set[str],
) -> list[dict[str, object]]:
    """Project the accumulated candidate state into the ranked candidate list. Safe to call at any
    point during a sweep (for checkpoints) and at the end."""
    candidate_list = []
    for descriptor_id, candidate in sorted(
        candidates.items(),
        key=lambda item: candidate_sort_key(item, candidate_sources, labels_normalized),
    ):
        entry = dict(candidate)
        entry["sources"] = sorted(set(candidate_sources[descriptor_id]))
        if descriptor_id in details_map:
            entry["details"] = details_map[descriptor_id]
        elif descriptor_id in details_skipped_ids:
            entry["details_skipped"] = "Detail lookup skipped by --max-detail-candidates budget."
        candidate_list.append(entry)
    return candidate_list


def add_candidate_provenance(candidate: dict[str, object], marker: object) -> None:
    if not isinstance(marker, dict):
        return
    values = candidate.setdefault("provenance", [])
    if not isinstance(values, list):
        return
    copied = dict(marker)
    if copied not in values:
        values.append(copied)


def build_sweep_result(
    *,
    concept: str,
    variants: list[str],
    matches: list[str],
    labels: list[str],
    candidate_list: list[dict[str, object]],
    raw_searches: list[dict[str, object]],
    status: str,
    stop_reason: str | None,
    pending: list[dict[str, str]],
    errors: list[dict[str, object]],
    max_seconds: float,
    elapsed_seconds: float,
    max_term_descriptor_lookups: int,
    term_descriptor_lookup_count: int,
    term_descriptor_lookup_skipped: int,
    pending_term_descriptor_lookups: list[dict[str, str]],
    max_detail_candidates: int,
    detail_candidate_count: int,
    detail_candidate_skipped: int,
    pending_detail_descriptors: list[str],
    transport_metrics: dict[str, int | float],
) -> dict[str, object]:
    """Assemble the full sweep result dict, including the completeness/recall accounting. The same
    shape is used for on-disk checkpoints and the final returned result."""
    units_total = len(matches) * len(labels)
    units_pending = len(pending)
    review_required: list[str] = []
    if status != "complete":
        review_required.append(
            f"Sweep is PARTIAL (stop_reason={stop_reason}): MeSH/entry-term recall is incomplete. "
            "Rerun the labels in `pending`, unresolved term mappings, pending detail descriptors, "
            "and any failed labels in `errors` (a separate sweep is fine), then merge candidates "
            "before finalizing the concept block. Do not treat these candidates as a complete MeSH layer."
        )
    review_required.extend(
        [
            "Inspect each plausible candidate descriptor with details before selecting MeSH terms.",
            "Check entry terms for [tiab] expansion.",
            "Check related descriptors and tree context before deciding explosion/noexp.",
            "Test accepted and rejected candidate descriptors in PubMed with --retmax 0.",
            "Document rejected descriptors with reason: too broad, too narrow, wrong sense, obsolete, duplicate, or noisy.",
        ]
    )
    backend_provenance: list[dict[str, object]] = []
    for candidate in candidate_list:
        values = candidate.get("provenance", [])
        if not isinstance(values, list):
            continue
        for marker in values:
            if isinstance(marker, dict) and marker not in backend_provenance:
                backend_provenance.append(dict(marker))
    if any(item.get("fidelity") == "reduced" for item in backend_provenance):
        review_required.insert(
            0,
            "Some candidates use reduced-fidelity E-utilities metadata. Confirm preferred headings, entry terms, "
            "qualifiers, and tree context against MeSH RDF before accepting or rejecting them."
        )
    return {
        "operation": "sweep",
        "concept": concept,
        "variants": variants,
        "matches_used": matches,
        "status": status,
        "stop_reason": stop_reason,
        "coverage": {
            "labels_total": len(labels),
            "matches_total": len(matches),
            "units_total": units_total,
            "units_processed": units_total - units_pending,
            "units_pending": units_pending,
        },
        "pending": pending,
        "pending_term_descriptor_lookups": pending_term_descriptor_lookups,
        "pending_detail_descriptors": pending_detail_descriptors,
        "errors": errors,
        "max_seconds": max_seconds,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "candidate_ranking": "Sorted by match specificity, direct descriptor hits before term-derived hits, MeSH descriptors before supplementary concepts, then query-label order and label.",
        "candidate_count": len(candidate_list),
        "candidates": candidate_list,
        "backend_provenance": backend_provenance,
        "raw_searches": raw_searches,
        "network_budget": {
            "request_cache_entries": len(REQUEST_CACHE),
            "max_term_descriptor_lookups": max_term_descriptor_lookups,
            "term_descriptor_lookups_used": term_descriptor_lookup_count,
            "term_descriptor_lookups_skipped": term_descriptor_lookup_skipped,
            "max_detail_candidates": max_detail_candidates,
            "detail_candidates_used": detail_candidate_count,
            "detail_candidates_skipped": detail_candidate_skipped,
            "transport": transport_metrics,
            "persistent_cache_enabled": cache_enabled(),
            "persistent_cache_dir": str(mesh_cache_dir()),
            "rate_limit_requests_per_second": env_float("MESH_RATE_LIMIT", DEFAULT_RATE_LIMIT),
            "eutils_rate_limit_requests_per_second": eutils_rate_limit(),
            "circuit": circuit_status(),
        },
        "review_required": review_required,
    }


def sweep(
    concept: str,
    variants: list[str],
    limit: int,
    include_details: bool,
    max_term_descriptor_lookups: int,
    max_detail_candidates: int,
    max_seconds: float = 0.0,
    output_path: str | None = None,
    backend: str | None = None,
) -> dict[str, object]:
    """Aggressively search MeSH descriptors and entry terms for a concept plus variants.

    Hardened for long variant lists: a wall-clock budget (``max_seconds``; 0 = unlimited) bounds the
    run, per-request failures are recorded and skipped instead of aborting, and (when ``output_path``
    is set) a checkpoint is written after each label so a killed process still leaves useful partial
    output. A shortened run is always explicit (``status="partial"`` + the unswept ``pending`` units
    and any ``errors``) so recall is never silently reduced.
    """
    labels: list[str] = []
    for value in [concept, *variants]:
        cleaned = " ".join(value.split())
        if cleaned and cleaned.lower() not in {item.lower() for item in labels}:
            labels.append(cleaned)

    labels_normalized = {normalized_label(label): index for index, label in enumerate(labels)}
    matches = ["exact", "startswith", "contains"]
    units = [(match, label) for match in matches for label in labels]
    raw_searches: list[dict[str, object]] = []
    candidates: dict[str, dict[str, object]] = {}
    candidate_sources: defaultdict[str, list[str]] = defaultdict(list)
    term_descriptor_lookup_count = 0
    term_descriptor_lookup_skipped = 0
    pending_term_descriptor_lookups: list[dict[str, str]] = []
    seen_term_resources: set[str] = set()
    errors: list[dict[str, object]] = []
    details_map: dict[str, object] = {}
    details_skipped_ids: set[str] = set()
    pending_detail_descriptors: list[str] = []
    circuit_interrupted = False
    transport_metrics_start = metrics_snapshot()

    start = time.monotonic()
    deadline = start + max_seconds if max_seconds and max_seconds > 0 else None
    time_budget_hit = False
    pending: list[dict[str, str]] = []

    def elapsed() -> float:
        return time.monotonic() - start

    def budget_exceeded() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def snapshot(status: str, stop_reason: str | None, pending_units: list[dict[str, str]]) -> dict[str, object]:
        return build_sweep_result(
            concept=concept,
            variants=variants,
            matches=matches,
            labels=labels,
            candidate_list=assemble_candidates(
                candidates, candidate_sources, labels_normalized, details_map, details_skipped_ids
            ),
            raw_searches=raw_searches,
            status=status,
            stop_reason=stop_reason,
            pending=pending_units,
            errors=errors,
            max_seconds=max_seconds,
            elapsed_seconds=elapsed(),
            max_term_descriptor_lookups=max_term_descriptor_lookups,
            term_descriptor_lookup_count=term_descriptor_lookup_count,
            term_descriptor_lookup_skipped=term_descriptor_lookup_skipped,
            pending_term_descriptor_lookups=pending_term_descriptor_lookups,
            max_detail_candidates=max_detail_candidates,
            detail_candidate_count=len(details_map),
            detail_candidate_skipped=len(details_skipped_ids),
            pending_detail_descriptors=pending_detail_descriptors,
            transport_metrics=metrics_delta(transport_metrics_start),
        )

    def checkpoint(status: str, stop_reason: str | None, pending_units: list[dict[str, str]]) -> None:
        if output_path:
            dump_json_to_path(Path(output_path), snapshot(status, stop_reason, pending_units))

    # Search phase: highest-value matches first (exact, then startswith, then contains) so a
    # time-truncated run still captures the best descriptors. One failing label never aborts the run.
    for index, (match, label) in enumerate(units):
        if budget_exceeded():
            time_budget_hit = True
            pending = [{"match": m, "label": l} for (m, l) in units[index:]]
            break

        try:
            descriptor_result = lookup(label, match, limit, backend=backend)
            raw_searches.append(
                {
                    "source": "descriptor",
                    "label": label,
                    "match": match,
                    "results": descriptor_result.get("results", []),
                }
            )
            for item in descriptor_result.get("results", []):
                if not isinstance(item, dict):
                    continue
                resource = str(item.get("resource", ""))
                if not resource:
                    continue
                descriptor_id = resource_id(resource)
                candidate = candidates.setdefault(
                    descriptor_id,
                    {
                        "descriptor": descriptor_id,
                        "resource": resource,
                        "label": item.get("label", ""),
                    },
                )
                add_candidate_provenance(candidate, item.get("provenance"))
                candidate_sources[descriptor_id].append(f"descriptor:{match}:{label}")
        except CircuitOpenError as exc:
            circuit_interrupted = True
            pending = [{"match": m, "label": l} for (m, l) in units[index:]]
            errors.append(
                {"source": "transport", "code": "circuit_open", "match": match, "label": label, "message": str(exc)}
            )
            break
        except MeshError as exc:
            errors.append({"source": "descriptor", "match": match, "label": label, "message": str(exc)})

        try:
            term_result = terms(label, match, limit, backend=backend)
            raw_searches.append(
                {
                    "source": "term",
                    "label": label,
                    "match": match,
                    "results": term_result.get("results", []),
                }
            )
            for item in term_result.get("results", []):
                if not isinstance(item, dict):
                    continue
                direct_descriptor = str(item.get("descriptor", ""))
                if direct_descriptor:
                    candidate = candidates.setdefault(
                        direct_descriptor,
                        {
                            "descriptor": direct_descriptor,
                            "resource": str(item.get("descriptor_resource", mesh_resource(direct_descriptor))),
                            "label": item.get("descriptor_label", ""),
                        },
                    )
                    add_candidate_provenance(candidate, item.get("provenance"))
                    candidate_sources[direct_descriptor].append(
                        f"term:{match}:{label}:{item.get('label', '')}"
                    )
                    continue
                term_resource = str(item.get("resource", ""))
                if not term_resource:
                    continue
                if term_resource in seen_term_resources:
                    do_lookup = True
                elif term_descriptor_lookup_count < max_term_descriptor_lookups:
                    seen_term_resources.add(term_resource)
                    term_descriptor_lookup_count += 1
                    do_lookup = True
                else:
                    term_descriptor_lookup_skipped += 1
                    pending_item = {
                        "term_resource": term_resource,
                        "match": match,
                        "label": label,
                        "term_label": str(item.get("label") or ""),
                    }
                    if pending_item not in pending_term_descriptor_lookups:
                        pending_term_descriptor_lookups.append(pending_item)
                    do_lookup = False
                if not do_lookup:
                    continue
                try:
                    descriptor_hits = term_descriptor_candidates(
                        term_resource,
                        limit=10,
                        term_label=str(item.get("label") or ""),
                        backend=backend,
                    )
                except CircuitOpenError:
                    raise
                except MeshError as exc:
                    errors.append(
                        {
                            "source": "term_descriptor",
                            "match": match,
                            "label": label,
                            "term_resource": term_resource,
                            "message": str(exc),
                        }
                    )
                    continue
                for descriptor_hit in descriptor_hits:
                    descriptor_id = descriptor_hit["descriptor"]
                    candidate = candidates.setdefault(
                        descriptor_id,
                        {
                            "descriptor": descriptor_id,
                            "resource": descriptor_hit["resource"],
                            "label": descriptor_hit["label"],
                        },
                    )
                    add_candidate_provenance(candidate, descriptor_hit.get("provenance"))
                    candidate_sources[descriptor_id].append(
                        f"term:{match}:{label}:{item.get('label', '')}"
                    )
        except CircuitOpenError as exc:
            circuit_interrupted = True
            pending = [{"match": m, "label": l} for (m, l) in units[index:]]
            errors.append(
                {"source": "transport", "code": "circuit_open", "match": match, "label": label, "message": str(exc)}
            )
            break
        except MeshError as exc:
            errors.append({"source": "term", "match": match, "label": label, "message": str(exc)})

        checkpoint("partial", "in_progress", [{"match": m, "label": l} for (m, l) in units[index + 1 :]])

    # Detail phase: enrich ranked candidates within the same wall-clock and count budgets.
    ordered_detail_ids = [
        descriptor_id
        for descriptor_id, _candidate in sorted(
            candidates.items(),
            key=lambda item: candidate_sort_key(item, candidate_sources, labels_normalized),
        )
    ]
    eligible_detail_ids = ordered_detail_ids[:max_detail_candidates]
    if include_details:
        details_skipped_ids.update(ordered_detail_ids[max_detail_candidates:])
        if circuit_interrupted or time_budget_hit:
            pending_detail_descriptors.extend(eligible_detail_ids)
        elif not time_budget_hit:
            for detail_index, descriptor_id in enumerate(eligible_detail_ids):
                if budget_exceeded():
                    time_budget_hit = True
                    pending_detail_descriptors.extend(eligible_detail_ids[detail_index:])
                    break
                try:
                    detail_result = details(
                        descriptor_id,
                        "terms,seealso,qualifiers",
                        backend=backend,
                    )
                    details_map[descriptor_id] = detail_result.get("details", {})
                    candidate = candidates.get(descriptor_id)
                    if candidate is not None:
                        add_candidate_provenance(candidate, detail_result.get("provenance"))
                except CircuitOpenError as exc:
                    circuit_interrupted = True
                    pending_detail_descriptors.extend(eligible_detail_ids[detail_index:])
                    errors.append(
                        {
                            "source": "transport",
                            "code": "circuit_open",
                            "descriptor": descriptor_id,
                            "message": str(exc),
                        }
                    )
                    break
                except MeshError as exc:
                    errors.append({"source": "details", "descriptor": descriptor_id, "message": str(exc)})
                checkpoint("partial", "in_progress", pending)

    reasons = []
    if time_budget_hit:
        reasons.append("time_budget")
    if circuit_interrupted:
        reasons.append("circuit_open")
    if any(error.get("code") != "circuit_open" for error in errors):
        reasons.append("request_errors")
    if pending_term_descriptor_lookups:
        reasons.append("term_descriptor_lookup_budget")
    stop_reason = "+".join(reasons) if reasons else None
    status = "partial" if (reasons or pending) else "complete"

    result = snapshot(status, stop_reason, pending)
    checkpoint(status, stop_reason, pending)
    return result


def sparql(
    query: str,
    limit: int,
    offset: int,
    inference: bool,
    *,
    backend: str | None = None,
) -> dict[str, object]:
    # Internal RDF helpers call this without a backend. CLI callers pass their resolved choice.
    if backend is not None and selected_backend(backend) == "eutils":
        raise MeshError("The MeSH SPARQL command is RDF-only in Phase 2; use --backend rdf or auto.")
    data = request_json(
        SPARQL_URL,
        {
            "query": query,
            "format": "JSON",
            "limit": str(limit),
            "offset": str(offset),
            "inference": "true" if inference else "false",
        },
    )
    return {
        "operation": "sparql",
        "query": query,
        "limit": limit,
        "offset": offset,
        "inference": inference,
        "results": data,
    }


def write_json(data: dict[str, object]) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def dump_json_to_path(path: Path, data: dict[str, object]) -> None:
    """Write the full result JSON to a file (used by sweep --output and checkpoints). Overwrites."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def summarize_sweep(result: dict[str, object]) -> dict[str, object]:
    """Compact, token-cheap projection of a full sweep result for stdout.

    Keeps everything recall-relevant (ranked candidate descriptors + their sources, completeness
    status, the unswept ``pending`` units, errors, and the network budget) but drops the bulky
    ``raw_searches`` echo and the per-candidate ``details`` blobs, which remain in the --output file.
    """
    candidates = []
    for cand in result.get("candidates", []) or []:
        if not isinstance(cand, dict):
            continue
        compact = {
            "descriptor": cand.get("descriptor"),
            "label": cand.get("label"),
            "sources": cand.get("sources", []),
        }
        if "details" in cand:
            compact["details_available"] = True
        if "details_skipped" in cand:
            compact["details_skipped"] = cand["details_skipped"]
        candidates.append(compact)

    errors = result.get("errors", []) or []
    summary: dict[str, object] = {
        "operation": "sweep",
        "concept": result.get("concept"),
        "status": result.get("status"),
        "stop_reason": result.get("stop_reason"),
        "coverage": result.get("coverage"),
        "candidate_count": result.get("candidate_count"),
        "candidates": candidates,
        "network_budget": result.get("network_budget"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "max_seconds": result.get("max_seconds"),
        "error_count": len(errors),
    }
    if result.get("pending"):
        summary["pending"] = result["pending"]
    if result.get("pending_term_descriptor_lookups"):
        summary["pending_term_descriptor_lookups"] = result["pending_term_descriptor_lookups"]
    if result.get("pending_detail_descriptors"):
        summary["pending_detail_descriptors"] = result["pending_detail_descriptors"]
    if errors:
        summary["errors"] = errors[:5]
        if len(errors) > 5:
            summary["errors_truncated_total"] = len(errors)
    if result.get("status") != "complete":
        review = result.get("review_required") or []
        if review:
            summary["review_required"] = [review[0]]
    return summary


def emit_sweep(result: dict[str, object], args: argparse.Namespace) -> None:
    """Serialize a sweep result: full JSON to --output; compact summary to stdout when --summary or
    --output is given; otherwise the full JSON to stdout (backward-compatible default)."""
    output_path = getattr(args, "output", None)
    pending_output_path = getattr(args, "pending_output", None)
    if output_path:
        dump_json_to_path(Path(output_path), result)
    if pending_output_path:
        write_pending_labels(Path(pending_output_path), result)
    if getattr(args, "summary", False) or output_path or pending_output_path:
        summary = summarize_sweep(result)
        if output_path:
            summary["output"] = str(output_path)
        if pending_output_path:
            summary["pending_output"] = str(pending_output_path)
        write_json(summary)
    else:
        write_json(result)


def write_pending_labels(path: Path, result: dict[str, object]) -> None:
    """Write newline-delimited labels that still need a follow-up sweep.

    The file is intentionally compatible with ``--variants-file``. The original concept is omitted
    because it is already supplied via ``--concept`` on the rerun.
    """
    concept = normalized_label(result.get("concept", ""))
    labels: list[str] = []
    for item in result.get("pending", []) or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        if not label or normalized_label(label) == concept:
            continue
        if label.casefold() not in {existing.casefold() for existing in labels}:
            labels.append(label)
    lines = [
        "# Pending MeSH sweep labels from a partial run.",
        "# Rerun with the same --concept and pass this file via --variants-file.",
    ]
    if labels:
        lines.extend(labels)
    else:
        lines.append("# No pending non-concept labels.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MeSH RDF helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_cache_bypass_flag(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--no-cache",
            action="store_true",
            help="Bypass both memory and persistent MeSH response caches for this command.",
        )

    def add_backend_flag(command_parser: argparse.ArgumentParser, *, rdf_only: bool = False) -> None:
        command_parser.add_argument(
            "--backend",
            choices=sorted(BACKEND_NAMES),
            help=(
                "MeSH metadata backend (default: MESH_BACKEND or auto). "
                + (
                    "This command remains RDF-only; eutils is rejected."
                    if rdf_only
                    else "Auto uses RDF first, then E-utilities only after eligible availability failures."
                )
            ),
        )

    lookup_parser = subparsers.add_parser("lookup", help="Search MeSH descriptors by label.")
    add_cache_bypass_flag(lookup_parser)
    add_backend_flag(lookup_parser)
    lookup_parser.add_argument("--label", required=True)
    lookup_parser.add_argument("--match", choices=["exact", "contains", "startswith"], default="contains")
    lookup_parser.add_argument("--limit", type=int, default=10)

    details_parser = subparsers.add_parser("details", help="Fetch descriptor details.")
    add_cache_bypass_flag(details_parser)
    add_backend_flag(details_parser)
    details_parser.add_argument("--descriptor", required=True)
    details_parser.add_argument("--include", default="terms,seealso,qualifiers")

    terms_parser = subparsers.add_parser("terms", help="Search MeSH entry terms.")
    add_cache_bypass_flag(terms_parser)
    add_backend_flag(terms_parser)
    terms_parser.add_argument("--label", required=True)
    terms_parser.add_argument("--match", choices=["exact", "contains", "startswith"], default="contains")
    terms_parser.add_argument("--limit", type=int, default=10)

    tree_parser = subparsers.add_parser("tree", help="Fetch descriptor tree context, scope, entry terms, siblings, descendants, and SCR mapping.")
    add_cache_bypass_flag(tree_parser)
    add_backend_flag(tree_parser, rdf_only=True)
    tree_parser.add_argument("--descriptor", required=True)
    tree_parser.add_argument("--max-descendants", type=int, default=DEFAULT_MAX_TREE_DESCENDANTS)
    tree_parser.add_argument("--max-siblings", type=int, default=DEFAULT_MAX_TREE_SIBLINGS)

    sweep_parser = subparsers.add_parser("sweep", help="Aggressively search MeSH descriptors and entry terms for a concept plus variants.")
    add_cache_bypass_flag(sweep_parser)
    add_backend_flag(sweep_parser)
    sweep_parser.add_argument("--concept", required=True)
    sweep_parser.add_argument("--variant", action="append", default=[], help="Additional synonym/acronym/spelling/seed term. Repeat as needed.")
    sweep_parser.add_argument("--variants-file", help="Optional newline-delimited variants file. Use '-' for stdin.")
    sweep_parser.add_argument("--limit", type=int, default=20)
    sweep_parser.add_argument("--details", action="store_true", help="Fetch details for every candidate descriptor.")
    sweep_parser.add_argument(
        "--max-term-descriptor-lookups",
        type=int,
        default=DEFAULT_MAX_TERM_DESCRIPTOR_LOOKUPS,
        help="Maximum unique term-to-descriptor SPARQL lookups during sweep.",
    )
    sweep_parser.add_argument(
        "--max-detail-candidates",
        type=int,
        default=DEFAULT_MAX_DETAIL_CANDIDATES,
        help="Maximum candidate descriptors to enrich when --details is used.",
    )
    sweep_parser.add_argument(
        "--max-seconds",
        type=float,
        default=DEFAULT_SWEEP_MAX_SECONDS,
        help="Wall-clock budget for the whole sweep (0 = unlimited). On timeout the sweep stops and "
        "returns status=partial with the unswept labels listed in `pending`.",
    )
    sweep_parser.add_argument(
        "--output",
        help="Write the full sweep JSON (including raw_searches and per-candidate details) to this "
        "path, checkpointing after each label, and print a compact summary to stdout. Recommended "
        "for long variant lists.",
    )
    sweep_parser.add_argument(
        "--pending-output",
        help="Write newline-delimited pending variant labels from a partial run; compatible with --variants-file on a rerun.",
    )
    sweep_parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact summary to stdout (drops raw_searches and per-candidate details). "
        "Implied by --output.",
    )

    sparql_parser = subparsers.add_parser("sparql", help="Run a MeSH RDF SPARQL query.")
    add_cache_bypass_flag(sparql_parser)
    add_backend_flag(sparql_parser, rdf_only=True)
    sparql_parser.add_argument("query")
    sparql_parser.add_argument("--limit", type=int, default=100)
    sparql_parser.add_argument("--offset", type=int, default=0)
    sparql_parser.add_argument("--inference", action="store_true")

    cache_parser = subparsers.add_parser("cache", help="Inspect or clear the persistent MeSH RDF response cache.")
    cache_parser.add_argument("action", choices=["stats", "clear"])

    circuit_parser = subparsers.add_parser("circuit", help="Inspect or reset the MeSH RDF circuit breaker.")
    circuit_parser.add_argument("action", choices=["status", "reset"])
    circuit_parser.add_argument("--host", default="id.nlm.nih.gov")

    return parser


def main(argv: list[str] | None = None) -> int:
    global CACHE_BYPASS
    parser = build_parser()
    args = parser.parse_args(argv)
    CACHE_BYPASS = bool(getattr(args, "no_cache", False))

    try:
        if args.command == "lookup":
            write_json(lookup(args.label, args.match, args.limit, backend=args.backend))
        elif args.command == "details":
            write_json(details(args.descriptor, args.include, backend=args.backend))
        elif args.command == "terms":
            write_json(terms(args.label, args.match, args.limit, backend=args.backend))
        elif args.command == "tree":
            write_json(tree(args.descriptor, max(0, args.max_descendants), max(0, args.max_siblings), backend=args.backend))
        elif args.command == "sweep":
            variants = list(args.variant)
            if args.variants_file:
                variants.extend(read_lines(args.variants_file))
            result = sweep(
                args.concept,
                variants,
                args.limit,
                args.details,
                max(0, args.max_term_descriptor_lookups),
                max(0, args.max_detail_candidates),
                max_seconds=max(0.0, args.max_seconds),
                output_path=args.output,
                backend=args.backend,
            )
            emit_sweep(result, args)
        elif args.command == "sparql":
            write_json(
                sparql(
                    args.query,
                    args.limit,
                    args.offset,
                    args.inference,
                    backend=selected_backend(args.backend),
                )
            )
        elif args.command == "cache":
            write_json(cache_stats() if args.action == "stats" else clear_cache())
        elif args.command == "circuit":
            write_json(circuit_status(args.host) if args.action == "status" else reset_circuit(args.host))
        else:
            parser.error(f"Unknown command: {args.command}")
    except MeshError as exc:
        write_json({"error": str(exc)})
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
