import importlib
import sys
import time
import types
from pathlib import Path


def import_app_module():
    sys.modules.setdefault("imagehash", types.SimpleNamespace(phash=lambda *args, **kwargs: "0" * 16))
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def make_info(path: Path, score=80.0, auto_reject=False, reason=None):
    app = import_app_module()
    path.write_bytes(b"fake")
    return app.ImageInfo(
        path=str(path),
        phash="0" * 16,
        size=path.stat().st_size,
        mtime=path.stat().st_mtime,
        exif_summary={"width": 1000, "height": 800, "file_size": path.stat().st_size},
        quality={
            "quality_score": score,
            "flags": ["very_blurry"] if auto_reject else [],
            "auto_reject": auto_reject,
            "reject_reason": reason,
        },
    )


def build_session(tmp_path, raw_groups, enabled=True, strength="standard"):
    app = import_app_module()
    return app.build_session_from_groups(
        str(tmp_path),
        dry_run=True,
        mode="copy",
        raw_groups=raw_groups,
        infos=[info for group in raw_groups for info in group],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=enabled,
        prescreen_strength=strength,
    )


LOCAL_HEADERS = {"Origin": "http://localhost"}


def test_single_image_group_is_kept_as_winner_until_prescreen_is_confirmed(tmp_path):
    bad = make_info(tmp_path / "bad.jpg", score=8, auto_reject=True, reason="严重模糊")

    sess = build_session(tmp_path, [[bad]])

    group = sess.groups[0]
    assert group.finished is True
    assert group.winner == bad.path
    assert group.losers == []
    assert group.auto_rejected == []


def test_group_prescreen_keeps_two_survivors_for_tournament(tmp_path):
    bad = make_info(tmp_path / "bad.jpg", score=5, auto_reject=True, reason="曝光过低")
    good1 = make_info(tmp_path / "good1.jpg", score=72)
    good2 = make_info(tmp_path / "good2.jpg", score=74)

    sess = build_session(tmp_path, [[bad, good1, good2]])

    group = sess.groups[0]
    assert group.finished is False
    assert group.losers == []
    assert group.auto_rejected == []
    assert {group.left, group.right} <= {bad.path, good1.path, good2.path}


def test_standard_prescreen_rejects_only_clear_relative_loser(tmp_path):
    best = make_info(tmp_path / "best.jpg", score=94)
    ok = make_info(tmp_path / "ok.jpg", score=62)
    weak = make_info(tmp_path / "weak.jpg", score=55)

    sess = build_session(tmp_path, [[best, ok, weak]], enabled=True, strength="standard")

    group = sess.groups[0]
    assert group.finished is False
    assert group.winner is None
    assert group.losers == [weak.path]
    assert group.auto_rejected == [weak.path]
    assert group.auto_reject_reasons[weak.path] == "同组美学/质量评分明显落后"
    assert group.left == best.path
    assert group.right == ok.path


def test_disabled_prescreen_keeps_original_multi_group_flow(tmp_path):
    bad = make_info(tmp_path / "bad.jpg", score=5, auto_reject=True, reason="严重模糊")
    good = make_info(tmp_path / "good.jpg", score=90)

    sess = build_session(tmp_path, [[bad, good]], enabled=False)

    group = sess.groups[0]
    assert group.finished is False
    assert group.left == bad.path
    assert group.right == good.path
    assert group.losers == []
    assert group.auto_rejected == []


def test_auto_rejected_api_lists_rejected_items(tmp_path):
    app = import_app_module()
    bad = make_info(tmp_path / "bad.jpg", score=8, auto_reject=True, reason="严重模糊")
    app.SESSION = app.build_prescreen_session_from_infos(
        str(tmp_path),
        dry_run=True,
        mode="copy",
        infos=[bad],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=True,
        prescreen_strength="standard",
    )

    with app.app.app_context():
        payload = app.api_auto_rejected().get_json()

    assert payload["items"][0]["path"] == bad.path
    assert payload["items"][0]["reason"] == "严重模糊"
    assert payload["items"][0]["restored"] is False


def test_restore_rejected_adds_photo_to_winners_once(tmp_path):
    app = import_app_module()
    bad = make_info(tmp_path / "bad.jpg", score=8, auto_reject=True, reason="严重模糊")
    app.SESSION = app.build_prescreen_session_from_infos(
        str(tmp_path),
        dry_run=True,
        mode="copy",
        infos=[bad],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=True,
        prescreen_strength="standard",
    )

    client = app.app.test_client()
    first = client.post(
        "/api/restore_rejected",
        json={"group_id": "__prescreen__", "path": bad.path},
        headers=LOCAL_HEADERS,
    ).get_json()
    second = client.post(
        "/api/restore_rejected",
        json={"group_id": "__prescreen__", "path": bad.path},
        headers=LOCAL_HEADERS,
    ).get_json()

    assert first["ok"] is True
    assert second["ok"] is True
    assert app.SESSION.prescreen_restored == [bad.path]


def test_confirm_prescreen_marks_session_reviewed(tmp_path):
    app = import_app_module()
    bad = make_info(tmp_path / "bad.jpg", score=8, auto_reject=True, reason="严重模糊")
    app.SESSION = build_session(tmp_path, [[bad]])

    with app.app.app_context():
        payload = app.api_confirm_prescreen().get_json()

    assert payload["ok"] is True
    assert app.SESSION.prescreen_reviewed is True


def test_confirm_prescreen_groups_only_passed_and_restored_photos(tmp_path):
    app = import_app_module()
    bad_drop = make_info(tmp_path / "drop.jpg", score=8, auto_reject=True, reason="严重模糊")
    bad_restore = make_info(tmp_path / "restore.jpg", score=9, auto_reject=True, reason="曝光过低")
    good = make_info(tmp_path / "good.jpg", score=88)
    infos = [bad_drop, bad_restore, good]
    app.LAST_INFOS = infos
    app.SESSION = app.build_prescreen_session_from_infos(
        str(tmp_path),
        dry_run=True,
        mode="copy",
        infos=infos,
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=True,
        prescreen_strength="standard",
    )

    client = app.app.test_client()
    restored = client.post(
        "/api/restore_rejected",
        json={"group_id": "__prescreen__", "path": bad_restore.path},
        headers=LOCAL_HEADERS,
    ).get_json()
    confirmed = client.post("/api/confirm_prescreen", headers=LOCAL_HEADERS).get_json()

    assert restored["ok"] is True
    assert confirmed["ok"] is True
    for _ in range(20):
        if app._GROUPING["status"] != "running":
            break
        time.sleep(0.05)
    all_group_images = [p for group in app.SESSION.groups for p in group.images]
    assert good.path in all_group_images
    assert bad_restore.path in all_group_images
    assert bad_drop.path in all_group_images  # kept only as an auto-rejected loser record
    tournament_images = [
        p
        for group in app.SESSION.groups
        if not group.auto_rejected
        for p in group.images
    ]
    assert good.path in tournament_images
    assert bad_restore.path in tournament_images
    assert bad_drop.path not in tournament_images
    assert app.SESSION.prescreen_reviewed is True
