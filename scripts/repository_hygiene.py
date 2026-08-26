#!/usr/bin/env python3
"""Check tracked source for ignored artifacts, personal paths, and oversized files."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKED_BYTES = 5 * 1024 * 1024
PERSONAL_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"'`]+"),
    re.compile(r"(?i)(?:^|[\s(])/(?:Users|home)/[^/\s\"'`)]+"),
    re.compile(r"(?i)\bC" + r"--Users-[A-Za-z0-9._-]+"),
)


def git_output(*args: str) -> bytes:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "-C", str(ROOT), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def nul_paths(payload: bytes) -> list[str]:
    return [item.decode("utf-8", errors="surrogateescape") for item in payload.split(b"\0") if item]


def assess_repository() -> list[str]:
    tracked = nul_paths(git_output("ls-files", "-z"))
    ignored = set(nul_paths(git_output("ls-files", "--cached", "--ignored", "--exclude-standard", "-z")))
    issues = [f"tracked file matches .gitignore: {path}" for path in sorted(ignored)]
    for relative in tracked:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        try:
            size = path.stat().st_size
            raw = path.read_bytes()
        except OSError:
            continue
        if size > MAX_TRACKED_BYTES:
            issues.append(f"tracked file exceeds 5 MiB: {relative} ({size} bytes)")
        if b"\0" not in raw:
            text = raw.decode("utf-8", errors="ignore")
            if any(pattern.search(text) for pattern in PERSONAL_PATH_PATTERNS):
                issues.append(f"tracked text contains a personal absolute path: {relative}")
    return sorted(set(issues))


def main() -> int:
    try:
        issues = assess_repository()
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "operation": "repository-hygiene", "error": str(exc)}))
        return 2
    print(json.dumps({"ok": not issues, "operation": "repository-hygiene", "issues": issues}, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
