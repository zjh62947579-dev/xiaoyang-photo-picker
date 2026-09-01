"""本地视频方向与人物分类。

视频按旋转后的实际画面分成横屏/竖屏，再按抽样帧中是否检测到人物
分成风景/人像。分类结果保存在素材文件夹内的 ``横屏视频`` / ``竖屏视频``。
"""

from __future__ import annotations

import errno
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image


VIDEO_EXTS = {
    ".3gp",
    ".avi",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ts",
    ".webm",
    ".wmv",
}
ORIENTATION_DIR_NAMES = {
    "横屏": "横屏视频",
    "竖屏": "竖屏视频",
}
OTHER_FILES_DIR_NAME = "其他文件"
STATE_FILENAME = ".video_sorter_state.json"
STATE_SCHEMA = 1
SKIP_DIR_NAMES = {
    "横屏视频",
    "竖屏视频",
    OTHER_FILES_DIR_NAME,
    "视频分类",
    "winners",
    "losers",
    "review",
    "_pic_selecter",
}
SAMPLE_FRACTIONS = (0.05, 0.20, 0.35, 0.50, 0.65, 0.80, 0.95)


class VideoReadError(RuntimeError):
    """视频无法打开或未能解码出画面。"""


class VideoCancelled(RuntimeError):
    """用户中止视频分类。"""


@dataclass
class SampledVideo:
    frames: list[Image.Image]
    width: int
    height: int
    frame_count: int = 0
    duration_seconds: float = 0.0


@dataclass
class VideoAnalysis:
    path: str
    width: int
    height: int
    orientation: str
    content: str
    person_present: bool
    person_score: float
    person_hit_frames: int
    sampled_frames: int
    duration_seconds: float


@dataclass
class SortedVideo:
    source: str
    target: str
    name: str
    orientation: str
    content: str
    person_score: float
    person_hit_frames: int
    sampled_frames: int
    width: int
    height: int
    duration_seconds: float
    status: str = "processed"
    error: str | None = None


@dataclass
class VideoSortSummary:
    folder: str
    total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    other_files: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    items: list[SortedVideo] = field(default_factory=list)


ProgressCallback = Callable[[int, int, str, SortedVideo | None], None]
CancelCheck = Callable[[], bool]
PersonDetector = Callable[[Sequence[Image.Image]], Sequence[float]]


def category_key(orientation: str, content: str) -> str:
    return f"{orientation}/{content}"


def orientation_for_dimensions(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        raise VideoReadError("视频画面尺寸无效")
    return "横屏" if width >= height else "竖屏"


def classify_person_scores(
    scores: Sequence[float],
    *,
    strong_threshold: float = 0.62,
    weak_threshold: float = 0.40,
    weak_hits_required: int = 2,
) -> tuple[bool, float, int]:
    """把多帧人体置信度合并成稳定的有人/无人判断。

    单帧高置信度可直接判定；较弱信号需要在至少两帧重复出现，降低把雕像、
    海报等误认为真人的概率。
    """
    clean = [max(0.0, min(1.0, float(score))) for score in scores]
    if not clean:
        return False, 0.0, 0
    max_score = max(clean)
    weak_hits = sum(score >= weak_threshold for score in clean)
    present = max_score >= strong_threshold or weak_hits >= weak_hits_required
    return present, round(max_score, 4), weak_hits


def _rotate_frame_from_metadata(frame, rotation: float):
    import cv2

    normalized = int(round(rotation)) % 360
    if normalized == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if normalized == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if normalized == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def _resize_frame(frame, max_dim: int = 960):
    import cv2

    height, width = frame.shape[:2]
    largest = max(width, height)
    if largest <= max_dim:
        return frame
    scale = max_dim / float(largest)
    return cv2.resize(
        frame,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )


def sample_video_frames(
    path: str | Path,
    *,
    sample_fractions: Sequence[float] = SAMPLE_FRACTIONS,
    max_dim: int = 960,
) -> SampledVideo:
    """从视频多个时间点抽帧，并返回旋转后的真实尺寸。"""
    import cv2

    video_path = str(path)
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        capture.release()
        raise VideoReadError("无法打开视频")

    orientation_prop = getattr(cv2, "CAP_PROP_ORIENTATION_AUTO", None)
    orientation_meta_prop = getattr(cv2, "CAP_PROP_ORIENTATION_META", None)
    auto_rotation = False
    rotation_meta = 0.0
    try:
        if orientation_prop is not None:
            auto_rotation = bool(capture.set(orientation_prop, 1))
        if orientation_meta_prop is not None:
            rotation_meta = float(capture.get(orientation_meta_prop) or 0.0)

        frame_count = max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        duration = frame_count / fps if frame_count > 0 and fps > 0 else 0.0

        if frame_count > 1:
            indices = sorted({
                min(frame_count - 1, max(0, int(round((frame_count - 1) * fraction))))
                for fraction in sample_fractions
            })
        else:
            indices = [0]

        decoded = []
        for index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            if rotation_meta and not auto_rotation:
                frame = _rotate_frame_from_metadata(frame, rotation_meta)
            decoded.append(frame)

        if not decoded:
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            for _ in range(30):
                ok, frame = capture.read()
                if ok and frame is not None:
                    if rotation_meta and not auto_rotation:
                        frame = _rotate_frame_from_metadata(frame, rotation_meta)
                    decoded.append(frame)
                    break
    finally:
        capture.release()

    if not decoded:
        raise VideoReadError("没有解码出可用画面")

    first_height, first_width = decoded[0].shape[:2]
    frames = [
        Image.fromarray(cv2.cvtColor(_resize_frame(frame, max_dim), cv2.COLOR_BGR2RGB))
        for frame in decoded
    ]
    return SampledVideo(
        frames=frames,
        width=int(first_width),
        height=int(first_height),
        frame_count=frame_count,
        duration_seconds=round(duration, 3),
    )


def analyze_video(
    path: str | Path,
    *,
    person_detector: PersonDetector | None = None,
) -> VideoAnalysis:
    sampled = sample_video_frames(path)
    if person_detector is None:
        from pic_selecter.vision import detect_people_scores

        person_detector = detect_people_scores
    scores = list(person_detector(sampled.frames))
    present, max_score, hit_frames = classify_person_scores(scores)
    orientation = orientation_for_dimensions(sampled.width, sampled.height)
    return VideoAnalysis(
        path=str(path),
        width=sampled.width,
        height=sampled.height,
        orientation=orientation,
        content="人像" if present else "风景",
        person_present=present,
        person_score=max_score,
        person_hit_frames=hit_frames,
        sampled_frames=len(sampled.frames),
        duration_seconds=sampled.duration_seconds,
    )


def discover_videos(folder: str | Path) -> list[Path]:
    root = Path(folder)
    videos: list[Path] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES)
        current_path = Path(current)
        for name in sorted(files, key=str.lower):
            if Path(name).suffix.lower() in VIDEO_EXTS:
                videos.append(current_path / name)
    return sorted(videos, key=lambda path: str(path).lower())


