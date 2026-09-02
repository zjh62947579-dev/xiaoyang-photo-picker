"""素材整理前置工具。

把喔图一类导出的路线分类包整理成 ``路线/风景|人像|合照|肖像权说明`` 结构：

- ``无水印_7.18惠州冲浪_风景(已显示&已修未显示).zip`` ->
  ``7.18惠州冲浪/风景``
- 解压成功后删除原压缩包
- 同级 ``xxx(1)`` / ``xxx(2)`` 这类重复文件夹删除
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


ARCHIVE_EXTS = {".zip"}
CATEGORY_ALIASES = {
    "风景": "风景",
    "风光": "风景",
    "人像": "人像",
    "合照": "合照",
    "群像": "合照",
    "肖像权说明": "肖像权说明",
}
OUTPUT_CATEGORY_NAMES = set(CATEGORY_ALIASES.values())
IGNORED_FILE_NAMES = {".DS_Store", "Thumbs.db"}
SKIP_DIR_NAMES = {
    "winners",
    "losers",
    "review",
    "_pic_selecter",
    "_pic_selecter_extract",
    "横屏视频",
    "竖屏视频",
}
ROUTE_PATTERN = re.compile(
    r"^(?:无水印_)?(?P<route>.+)_(?P<category>风景|风光|人像|合照|群像|肖像权说明)(?:\(.*\))?$"
)
DUPLICATE_DIR_PATTERN = re.compile(r"^(?P<base>.+)\((?P<index>[1-9]\d*)\)$")


@dataclass
class OrganizerItem:
    source: str
    target: str = ""
    action: str = ""
    status: str = "ok"
    note: str = ""


@dataclass
class OrganizerSummary:
    folder: str
    deleted_duplicate_dirs: int = 0
    extracted_archives: int = 0
    deleted_archives: int = 0
    organized_dirs: int = 0
    moved_files: int = 0
    skipped: int = 0
    failed: int = 0
    items: list[OrganizerItem] = field(default_factory=list)


ProgressCallback = Callable[[int, int, str, OrganizerItem | None], None]
CancelCheck = Callable[[], bool]


class OrganizerCancelled(RuntimeError):
    pass


def parse_route_category(name: str) -> tuple[str, str] | None:
    stem = Path(name).stem if Path(name).suffix.lower() in ARCHIVE_EXTS else name
    stem = stem.strip()
    match = ROUTE_PATTERN.match(stem)
    if not match:
        return None
    route = match.group("route").strip()
    category = CATEGORY_ALIASES.get(match.group("category"))
    if not route or not category:
        return None
    return route, category


def _unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    index = 1
    while True:
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _trash_windows(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", wintypes.USHORT),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", wintypes.LPVOID),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        fo_delete = 0x0003
        fof_allowundo = 0x0040
        fof_noconfirmation = 0x0010
        fof_silent = 0x0004
        op = SHFILEOPSTRUCTW()
        op.wFunc = fo_delete
        op.pFrom = str(path) + "\0\0"
        op.fFlags = fof_allowundo | fof_noconfirmation | fof_silent
        return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0
    except Exception:
        return False


def move_to_trash(path: Path) -> None:
    if not path.exists():
        return
    if _trash_windows(path):
        return
    if sys.platform == "darwin":
        trash_dir = Path.home() / ".Trash"
        trash_dir.mkdir(exist_ok=True)
        shutil.move(str(path), str(_unique_path(trash_dir / path.name)))
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _delete_duplicate_dirs(root: Path, summary: OrganizerSummary) -> None:
    for current, dirs, _files in os.walk(root, topdown=False):
        current_path = Path(current)
        for dirname in list(dirs):
            match = DUPLICATE_DIR_PATTERN.match(dirname)
            if not match:
                continue
            duplicate = current_path / dirname
            original = current_path / match.group("base")
            if not original.is_dir():
                continue
            move_to_trash(duplicate)
            summary.deleted_duplicate_dirs += 1
            summary.items.append(OrganizerItem(
                source=str(duplicate),
                action="delete_duplicate_dir",
                note="重复文件夹已删除",
            ))


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            member = Path(info.filename)
            if member.is_absolute() or ".." in member.parts:
                continue
            zf.extract(info, destination)


def _is_valid_zip(archive: Path) -> bool:
    """快速检查 ZIP 结构，避免坏压缩包中断整理流程。"""
    try:
        return zipfile.is_zipfile(archive)
    except (OSError, ValueError):
        return False


def _discover_archives(root: Path) -> list[Path]:
    archives: list[Path] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES)
        for name in sorted(files, key=str.lower):
            if Path(name).suffix.lower() in ARCHIVE_EXTS:
                archives.append(Path(current) / name)
    return archives


def peek_materials(folder: str | Path) -> dict:
    root = Path(folder).resolve()
    archives = _discover_archives(root)
    route_archives = [path for path in archives if parse_route_category(path.name)]
    route_dirs = _iter_route_source_dirs(root)
    duplicate_dirs = 0
    for current, dirs, _files in os.walk(root):
        current_path = Path(current)
        for dirname in dirs:
            match = DUPLICATE_DIR_PATTERN.match(dirname)
            if match and (current_path / match.group("base")).is_dir():
                duplicate_dirs += 1
    routes = {
        parsed[0]
        for path in [*route_archives, *route_dirs]
        if (parsed := parse_route_category(path.name))
    }
    return {
        "archives": len(archives),
        "route_archives": len(route_archives),
        "route_dirs": len(route_dirs),
        "duplicate_dirs": duplicate_dirs,
        "routes": len(routes),
    }


def _iter_route_source_dirs(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for current, dirs, _files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES)
        current_path = Path(current)
        for dirname in dirs:
            child = current_path / dirname
            if parse_route_category(dirname):
                candidates.append(child)
    return sorted(candidates, key=lambda path: len(path.parts), reverse=True)


def _move_dir_contents(source: Path, target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    for child in sorted(source.iterdir(), key=lambda path: path.name.lower()):
        if child.name in IGNORED_FILE_NAMES:
            continue
        shutil.move(str(child), str(_unique_path(target / child.name)))
        moved += 1
    return moved


def _move_tree_files_flat(source: Path, target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    files = sorted(
        (path for path in source.rglob("*") if path.is_file() and path.name not in IGNORED_FILE_NAMES),
        key=lambda path: str(path).lower(),
    )
    for file_path in files:
        if file_path.parent.resolve() == target.resolve():
            continue
        shutil.move(str(file_path), str(_unique_path(target / file_path.name)))
        moved += 1
    for current, dirs, files_in_dir in os.walk(source, topdown=False):
        path = Path(current)
        if path == target:
            continue
        for name in files_in_dir:
            if name in IGNORED_FILE_NAMES:
                try:
                    (path / name).unlink()
                except OSError:
                    pass
        try:
            path.rmdir()
        except OSError:
            pass
    return moved


def _move_extracted_payload(extract_root: Path, target: Path) -> int:
    entries = [path for path in extract_root.iterdir() if path.name not in IGNORED_FILE_NAMES]
    if len(entries) == 1 and entries[0].is_dir() and parse_route_category(entries[0].name):
        source = entries[0]
    else:
        source = extract_root
    return _move_tree_files_flat(source, target)


def _flatten_existing_route_categories(root: Path, summary: OrganizerSummary) -> None:
    for route_dir in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda path: path.name.lower()):
        if route_dir.name in SKIP_DIR_NAMES:
            continue
        for category in OUTPUT_CATEGORY_NAMES:
            category_dir = route_dir / category
            if not category_dir.is_dir():
                continue
            moved = _move_tree_files_flat(category_dir, category_dir)
            if moved:
                summary.moved_files += moved
                summary.items.append(OrganizerItem(
                    source=str(category_dir),
                    target=str(category_dir),
                    action="flatten_category",
                    note=f"已拍平 {moved} 个文件",
                ))


def organize_materials(
    folder: str | Path,
    *,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> OrganizerSummary:
    root = Path(folder).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"文件夹不存在: {root}")

    summary = OrganizerSummary(folder=str(root))

    def cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    _delete_duplicate_dirs(root, summary)

    archives = _discover_archives(root)
    total = len(archives)
    for index, archive in enumerate(archives, start=1):
        if cancelled():
            raise OrganizerCancelled()
        parsed = parse_route_category(archive.name)
        extract_root = archive.parent
        item = OrganizerItem(source=str(archive), action="extract")
        try:
            if not _is_valid_zip(archive):
                summary.skipped += 1
                item.status = "skipped"
                item.note = "不是有效的 ZIP 压缩包，已跳过（原文件未删除）"
                summary.items.append(item)
                if progress:
                    progress(index, total, f"跳过无效压缩包 {archive.name}", item)
                continue
            target = extract_root
            if parsed:
                route, category = parsed
                extract_root = _unique_path(archive.parent / "_pic_selecter_extract" / archive.stem)
                target = archive.parent / route / category
                _safe_extract_zip(archive, extract_root)
                moved = _move_extracted_payload(extract_root, target)
                shutil.rmtree(extract_root, ignore_errors=True)
                try:
                    extract_root.parent.rmdir()
                except OSError:
                    pass
                summary.moved_files += moved
            else:
                _safe_extract_zip(archive, extract_root)
            summary.extracted_archives += 1
            move_to_trash(archive)
            summary.deleted_archives += 1
            item.target = str(target)
            item.note = "已解压并删除压缩包"
            summary.items.append(item)
        except Exception as exc:
            summary.failed += 1
            item.status = "error"
            item.note = str(exc)
            summary.items.append(item)
        if progress:
            progress(index, total, f"解压 {archive.name}", item)

    source_dirs = _iter_route_source_dirs(root)
    for source in source_dirs:
        if cancelled():
            raise OrganizerCancelled()
        parsed = parse_route_category(source.name)
        if not parsed or not source.exists():
            continue
        route, category = parsed
        target = root / route / category
        if source.resolve() == target.resolve():
            continue
        item = OrganizerItem(source=str(source), target=str(target), action="organize_dir")
        try:
            moved = _move_tree_files_flat(source, target)
            summary.moved_files += moved
            summary.organized_dirs += 1
            if not any(source.iterdir()):
                source.rmdir()
            item.note = f"已归并 {moved} 个文件"
            summary.items.append(item)
        except Exception as exc:
            summary.failed += 1
            item.status = "error"
            item.note = str(exc)
            summary.items.append(item)

    _flatten_existing_route_categories(root, summary)

    return summary
