#!/usr/bin/env python3
"""Build a clean deployable pubmed-search-builder skill from the repository source."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pubmed_search_builder.core.filesystem_safety import checked_directory, reject_tree_links_and_git

SKILL_NAME = "pubmed-search-builder"
OWNERSHIP_FILE = ".pubmed-package.json"
RUNTIME_FILES = ("SKILL.md",)
RUNTIME_GLOBS = {
    "agents": ("*.yaml",),
    "references": ("*.md",),
    "schemas": ("*.json",),
    "scripts": ("*.py",),
    "pubmed_search_builder": ("**/*.py",),
}


class PackageError(ValueError):
    pass


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def source_git_info(source: Path) -> tuple[Path | None, str | None]:
    def git(*args: str) -> str:
        result = subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    try:
        common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir"))
        return common, git("rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        if (source / ".git").exists():
            raise PackageError("Cannot resolve the source repository's shared Git directory")
        return None, None


def validate_destination(source: Path, output: Path, common: Path | None, replace: bool) -> Path:
    try:
        output = checked_directory(output, protected=(source, *((common,) if common else ())))
    except ValueError as exc:
        raise PackageError(str(exc)) from exc
    if not (source / "SKILL.md").is_file():
        raise PackageError(f"Source does not contain SKILL.md: {source}")
    if output == source or is_relative_to(source, output):
        raise PackageError("Output cannot be the source directory or one of its parents")
    if is_relative_to(output, source):
        raise PackageError("Output must be outside the source repository to prevent recursive packaging")
    if output.exists() and not replace:
        raise PackageError(f"Output already exists; pass --replace to rebuild it: {output}")
    if output.exists():
        if output.name != SKILL_NAME:
            raise PackageError(f"Refusing to replace a directory not named {SKILL_NAME!r}: {output}")
        try:
            reject_tree_links_and_git(output)
            owner = json.loads((output / OWNERSHIP_FILE).read_text(encoding="utf-8"))
            inventory = owner.get("sha256") if isinstance(owner, dict) else None
            if (owner.get("operation") != "package-skill" or owner.get("skill") != SKILL_NAME
                    or owner.get("ownership_version") != 1 or not isinstance(inventory, dict)
                    or "SKILL.md" not in inventory):
                raise ValueError("invalid ownership receipt")
            for name, digest in inventory.items():
                entry = Path(name)
                if (entry.is_absolute() or ".." in entry.parts or not isinstance(digest, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                    raise ValueError("invalid package inventory")
        except (OSError, ValueError, AttributeError) as exc:
            raise PackageError(f"Refusing unmanaged or unsafe destination {output}: {exc}") from exc
    return output


def build_package(source: Path, output: Path) -> list[str]:

    copied: list[str] = []
    for relative in RUNTIME_FILES:
        src = source / relative
        if not src.is_file():
            raise PackageError(f"Required runtime file is missing: {src}")
        if not is_relative_to(src.resolve(), source):
            raise PackageError(f"Runtime source escapes the repository: {src}")
        dest = output / relative
        shutil.copy2(src, dest)
        copied.append(relative)

    for directory, patterns in RUNTIME_GLOBS.items():
        src_dir = source / directory
        if not src_dir.is_dir():
            raise PackageError(f"Required runtime directory is missing: {src_dir}")
        dest_dir = output / directory
        dest_dir.mkdir()
        matches: list[Path] = []
        for pattern in patterns:
            matches.extend(sorted(src_dir.glob(pattern)))
        for src in sorted(set(matches)):
            if not src.is_file():
                continue
            if not is_relative_to(src.resolve(), source):
                raise PackageError(f"Runtime source escapes the repository: {src}")
            relative = src.relative_to(source)
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, destination)
            copied.append(relative.as_posix())
    for relative in copied:
        if relative.endswith(".py"):
            ast.parse((output / relative).read_text(encoding="utf-8-sig"), filename=relative)
        elif relative.endswith(".json"):
            json.loads((output / relative).read_text(encoding="utf-8-sig"))
    for required in ("scripts/pubmed_tool.py", "scripts/manifest_tool.py", "scripts/workflow_tool.py",
                     "references/workflow.md", "schemas/review-protocol.schema.json", "agents/openai.yaml",
                     "pubmed_search_builder/__init__.py"):
        if required not in copied:
            raise PackageError(f"Required runtime file is missing: {required}")
    return copied


def package_skill(source: Path, output: Path, *, replace: bool = False) -> dict[str, object]:
    source = source.resolve()
    common, commit = source_git_info(source)
    output = validate_destination(source, output, common, replace)
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.with_name(f".{output.name}.package.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise PackageError(f"Packaging lock exists; check for an active/interrupted update: {lock}") from exc
    os.close(descriptor)
    try:
        output = validate_destination(source, output, common, replace)
        with tempfile.TemporaryDirectory(prefix=f".{output.name}.stage-", dir=output.parent) as temporary:
            stage = Path(temporary) / SKILL_NAME
            stage.mkdir()
            copied = build_package(source, stage)
            receipt = {
                "operation": "package-skill",
                "ownership_version": 1,
                "skill": SKILL_NAME,
                "source": str(source),
                "source_commit": commit,
                "output": str(output),
                "file_count": len(copied),
                "files": copied,
                "excluded_repository_content": [
                    "README.md", "INSTALL.md", "GITHUB_SETUP.md", "CONTRIBUTING.md",
                    "tests/", "evals/", "examples/", "tools/",
                ],
            }
            receipt["sha256"] = {name: hashlib.sha256((stage / name).read_bytes()).hexdigest() for name in copied}
            # Carry local credentials forward; all other local changes remain in the backup.
            preserved = []
            if output.exists():
                for local in output.glob(".env*"):
                    if local.is_file():
                        shutil.copy2(local, stage / local.name)
                        preserved.append(local.name)
            receipt["preserved_local_files"] = preserved
            backup = output.with_name(f"{output.name}.backup-{uuid.uuid4().hex}") if output.exists() else None
            receipt["backup"] = str(backup) if backup else None
            (stage / OWNERSHIP_FILE).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            validate_destination(source, output, common, replace)
            if backup:
                output.rename(backup)
            try:
                stage.rename(output)
            except OSError as exc:
                if backup:
                    if output.exists():
                        raise PackageError(f"Promotion failed; previous installation preserved at {backup}") from exc
                    try:
                        backup.rename(output)
                    except OSError as restore_error:
                        raise PackageError(f"Restore failed; previous installation preserved at {backup}: {restore_error}") from exc
                message = "Package promotion failed; previous installation restored" if backup else "Package promotion failed; no installation was replaced"
                raise PackageError(message) from exc
            return receipt
    finally:
        lock.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a clean deployable Codex skill directory.")
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]), help="Repository source root.")
    parser.add_argument("--output", required=True, help="Destination directory named pubmed-search-builder.")
    parser.add_argument("--replace", action="store_true", help="Replace an owned package, retaining a sibling backup; repositories and unmanaged folders are refused.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = package_skill(Path(args.source), Path(args.output), replace=args.replace)
    except (ValueError, OSError, SyntaxError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
