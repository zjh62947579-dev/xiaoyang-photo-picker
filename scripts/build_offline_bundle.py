"""Build a distributable ZIP that includes local model caches.

This is for sharing with Windows users on restricted networks. The normal
GitHub source ZIP stays small; this script creates a separate local package
that includes models/ so expert mode can start without downloading model
weights again.
"""

from __future__ import annotations

import argparse
import os
import time
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "dist"

EXCLUDE_DIR_NAMES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    ".cache",
    ".launcher-cache",
    ".launcher-python",
    ".pip-cache",
    ".uv-cache",
    ".uv-python",
    "dist",
    "env",
    "venv",
    "winners",
    "losers",
    "review",
    "_pic_selecter",
}

EXCLUDE_FILE_NAMES = {
    ".DS_Store",
    ".pic_selecter_deps.stamp",
    ".pic_selecter_install.json",
    "com.codex.pianke.local.plist",
    "log.txt",
    "state.json",
}

EXCLUDE_SUFFIXES = {
    ".bak",
    ".log",
    ".pid",
    ".pyc",
    ".session.json",
    ".tmp",
}


def _skip_file(path: Path) -> bool:
    if path.name in EXCLUDE_FILE_NAMES:
        return True
    if any(path.name.endswith(suffix) for suffix in EXCLUDE_SUFFIXES):
        return True
    return False


def _iter_files(include_models: bool):
    for current, dirnames, filenames in os.walk(ROOT):
        current_path = Path(current)
        dirnames[:] = [
            name
            for name in dirnames
            if name not in EXCLUDE_DIR_NAMES and (include_models or name != "models")
        ]
        for filename in filenames:
            path = current_path / filename
            if _skip_file(path):
                continue
            yield path


def _size_mb(paths: list[Path]) -> float:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total / 1024 / 1024


def build_bundle(out_dir: Path, include_models: bool = True) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    suffix = "offline-with-models" if include_models else "source"
    zip_path = out_dir / f"xiaoyang-photo-picker-{suffix}-{stamp}.zip"
    files = list(_iter_files(include_models=include_models))
    root_name = f"xiaoyang-photo-picker-{suffix}"

    print(f"Building {zip_path}")
    print(f"Files: {len(files)}")
    print(f"Input size: {_size_mb(files):.1f} MB")
    if include_models and not (ROOT / "models").exists():
        print("WARNING: models/ not found. Expert mode will still need network downloads.")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            rel = path.relative_to(ROOT)
            zf.write(path, Path(root_name) / rel)

    print(f"Done: {zip_path}")
    print(f"ZIP size: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--no-models", action="store_true", help="Build a source-only ZIP.")
    args = parser.parse_args()
    build_bundle(args.out_dir, include_models=not args.no_models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
