"""Persistent, workspace-scoped response cache for NCBI E-utilities traffic.

A build re-probes the same queries many times -- block counts, ablations, variant
comparisons, re-fetches of a frozen holdout -- and an eval re-runs whole strategies. Every
one of those was a live E-utilities call paced at 3-10 requests/second.

Two properties this cache must have, beyond being fast:

**Workspace scoping.** The cache lives inside the run workspace, not in a shared user
directory. A count served to build B from a response build A fetched last week would be
a provenance leak of exactly the kind the run-anchoring work removed: the audit says the
number was retrieved on its own date, and it must have been. MeSH RDF is cached globally
by ``mesh_tool.py`` and correctly so -- that vocabulary is a shared reference dataset that
does not belong to a review. PubMed retrieval results do belong to a review.

**Secret hygiene.** ``api_key`` never reaches the cache key or the stored entry. Keying on
it would silently discard the whole cache on key rotation; storing it would write a
credential to disk inside the run workspace.

Freshness is per endpoint. Record content (``efetch``/``esummary``) is effectively stable,
so it carries a long TTL. Counts and links (``esearch``/``elink``) drift as PubMed grows,
so they carry a short one -- and the delivered final count should be taken live via
``--no-cache`` rather than trusted from any cache at all.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from pubmed_search_builder.core.workspace import skill_root
from pubmed_search_builder.infrastructure.transport import SECRET_PARAMETER_NAMES

CACHE_SCHEMA_VERSION = 1
DEFAULT_CACHE_DIRNAME = ".ncbi_cache"

# Parameters that identify the caller rather than the request. Excluding them keeps one
# cache usable across contributors and across an api-key rotation.
NON_IDENTIFYING_PARAMETERS = frozenset({"tool", "email"}) | SECRET_PARAMETER_NAMES

# Record content is effectively immutable; counts and link sets are not.
STABLE_ENDPOINTS = frozenset({"efetch.fcgi", "esummary.fcgi"})
DEFAULT_RECORD_TTL_SECONDS = 30 * 86400.0
DEFAULT_QUERY_TTL_SECONDS = 86400.0

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})


def is_enabled_value(value: str, default: bool = True) -> bool:
    """Interpret an on/off configuration string, falling back to ``default``."""
    cleaned = str(value or "").strip().casefold()
    if cleaned in TRUE_VALUES:
        return True
    if cleaned in FALSE_VALUES:
        return False
    return default


class ResponseCache:
    """File-backed cache of successful E-utilities response bodies.

    A disabled cache is a working no-op object rather than ``None``, so callers never
    branch on cache presence and the reason for disablement stays reportable.
    """

    def __init__(
        self,
        directory: Path | None,
        *,
        enabled: bool = True,
        disabled_reason: str = "",
        record_ttl_seconds: float = DEFAULT_RECORD_TTL_SECONDS,
        query_ttl_seconds: float = DEFAULT_QUERY_TTL_SECONDS,
        clock: "callable[[], float]" = time.time,
    ) -> None:
        self.directory = Path(directory).resolve() if directory is not None else None
        self.enabled = bool(enabled and self.directory is not None)
        self.disabled_reason = disabled_reason if not self.enabled else ""
        self.record_ttl_seconds = float(record_ttl_seconds)
        self.query_ttl_seconds = float(query_ttl_seconds)
        self._clock = clock
        self._counts: Counter[str] = Counter()

    # -- construction -------------------------------------------------------------

    @classmethod
    def disabled(cls, reason: str) -> "ResponseCache":
        return cls(None, enabled=False, disabled_reason=reason)

    @classmethod
    def for_workspace(
        cls,
        *,
        enabled: bool = True,
        directory: str | Path | None = None,
        workspace: str | Path | None = None,
        record_ttl_seconds: float = DEFAULT_RECORD_TTL_SECONDS,
        query_ttl_seconds: float = DEFAULT_QUERY_TTL_SECONDS,
        clock: "callable[[], float]" = time.time,
    ) -> "ResponseCache":
        """Resolve the cache directory for the current run workspace.

        With no explicit directory the cache sits in the working directory, which for a
        build started through ``--workspace`` is that run's own directory: reused across
        commands and sessions for one case, never shared with another.
        """
        if not enabled:
            return cls.disabled("disabled by configuration")
        if directory:
            resolved = Path(directory).expanduser().resolve()
        else:
            root = Path(workspace).resolve() if workspace else Path.cwd().resolve()
            resolved = root / DEFAULT_CACHE_DIRNAME
        if resolved.parent == skill_root():
            # Caching directly in the installation would be shared by every build that ran
            # there, which is precisely the cross-case reuse this cache must not allow.
            return cls.disabled(
                "refusing to cache in the skill installation directory; start the build in a run "
                "workspace (`--workspace runs/<topic-slug>`) or set NCBI_CACHE_DIR"
            )
        return cls(
            resolved,
            record_ttl_seconds=record_ttl_seconds,
            query_ttl_seconds=query_ttl_seconds,
            clock=clock,
        )

    # -- keying -------------------------------------------------------------------

    def identifying_params(self, params: Mapping[str, str]) -> dict[str, str]:
        return {
            str(key): str(value)
            for key, value in params.items()
            if str(key).casefold() not in NON_IDENTIFYING_PARAMETERS
        }

    def cache_key(self, endpoint: str, params: Mapping[str, str]) -> str:
        canonical = json.dumps(
            {
                "schema_version": CACHE_SCHEMA_VERSION,
                "endpoint": str(endpoint),
                "params": sorted(self.identifying_params(params).items()),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def entry_path(self, endpoint: str, params: Mapping[str, str]) -> Path:
        assert self.directory is not None
        digest = self.cache_key(endpoint, params)
        return self.directory / digest[:2] / f"{digest}.json"

    def ttl_seconds_for(self, endpoint: str) -> float:
        return self.record_ttl_seconds if str(endpoint) in STABLE_ENDPOINTS else self.query_ttl_seconds

    # -- read/write ---------------------------------------------------------------

    def get(self, endpoint: str, params: Mapping[str, str]) -> bytes | None:
        if not self.enabled:
            return None
        path = self.entry_path(endpoint, params)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._counts["misses"] += 1
            return None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._counts["unreadable"] += 1
            return None
        if not isinstance(entry, dict) or entry.get("schema_version") != CACHE_SCHEMA_VERSION:
            self._counts["unreadable"] += 1
            return None
        if entry.get("endpoint") != str(endpoint) or entry.get("params") != self.identifying_params(params):
            # A digest collision or a hand-edited entry must never be served as evidence.
            self._counts["unreadable"] += 1
            return None
        fetched = entry.get("fetched_epoch")
        if not isinstance(fetched, (int, float)):
            self._counts["unreadable"] += 1
            return None
        ttl = self.ttl_seconds_for(endpoint)
        if ttl <= 0 or self._clock() - float(fetched) > ttl:
            self._counts["stale"] += 1
            return None
        body = self._decode_body(entry)
        if body is None:
            self._counts["unreadable"] += 1
            return None
        self._counts["hits"] += 1
        return body

    def put(self, endpoint: str, params: Mapping[str, str], body: bytes) -> None:
        if not self.enabled:
            return
        now = self._clock()
        entry: dict[str, object] = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "endpoint": str(endpoint),
            "params": self.identifying_params(params),
            "fetched_epoch": now,
            "fetched_utc": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z"),
            "ttl_seconds": self.ttl_seconds_for(endpoint),
        }
        try:
            entry["body"] = body.decode("utf-8")
            entry["body_encoding"] = "utf-8"
        except UnicodeDecodeError:
            entry["body"] = base64.b64encode(body).decode("ascii")
            entry["body_encoding"] = "base64"
        try:
            self._atomic_write(self.entry_path(endpoint, params), entry)
            self._counts["writes"] += 1
        except OSError:
            self._counts["write_errors"] += 1

    @staticmethod
    def _decode_body(entry: Mapping[str, object]) -> bytes | None:
        body = entry.get("body")
        if not isinstance(body, str):
            return None
        encoding = entry.get("body_encoding")
        try:
            if encoding == "base64":
                return base64.b64decode(body.encode("ascii"), validate=True)
            if encoding == "utf-8":
                return body.encode("utf-8")
        except (ValueError, UnicodeEncodeError):
            return None
        return None

    @staticmethod
    def _atomic_write(path: Path, entry: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(entry, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    # -- reporting ----------------------------------------------------------------

    def stats(self) -> dict[str, object]:
        """Cache activity for this process, for disclosure in saved artifacts."""
        summary: dict[str, object] = {
            "enabled": self.enabled,
            "directory": str(self.directory) if self.directory else None,
            "hits": int(self._counts["hits"]),
            "misses": int(self._counts["misses"]),
            "stale": int(self._counts["stale"]),
            "writes": int(self._counts["writes"]),
        }
        for optional in ("unreadable", "write_errors"):
            if self._counts[optional]:
                summary[optional] = int(self._counts[optional])
        if not self.enabled and self.disabled_reason:
            summary["disabled_reason"] = self.disabled_reason
        return summary

    def served_from_cache(self) -> bool:
        return bool(self._counts["hits"])

    def describe(self) -> dict[str, object]:
        """Stored-entry inventory, for `pubmed_tool.py cache --stats`."""
        info: dict[str, object] = {
            "enabled": self.enabled,
            "directory": str(self.directory) if self.directory else None,
            "record_ttl_days": round(self.record_ttl_seconds / 86400.0, 3),
            "query_ttl_hours": round(self.query_ttl_seconds / 3600.0, 3),
        }
        if not self.enabled:
            info["disabled_reason"] = self.disabled_reason
            return info
        assert self.directory is not None
        entries = 0
        fresh = 0
        bytes_on_disk = 0
        now = self._clock()
        for path in self.directory.rglob("*.json"):
            if not path.is_file():
                continue
            entries += 1
            try:
                bytes_on_disk += path.stat().st_size
                entry = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            fetched = entry.get("fetched_epoch") if isinstance(entry, dict) else None
            ttl = entry.get("ttl_seconds") if isinstance(entry, dict) else None
            if isinstance(fetched, (int, float)) and isinstance(ttl, (int, float)) and now - float(fetched) <= float(ttl):
                fresh += 1
        info.update({"entries": entries, "fresh_entries": fresh, "bytes_on_disk": bytes_on_disk})
        return info

    def clear(self) -> dict[str, object]:
        before = self.describe()
        if self.enabled and self.directory is not None and self.directory.is_dir():
            shutil.rmtree(self.directory, ignore_errors=True)
        return {"cleared": before.get("entries", 0), "directory": before.get("directory")}
