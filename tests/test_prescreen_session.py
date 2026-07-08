import importlib
import io
import json
import sys
import time
import types
import zipfile
from pathlib import Path


def import_app_module():
    sys.modules.setdefault("imagehash", types.SimpleNamespace(phash=lambda *args, **kwargs: "0" * 16))
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def make_info(path: Path, score=80.0, auto_reject=False, reason=None, face_count=0):
    app = import_app_module()
    path.parent.mkdir(parents=True, exist_ok=True)
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
            "face_count": face_count,
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


def test_skip_duplicate_with_prescreen_archives_passed_and_restored_as_winners(tmp_path):
    app = import_app_module()
    drop = make_info(tmp_path / "drop.jpg", score=8, auto_reject=True, reason="严重模糊")
    restore = make_info(tmp_path / "restore.jpg", score=9, auto_reject=True, reason="曝光过低", face_count=1)
    good = make_info(tmp_path / "day1" / "good.jpg", score=88, face_count=0)
    infos = [drop, restore, good]
    app.LAST_INFOS = infos
    app.SESSION = app.build_prescreen_session_from_infos(
        str(tmp_path),
        dry_run=False,
        mode="copy",
        infos=infos,
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=True,
        prescreen_strength="standard",
        skip_duplicate_selection=True,
    )

    client = app.app.test_client()
    restored = client.post(
        "/api/restore_rejected",
        json={"group_id": "__prescreen__", "path": restore.path},
        headers=LOCAL_HEADERS,
    ).get_json()
    confirmed = client.post("/api/confirm_prescreen", headers=LOCAL_HEADERS).get_json()

    assert restored["ok"] is True
    assert confirmed["async"] is False
    assert app.SESSION.skip_duplicate_selection is True
    assert app.SESSION.prescreen_reviewed is True
    assert all(group.finished for group in app.SESSION.groups)
    assert (tmp_path / "winners" / "风景" / "day1" / "good.jpg").exists()
    assert (tmp_path / "winners" / "人像" / "restore.jpg").exists()
    assert (tmp_path / "losers" / "模糊" / "drop.jpg").exists()


def test_skip_duplicate_without_prescreen_keeps_all_readable_photos(tmp_path):
    app = import_app_module()
    one = make_info(tmp_path / "one.jpg", score=80, face_count=0)
    two = make_info(tmp_path / "nested" / "two.jpg", score=82, face_count=3)

    sess = app.build_keep_all_session_from_infos(
        str(tmp_path),
        dry_run=False,
        mode="copy",
        infos=[one, two],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=False,
        prescreen_strength="standard",
        engine="fast",
    )

    assert sess.skip_duplicate_selection is True
    assert len(sess.groups) == 2
    assert all(group.finished and group.winner for group in sess.groups)
    assert (tmp_path / "winners" / "风景" / "one.jpg").exists()
    assert (tmp_path / "winners" / "合照" / "nested" / "two.jpg").exists()


def test_refine_winners_reuses_archived_winners_and_sends_rejects_to_duplicate_losers(tmp_path, monkeypatch):
    app = import_app_module()
    one = make_info(tmp_path / "one.jpg", score=80, face_count=0)
    two = make_info(tmp_path / "two.jpg", score=82, face_count=0)
    app.LAST_INFOS = [one, two]
    app.SESSION = app.build_keep_all_session_from_infos(
        str(tmp_path),
        dry_run=False,
        mode="copy",
        infos=[one, two],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=False,
        prescreen_strength="standard",
        engine="fast",
    )
    archived_one = tmp_path / "winners" / "风景" / "one.jpg"
    archived_two = tmp_path / "winners" / "风景" / "two.jpg"
    assert archived_one.exists()
    assert archived_two.exists()

    monkeypatch.setattr(app, "group_infos", lambda infos, **kwargs: [infos])

    client = app.app.test_client()
    refined = client.post("/api/refine_winners", headers=LOCAL_HEADERS).get_json()

    assert refined["ok"] is True
    assert app.SESSION.mode == "move"
    assert app.SESSION.prescreen_enabled is False
    group = app.SESSION.groups[0]
    assert group.finished is False
    assert group.left == str(archived_one)
    assert group.right == str(archived_two)

    chosen = client.post(
        "/api/choose",
        json={"loser": "right"},
        headers=LOCAL_HEADERS,
    ).get_json()

    assert chosen["done"] is True
    assert archived_one.exists()
    assert not archived_two.exists()
    assert (tmp_path / "losers" / "重复落选" / "two.jpg").exists()


