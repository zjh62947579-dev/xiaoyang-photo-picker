import importlib
import sys
import types
from pathlib import Path

from pic_selecter import video_classifier


def import_app_module():
    sys.modules.setdefault("imagehash", types.SimpleNamespace(phash=lambda *args, **kwargs: "0" * 16))
    sys.modules.pop("app", None)
    return importlib.import_module("app")


LOCAL_HEADERS = {"Origin": "http://localhost"}


def fake_analysis(path, *, person_detector=None):
    path = Path(path)
    portrait = "portrait" in path.parts
    people = "people" in path.parts
    return video_classifier.VideoAnalysis(
        path=str(path),
        width=1080 if portrait else 1920,
        height=1920 if portrait else 1080,
        orientation="竖屏" if portrait else "横屏",
        content="人像" if people else "风景",
        person_present=people,
        person_score=0.91 if people else 0.08,
        person_hit_frames=4 if people else 0,
        sampled_frames=7,
        duration_seconds=12.5,
    )


def test_orientation_uses_rotated_frame_dimensions():
    assert video_classifier.orientation_for_dimensions(1920, 1080) == "横屏"
    assert video_classifier.orientation_for_dimensions(1080, 1920) == "竖屏"
    assert video_classifier.orientation_for_dimensions(1080, 1080) == "横屏"


def test_person_scores_accept_one_strong_or_repeated_weak_signal():
    assert video_classifier.classify_person_scores([0.03, 0.72, 0.01]) == (True, 0.72, 1)
    assert video_classifier.classify_person_scores([0.03, 0.44, 0.48]) == (True, 0.48, 2)
    assert video_classifier.classify_person_scores([0.03, 0.44, 0.12]) == (False, 0.44, 1)


def test_copy_sort_flattens_categories_avoids_name_collisions_and_resumes(tmp_path, monkeypatch):
    first = tmp_path / "route-a" / "clip.mp4"
    second = tmp_path / "route-b" / "clip.mp4"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    calls = []

    def analyze(path, *, person_detector=None):
        calls.append(str(path))
        return fake_analysis(path, person_detector=person_detector)

    monkeypatch.setattr(video_classifier, "analyze_video", analyze)
    summary = video_classifier.sort_videos(tmp_path, mode="copy")

    output = tmp_path / "视频分类" / "横屏" / "风景"
    assert summary.processed == 2
    assert summary.failed == 0
    assert (output / "clip.mp4").read_bytes() == b"first"
    assert (output / "clip_1.mp4").read_bytes() == b"second"
    assert first.exists() and second.exists()
    assert len(calls) == 2

    resumed = video_classifier.sort_videos(tmp_path, mode="copy")
    assert resumed.processed == 0
    assert resumed.skipped == 2
    assert len(calls) == 2
    assert len(list(output.glob("*.mp4"))) == 2


def test_move_sort_uses_four_requested_categories(tmp_path, monkeypatch):
    paths = [
        tmp_path / "landscape" / "scenery" / "a.mov",
        tmp_path / "landscape" / "people" / "b.mov",
        tmp_path / "portrait" / "scenery" / "c.mov",
        tmp_path / "portrait" / "people" / "d.mov",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
    monkeypatch.setattr(video_classifier, "analyze_video", fake_analysis)

    summary = video_classifier.sort_videos(tmp_path, mode="move")

    assert summary.categories == {
        "横屏/风景": 1,
        "横屏/人像": 1,
        "竖屏/风景": 1,
        "竖屏/人像": 1,
    }
    assert all(not path.exists() for path in paths)
    assert (tmp_path / "视频分类" / "横屏" / "风景" / "a.mov").exists()
    assert (tmp_path / "视频分类" / "横屏" / "人像" / "b.mov").exists()
    assert (tmp_path / "视频分类" / "竖屏" / "风景" / "c.mov").exists()
    assert (tmp_path / "视频分类" / "竖屏" / "人像" / "d.mov").exists()


def test_unreadable_video_stays_in_original_location(tmp_path, monkeypatch):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"broken")

    def fail(path, *, person_detector=None):
        raise video_classifier.VideoReadError("没有解码出可用画面")

    monkeypatch.setattr(video_classifier, "analyze_video", fail)
    summary = video_classifier.sort_videos(tmp_path, mode="move")

    assert summary.failed == 1
    assert summary.processed == 0
    assert bad.exists()
    assert summary.items[0].status == "error"


def test_batch_discovery_uses_first_level_folders_and_skips_output(tmp_path):
    route_a = tmp_path / "route-a"
    route_b = tmp_path / "route-b"
    (route_a / "nested").mkdir(parents=True)
    route_b.mkdir()
    (route_a / "nested" / "one.mp4").write_bytes(b"1")
    (route_b / "two.mov").write_bytes(b"2")
    output = tmp_path / "视频分类" / "横屏" / "风景"
    output.mkdir(parents=True)
    (output / "ignored.mp4").write_bytes(b"3")

    discovered = video_classifier.discover_batch_folders(tmp_path)

    assert [(path.name, count) for path, count in discovered] == [
        ("route-a", 1),
        ("route-b", 1),
    ]


def test_video_start_api_creates_background_job(tmp_path, monkeypatch):
    app = import_app_module()
    (tmp_path / "one.mp4").write_bytes(b"video")
    monkeypatch.setattr(app.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(app, "VIDEO_JOB", None)
    monkeypatch.setattr(app, "VIDEO_BATCH_JOB", None)
    monkeypatch.setattr(app, "JOB", None)
    monkeypatch.setattr(app, "BATCH_JOB", None)
    from pic_selecter import vision
    monkeypatch.setattr(vision, "require_person_detector_capabilities", lambda: None)

    client = app.app.test_client()
    response = client.post(
        "/api/video/start",
        json={"folder": str(tmp_path), "mode": "move", "runtime": "auto"},
        headers=LOCAL_HEADERS,
    )

    assert response.status_code == 200
    assert response.get_json()["total"] == 1
    assert app.VIDEO_JOB.folder == str(tmp_path.resolve())
    assert app.VIDEO_JOB.mode == "move"


def test_video_batch_start_discovers_route_folders(tmp_path, monkeypatch):
    app = import_app_module()
    route = tmp_path / "route-a"
    route.mkdir()
    (route / "one.mp4").write_bytes(b"video")
    monkeypatch.setattr(app.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(app, "VIDEO_JOB", None)
    monkeypatch.setattr(app, "VIDEO_BATCH_JOB", None)
    monkeypatch.setattr(app, "JOB", None)
    monkeypatch.setattr(app, "BATCH_JOB", None)
    from pic_selecter import vision
    monkeypatch.setattr(vision, "require_person_detector_capabilities", lambda: None)

    client = app.app.test_client()
    response = client.post(
        "/api/video/batch/start",
        json={"folder": str(tmp_path), "mode": "copy"},
        headers=LOCAL_HEADERS,
    )

    assert response.status_code == 200
    assert response.get_json()["total"] == 1
    assert app.VIDEO_BATCH_JOB.items[0].name == "route-a"
    assert app.VIDEO_BATCH_JOB.items[0].video_count == 1