def discover_other_files(folder: str | Path) -> list[Path]:
    root = Path(folder)
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES)
        current_path = Path(current)
        for name in sorted(names, key=str.lower):
            path = current_path / name
            if path.name in {STATE_FILENAME, ".DS_Store", "Thumbs.db"}:
                continue
            if path.suffix.lower() in VIDEO_EXTS:
                continue
            files.append(path)
    return sorted(files, key=lambda path: str(path).lower())


def count_videos(folder: str | Path) -> int:
    return len(discover_videos(folder))


def discover_batch_folders(root: str | Path) -> list[tuple[Path, int]]:
    base = Path(root)
    items: list[tuple[Path, int]] = []
    for child in sorted(base.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir() or child.name in SKIP_DIR_NAMES:
            continue
        count = count_videos(child)
        if count:
            items.append((child, count))
    return items


def output_dir(folder: str | Path) -> Path:
    return Path(folder)


def target_dir_for(root: Path, orientation: str, content: str) -> Path:
    return root / ORIENTATION_DIR_NAMES.get(orientation, f"{orientation}视频") / content


def other_files_dir(root: Path) -> Path:
    return root / OTHER_FILES_DIR_NAME


def state_path(folder: str | Path) -> Path:
    return Path(folder) / STATE_FILENAME


def _empty_state(mode: str) -> dict:
    return {"schema": STATE_SCHEMA, "mode": mode, "items": {}}


def load_state(folder: str | Path, mode: str) -> dict:
    path = state_path(folder)
    if not path.exists():
        return _empty_state(mode)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _empty_state(mode)
    if data.get("schema") != STATE_SCHEMA or not isinstance(data.get("items"), dict):
        return _empty_state(mode)
    return data


def save_state(folder: str | Path, state: dict) -> None:
    path = state_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _signature(path: Path) -> dict:
    stat = path.stat()
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _source_key(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _target_from_entry(root: Path, entry: dict) -> Path | None:
    relative = entry.get("target")
    if not isinstance(relative, str) or not relative:
        return None
    return root / Path(relative)


def _already_completed(root: Path, path: Path, entry: dict | None, mode: str) -> bool:
    if not entry or entry.get("status") != "processed" or entry.get("mode") != mode:
        return False
    try:
        if entry.get("signature") != _signature(path):
            return False
    except OSError:
        return False
    target = _target_from_entry(root, entry)
    return bool(target and target.is_file())


def _unique_target(folder: Path, name: str) -> Path:
    target = folder / name
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    index = 1
    while True:
        candidate = folder / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _transfer(source: Path, target: Path, mode: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "move":
        shutil.move(str(source), str(target))
    else:
        shutil.copy2(source, target)


def organize_other_files(root: Path, mode: str) -> int:
    moved = 0
    target_folder = other_files_dir(root)
    for source in discover_other_files(root):
        target = _unique_target(target_folder, source.name)
        _transfer(source, target, mode)
        moved += 1
    return moved


def sort_videos(
    folder: str | Path,
    *,
    mode: str = "move",
    person_detector: PersonDetector | None = None,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> VideoSortSummary:
    """分类一个素材文件夹；每完成一个视频就保存断点。"""
    if mode not in {"copy", "move"}:
        raise ValueError(f"不支持的归档方式: {mode}")

    root = Path(folder).resolve()
    videos = discover_videos(root)
    other_files = discover_other_files(root)
    state = load_state(root, mode)
    entries = state.setdefault("items", {})
    state["mode"] = mode
    summary = VideoSortSummary(
        folder=str(root),
        total=len(videos),
        categories={
            "横屏/风景": 0,
            "横屏/人像": 0,
            "竖屏/风景": 0,
            "竖屏/人像": 0,
        },
    )
    summary.other_files = len(other_files)

    for index, source in enumerate(videos, start=1):
        if cancel_check and cancel_check():
            raise VideoCancelled()

        source_key = _source_key(root, source)
        existing = entries.get(source_key)
        if _already_completed(root, source, existing, mode):
            summary.skipped += 1
            category = existing.get("category")
            if category in summary.categories:
                summary.categories[category] += 1
            item = SortedVideo(
                source=str(source),
                target=str(_target_from_entry(root, existing) or ""),
                name=source.name,
                orientation=existing.get("orientation", ""),
                content=existing.get("content", ""),
                person_score=float(existing.get("person_score") or 0.0),
                person_hit_frames=int(existing.get("person_hit_frames") or 0),
                sampled_frames=int(existing.get("sampled_frames") or 0),
                width=int(existing.get("width") or 0),
                height=int(existing.get("height") or 0),
                duration_seconds=float(existing.get("duration_seconds") or 0.0),
                status="skipped",
            )
            summary.items.append(item)
            if progress:
                progress(index, summary.total, f"已跳过 {source.name}", item)
            continue

        if progress:
            progress(index - 1, summary.total, f"正在识别 {source.name}", None)

        try:
            signature = _signature(source)
            analysis = analyze_video(source, person_detector=person_detector)
            if cancel_check and cancel_check():
                raise VideoCancelled()
            category = category_key(analysis.orientation, analysis.content)
            target_folder = target_dir_for(root, analysis.orientation, analysis.content)
            target = _unique_target(target_folder, source.name)
            _transfer(source, target, mode)
            relative_target = target.relative_to(root).as_posix()
            entry = {
                "status": "processed",
                "mode": mode,
                "signature": signature,
                "target": relative_target,
                "orientation": analysis.orientation,
                "content": analysis.content,
                "category": category,
                "person_score": analysis.person_score,
                "person_hit_frames": analysis.person_hit_frames,
                "sampled_frames": analysis.sampled_frames,
                "width": analysis.width,
                "height": analysis.height,
                "duration_seconds": analysis.duration_seconds,
            }
            entries[source_key] = entry
            save_state(root, state)

            item = SortedVideo(
                source=str(source),
                target=str(target),
                name=source.name,
                orientation=analysis.orientation,
                content=analysis.content,
                person_score=analysis.person_score,
                person_hit_frames=analysis.person_hit_frames,
                sampled_frames=analysis.sampled_frames,
                width=analysis.width,
                height=analysis.height,
                duration_seconds=analysis.duration_seconds,
            )
            summary.processed += 1
            summary.categories[category] += 1
            summary.items.append(item)
            if progress:
                progress(index, summary.total, f"{analysis.orientation} · {analysis.content} · {source.name}", item)
        except VideoCancelled:
            raise
        except VideoReadError as exc:
            summary.failed += 1
            item = SortedVideo(
                source=str(source),
                target="",
                name=source.name,
                orientation="",
                content="",
                person_score=0.0,
                person_hit_frames=0,
                sampled_frames=0,
                width=0,
                height=0,
                duration_seconds=0.0,
                status="error",
                error=str(exc),
            )
            summary.items.append(item)
            if progress:
                progress(index, summary.total, f"无法读取 {source.name}", item)
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise RuntimeError("磁盘空间不足，视频分类已停止") from exc
            summary.failed += 1
            item = SortedVideo(
                source=str(source),
                target="",
                name=source.name,
                orientation="",
                content="",
                person_score=0.0,
                person_hit_frames=0,
                sampled_frames=0,
                width=0,
                height=0,
                duration_seconds=0.0,
                status="error",
                error=str(exc),
            )
            summary.items.append(item)
            if progress:
                progress(index, summary.total, f"归档失败 {source.name}", item)
    if not (cancel_check and cancel_check()):
        summary.other_files = organize_other_files(root, mode)

    return summary


def summary_to_dict(summary: VideoSortSummary) -> dict:
    return asdict(summary)
