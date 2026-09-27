#!/usr/bin/env python3
"""Restore project files that were renamed to non-hidden names with suffixes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


RENAMES = [
    ("env.runtime.txt", ".env"),
    ("pre-commit-config.yaml", ".pre-commit-config.yaml"),
    ("LICENSE.txt", "LICENSE"),
    ("rag-anything-experiments/env.experiments.txt", "rag-anything-experiments/.env"),
    ("raganything.egg-info/PKG-INFO.txt", "raganything.egg-info/PKG-INFO"),
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def restore(root: Path, dry_run: bool) -> int:
    failures = 0

    for renamed_rel, original_rel in RENAMES:
        renamed = root / renamed_rel
        original = root / original_rel

        if original.exists():
            if renamed.exists():
                print(f"CONFLICT: both exist: {original_rel} and {renamed_rel}")
                failures += 1
            else:
                print(f"OK: already restored: {original_rel}")
            continue

        if not renamed.exists():
            print(f"MISSING: cannot restore {original_rel}; source not found: {renamed_rel}")
            failures += 1
            continue

        if dry_run:
            print(f"WOULD RESTORE: {renamed_rel} -> {original_rel}")
            continue

        renamed.rename(original)
        print(f"RESTORED: {renamed_rel} -> {original_rel}")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore original filenames required by the RAG-Anything test flow."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned restores without renaming files.",
    )
    args = parser.parse_args()

    return restore(project_root(), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
