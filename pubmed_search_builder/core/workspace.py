"""Run-workspace anchoring: resolve artifact references against a run root, never the CWD.

Two failure modes motivate this module.

1. **CWD-relative resolution.** Manifests, critic rounds, and ledgers store artifact
   references as bare filenames (``critic_round_1.json``). Resolving those with
   ``Path(value).is_file()`` tests them against the *process* working directory, so a
   leftover file from an unrelated build silently satisfies the lookup and becomes
   evidence for the current run. :func:`resolve_within` resolves only inside a declared
   run root and returns ``None`` rather than reaching outside it.

2. **Builds run inside the skill installation.** The bundled scripts write their
   ``--output`` artifacts relative to the CWD, so a build started from the skill
   directory scatters run state across the installation, where (1) can then pick it up.
   :func:`guard_run_workspace` refuses to start build state there and points at a run
   workspace instead.
"""

from __future__ import annotations

import os
from pathlib import Path

ALLOW_SKILL_ROOT_ENV = "PUBMED_SEARCH_BUILDER_ALLOW_SKILL_ROOT"


class WorkspaceError(ValueError):
    """A path escapes its run workspace, or build state would land in the skill install."""


def skill_root() -> Path:
    """The installed skill directory (the parent of the ``pubmed_search_builder`` package)."""

    return Path(__file__).resolve().parents[2]


def is_within(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` itself or lives underneath it."""

    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def resolve_within(
    root: Path | str,
    value: Path | str,
    *,
    must_exist: bool = True,
    search: bool = True,
) -> Path | None:
    """Resolve an artifact reference against ``root``.

    ``value`` may be absolute or relative. A relative reference is joined to ``root``;
    the process working directory is never consulted. When the joined path is missing
    and ``search`` is set, the run tree is searched for a file of the same name, taking
    the lexicographically first match so repeated runs resolve identically.

    Returns ``None`` when the reference cannot be satisfied inside ``root`` -- including
    an absolute path that points outside it, which is a reference leaking in from another
    run and never valid evidence for this one.
    """

    root_path = Path(root).resolve()
    raw = Path(value)

    if raw.is_absolute():
        if not is_within(raw, root_path):
            return None
        candidate = raw.resolve()
        if candidate.exists() or not must_exist:
            return candidate
        return None

    candidate = (root_path / raw).resolve()
    if is_within(candidate, root_path) and candidate.exists():
        return candidate
    if not must_exist and is_within(candidate, root_path):
        return candidate
    if not search:
        return None

    matches: list[Path] = []
    for path in root_path.rglob(raw.name):
        if not path.is_file():
            continue
        try:
            resolved_match = path.resolve()
        except OSError:
            continue
        if is_within(resolved_match, root_path):
            matches.append(resolved_match)
    matches.sort()
    return matches[0] if matches else None


def skill_root_override_enabled() -> bool:
    """True when the environment explicitly allows build state in the skill install."""

    return os.environ.get(ALLOW_SKILL_ROOT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def guard_run_workspace(
    path: Path | str,
    *,
    allow_skill_root: bool = False,
    what: str = "build state",
) -> Path:
    """Refuse to create ``what`` directly inside the installed skill directory.

    Returns the resolved path so callers can use it directly. Pass ``allow_skill_root``
    (or set :data:`ALLOW_SKILL_ROOT_ENV`) to override -- useful for the skill's own
    self-tests, not for real builds.
    """

    resolved = Path(path).resolve()
    if allow_skill_root or skill_root_override_enabled():
        return resolved
    if resolved.parent != skill_root():
        return resolved
    raise WorkspaceError(
        f"Refusing to create {what} in the skill installation directory ({skill_root()}). "
        "Run artifacts written there collide across builds and can be picked up as evidence "
        "by a later run. Create a run workspace instead, for example "
        "`--workspace runs/<topic-slug>`, or pass --allow-skill-root to override."
    )


def prepare_workspace(workspace: Path | str | None, target: Path | str) -> Path:
    """Resolve ``target`` inside ``workspace``, creating the workspace directory.

    With no ``workspace`` the target is returned unchanged, preserving the existing
    behaviour of every command that takes a bare ``--manifest`` path.
    """

    if workspace is None:
        return Path(target)
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    candidate = Path(target)
    if candidate.is_absolute():
        if not is_within(candidate, root):
            raise WorkspaceError(f"Path {candidate} is outside the requested workspace {root}")
        return candidate
    return root / candidate
