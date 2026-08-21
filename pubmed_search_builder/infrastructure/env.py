"""Trusted configuration loading for the PubMed and MeSH command-line tools."""

from __future__ import annotations

import os
import re
from pathlib import Path


DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
ALLOWED_FILE_VARIABLES = frozenset(
    {
        "MESH_BACKEND",
        "MESH_CACHE",
        "MESH_CACHE_DIR",
        "MESH_CACHE_TTL_DAYS",
        "MESH_CIRCUIT_COOLDOWN",
        "MESH_CIRCUIT_MAX_COOLDOWN",
        "MESH_CIRCUIT_THRESHOLD",
        "MESH_RATE_LIMIT",
        "MESH_THROTTLE_RETRIES",
        "MESH_TRANSIENT_RETRIES",
        "NCBI_API_KEY",
        "NCBI_CACHE",
        "NCBI_CACHE_DIR",
        "NCBI_CACHE_TTL_HOURS",
        "NCBI_EMAIL",
        "NCBI_RECORD_CACHE_TTL_DAYS",
        "NCBI_TOOL",
    }
)

_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_configured_env_file: Path | None = None
_env_file_cache: dict[str, str] | None = None


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse allowlisted values from ``path`` without evaluating or interpolating them."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}

    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY_PATTERN.fullmatch(key) or key not in ALLOWED_FILE_VARIABLES:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def configure_env_file(path: str | Path | None) -> Path | None:
    """Select an explicit env file, or restore the trusted skill-root default with ``None``."""
    global _configured_env_file, _env_file_cache
    if path is None:
        _configured_env_file = None
    else:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(f"Environment file does not exist or is not a file: {resolved}")
        _configured_env_file = resolved
    _env_file_cache = None
    return _configured_env_file


def active_env_file() -> Path:
    """Return the explicit env file or the trusted file beside the installed skill."""
    return _configured_env_file or DEFAULT_ENV_FILE


def reset_env_file_cache() -> None:
    """Clear cached file values; intended for tests and explicit configuration changes."""
    global _env_file_cache
    _env_file_cache = None


def env_file_values() -> dict[str, str]:
    """Return cached values from the one trusted env file; never inspect the CWD implicitly."""
    global _env_file_cache
    if _env_file_cache is None:
        _env_file_cache = parse_env_file(active_env_file())
    return _env_file_cache


def read_env(name: str, default: str = "") -> str:
    """Read process configuration first, then the trusted env file, then Windows user env."""
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