def test_training_decisions_log_pk_and_prescreen_restore_without_paths(tmp_path):
    app = import_app_module()
    left = make_info(tmp_path / "left.jpg", score=80, face_count=1)
    right = make_info(tmp_path / "right.jpg", score=70, face_count=0)
    app.SESSION = app.build_session_from_groups(
        str(tmp_path),
        dry_run=True,
        mode="copy",
        raw_groups=[[left, right]],
        infos=[left, right],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=False,
        prescreen_strength="standard",
        record_preferences=True,
        scene_label="旅行",
    )

    client = app.app.test_client()
    chosen = client.post(
        "/api/choose",
        json={"loser": "right"},
        headers=LOCAL_HEADERS,
    ).get_json()

    assert chosen["done"] is True
    log_path = app.decisions_log_path(str(tmp_path))
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["decision_type"] == "pk"
    assert records[0]["scene_label"] == "旅行"
    assert records[0]["winner"]["features"]["face_count"] == 1
    assert str(tmp_path) not in json.dumps(records, ensure_ascii=False)

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
        record_preferences=True,
        scene_label="旅行",
    )
    restored = client.post(
        "/api/restore_rejected",
        json={"group_id": "__prescreen__", "path": bad.path},
        headers=LOCAL_HEADERS,
    ).get_json()

    assert restored["ok"] is True
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["decision_type"] == "prescreen_restore"
    assert records[-1]["reject_reason"] == "严重模糊"
    assert str(tmp_path) not in json.dumps(records, ensure_ascii=False)


def test_training_export_contains_anonymized_jsonl_files(tmp_path):
    app = import_app_module()
    one = make_info(tmp_path / "one.jpg", score=80, face_count=1)
    two = make_info(tmp_path / "two.jpg", score=75, face_count=0)
    app.SESSION = app.build_session_from_groups(
        str(tmp_path),
        dry_run=True,
        mode="copy",
        raw_groups=[[one, two]],
        infos=[one, two],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=False,
        prescreen_strength="standard",
        record_preferences=True,
        scene_label="亲子",
    )

    client = app.app.test_client()
    client.post("/api/choose", json={"loser": "right"}, headers=LOCAL_HEADERS)
    resp = client.get("/api/training_export", headers=LOCAL_HEADERS)

    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = set(zf.namelist())
        assert {"decisions.jsonl", "features.jsonl", "session_meta.json"} <= names
        combined = (
            zf.read("decisions.jsonl").decode("utf-8") +
            zf.read("features.jsonl").decode("utf-8") +
            zf.read("session_meta.json").decode("utf-8")
        )
        meta = json.loads(zf.read("session_meta.json"))

    assert meta["scene_label"] == "亲子"
    assert meta["contains_images"] is False
    assert str(tmp_path) not in combined


def test_resume_restores_saved_session_and_meta(tmp_path):
    app = import_app_module()
    one = make_info(tmp_path / "one.jpg", score=80, face_count=2)
    two = make_info(tmp_path / "two.jpg", score=75, face_count=0)
    sess = app.build_session_from_groups(
        str(tmp_path),
        dry_run=True,
        mode="copy",
        raw_groups=[[one, two]],
        infos=[one, two],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=False,
        prescreen_strength="standard",
        scene_label="活动",
    )
    assert (app.state_path(str(tmp_path))).exists()
    app.SESSION = None
    app.LAST_INFOS = None

    client = app.app.test_client()
    resp = client.post(
        "/api/resume",
        json={"folder": str(tmp_path)},
        headers=LOCAL_HEADERS,
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["resumed"] is True
    assert app.SESSION is not None
    assert app.SESSION.scene_label == "活动"
    assert app.SESSION.meta[one.path]["face_count"] == 2
    assert app.SESSION.groups[0].left == sess.groups[0].left


def test_state_save_load_uses_utf8_for_non_gbk_text(tmp_path):
    app = import_app_module()
    one = make_info(tmp_path / "emoji.jpg", score=80)
    sess = app.build_session_from_groups(
        str(tmp_path),
        dry_run=True,
        mode="copy",
        raw_groups=[[one]],
        infos=[one],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=False,
        prescreen_strength="standard",
        scene_label="旅行🚣",
    )

    app.save_state(sess)
    loaded = app.load_state(str(tmp_path))

    assert loaded is not None
    assert loaded.scene_label == "旅行🚣"


def test_start_requires_explicit_force_restart_when_prior_state_exists(tmp_path):
    app = import_app_module()
    one = make_info(tmp_path / "one.jpg", score=80)
    app.build_keep_all_session_from_infos(
        str(tmp_path),
        dry_run=True,
        mode="copy",
        infos=[one],
        threshold_near=10,
        threshold_far=6,
        near_seconds=300,
        prescreen_enabled=False,
        prescreen_strength="standard",
        engine="fast",
    )

    client = app.app.test_client()
    resp = client.post(
        "/api/start",
        json={"folder": str(tmp_path), "engine": "fast"},
        headers=LOCAL_HEADERS,
    )

    assert resp.status_code == 409
    assert resp.get_json()["has_prior"] is True
