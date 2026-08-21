#!/usr/bin/env python3
"""Fail when source control contains ignored artifacts, personal paths, or oversized files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_TRACKED_BYTES = 5 * 1024 * 1024
PERSONAL_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"'`]+"),
    re.compile(r"(?i)(?:^|[\s(])/(?:Users|home)/[^/\s\"'`)]+"),
    re.compile(r"(?i)\bC--Users-[A-Za-z0-9._-]+"),
)


def git_output(root: Path, *args: str) -> bytes:
    command = [
        "git",
        "-c",
        f"safe.directory={root.as_posix()}",
        "-C",
        str(root),
        *args,
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout


def nul_paths(payload: bytes) -> list[str]:
    return [item.decode("utf-8", errors="surrogateescape") for item in payload.split(b"\0") if item]


def tracked_paths(root: Path) -> list[str]:
    return nul_paths(git_output(root, "ls-files", "-z"))


def ignored_tracked_paths(root: Path) -> list[str]:
    return nul_paths(git_output(root, "ls-files", "--cached", "--ignored", "--exclude-standard", "-z"))


def personal_path_files(root: Path, paths: list[str]) -> list[str]:
    matches: list[str] = []
    for relative in paths:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw:
            continue
        text = raw.decode("utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in PERSONAL_PATH_PATTERNS):
            matches.append(relative)
    return matches


def oversized_tracked_files(
    root: Path,
    paths: list[str],
    *,
    max_bytes: int = DEFAULT_MAX_TRACKED_BYTES,
) -> list[tuple[str, int]]:
    matches: list[tuple[str, int]] = []
    for relative in paths:
        path = root / relative
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > max_bytes:
            matches.append((relative, size))
    return matches


def assess_repository(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    paths = tracked_paths(root)
    issues = [f"tracked file matches .gitignore: {path}" for path in ignored_tracked_paths(root)]
    issues.extend(f"tracked text contains a personal absolute path: {path}" for path in personal_path_files(root, paths))
    issues.extend(
        f"tracked file exceeds {DEFAULT_MAX_TRACKED_BYTES // (1024 * 1024)} MiB: {path} ({size} bytes)"
        for path, size in oversized_tracked_files(root, paths)
    )
    return sorted(issues)


def main() -> int:
    try:
        issues = assess_repository()
    except RuntimeError as exc:
        print(f"repository hygiene check failed to run: {exc}", file=sys.stderr)
        return 2
    if issues:
        print("repository hygiene check failed:", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    print("repository hygiene check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
