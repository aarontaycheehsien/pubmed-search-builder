#!/usr/bin/env python3
"""Build a clean deployable pubmed-search-builder skill from the repository source."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


SKILL_NAME = "pubmed-search-builder"
RUNTIME_FILES = ("SKILL.md",)
RUNTIME_GLOBS = {
    "agents": ("*.yaml",),
    "references": ("*.md",),
    "schemas": ("*.json",),
    "scripts": ("*.py",),
}


class PackageError(ValueError):
    pass


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def package_skill(source: Path, output: Path, *, replace: bool = False) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
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
        shutil.rmtree(output)
    output.mkdir(parents=True)

    copied: list[str] = []
    for relative in RUNTIME_FILES:
        src = source / relative
        if not src.is_file():
            raise PackageError(f"Required runtime file is missing: {src}")
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
            relative = src.relative_to(source)
            shutil.copy2(src, output / relative)
            copied.append(relative.as_posix())

    receipt = {
        "operation": "package-skill",
        "skill": SKILL_NAME,
        "source": str(source),
        "output": str(output),
        "file_count": len(copied),
        "files": copied,
        "excluded_repository_content": [
            "README.md",
            "INSTALL.md",
            "GITHUB_SETUP.md",
            "CONTRIBUTING.md",
            "tests/",
            "evals/",
            "examples/",
            "tools/",
        ],
    }
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a clean deployable Codex skill directory.")
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]), help="Repository source root.")
    parser.add_argument("--output", required=True, help="Destination directory named pubmed-search-builder.")
    parser.add_argument("--replace", action="store_true", help="Replace an existing destination with the same skill name.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = package_skill(Path(args.source), Path(args.output), replace=args.replace)
    except PackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
