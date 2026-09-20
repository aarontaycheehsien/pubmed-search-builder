"""Conservative path checks for managed package and cache directories."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def is_link(path: Path) -> bool:
    """Include Windows junctions on Python versions without Path.is_junction."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def checked_directory(path: Path, *, protected: tuple[Path, ...] = ()) -> Path:
    absolute = Path(os.path.abspath(path.expanduser()))
    for part in (absolute, *absolute.parents):
        if is_link(part):
            raise ValueError(f"Refusing a directory reached through a link or junction: {part}")
    resolved = absolute.resolve()
    if any(part.casefold() == ".git" for part in resolved.parts):
        raise ValueError(f"Refusing a location inside Git metadata: {resolved}")
    if resolved == Path(resolved.anchor):
        raise ValueError(f"Refusing a filesystem root: {resolved}")
    for target in (Path.home().resolve(), *[p.resolve() for p in protected]):
        if resolved == target or resolved in target.parents:
            raise ValueError(f"Directory contains a protected location: {resolved} ({target})")
    if (resolved / ".git").exists():
        raise ValueError(f"Refusing a Git repository or worktree: {resolved}")
    if (resolved / "HEAD").is_file() and (resolved / "objects").is_dir() and (resolved / "refs").is_dir():
        raise ValueError(f"Refusing a bare Git repository: {resolved}")
    return resolved


def reject_tree_links_and_git(root: Path) -> None:
    """Inspect without following directory links, including junctions."""
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(parent) / name
            if name == ".git" or is_link(path):
                raise ValueError(f"Refusing Git metadata or a linked entry: {path}")
