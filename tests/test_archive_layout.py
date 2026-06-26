import app as app_module


LOCAL_HEADERS = {"Origin": "http://localhost"}


def _write_photo(path):
    path.write_bytes(b"fake photo")
    return str(path)


def _session(tmp_path, group):
    return app_module.SessionState(
        folder=str(tmp_path),
        dry_run=False,
        mode="copy",
        groups=[group],
    )


def test_apply_group_archives_winners_by_face_category_and_losers_by_reason(tmp_path):
    src_dir = tmp_path / "A" / "B"
    src_dir.mkdir(parents=True)
    winner = _write_photo(src_dir / "winner.jpg")
    blurry = _write_photo(src_dir / "blurry.jpg")
    duplicate = _write_photo(tmp_path / "duplicate.jpg")
    group = app_module.GroupState(
        images=[winner, blurry, duplicate],
        winner=winner,
        losers=[blurry, duplicate],
        finished=True,
        auto_reject_reasons={blurry: "主体失焦"},
    )
    session = _session(tmp_path, group)
    session.meta[winner] = {"datetime": "2026-06-20T10:20:30", "face_count": 2}

    app_module.apply_group(group, str(tmp_path), dry_run=False, mode="copy", session=session)

    assert (tmp_path / "winners" / "人像" / "A" / "B" / "winner.jpg").exists()
    assert (tmp_path / "losers" / "模糊" / "A" / "B" / "blurry.jpg").exists()
    assert (tmp_path / "losers" / "重复落选" / "duplicate.jpg").exists()


def test_restore_rejected_archives_to_review_folder(tmp_path):
    src_dir = tmp_path / "set1"
    src_dir.mkdir()
    loser = _write_photo(src_dir / "loser.jpg")
    group = app_module.GroupState(
        images=[loser],
        losers=[loser],
        finished=True,
        auto_rejected=[loser],
        auto_reject_reasons={loser: "主体闭眼"},
    )
    session = _session(tmp_path, group)
    session.meta[loser] = {"face_count": 3}
    app_module.apply_group(group, str(tmp_path), dry_run=False, mode="copy", session=session)
    app_module.SESSION = session

    client = app_module.app.test_client()
    resp = client.post(
        "/api/restore_rejected",
        json={"group_id": group.id, "path": loser},
        headers=LOCAL_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert (tmp_path / "review" / "合照" / "set1" / "召回保留" / "loser.jpg").exists()


def test_face_count_archives_to_expected_winner_categories(tmp_path):
    expected = {
        0: "风景",
        1: "人像",
        2: "人像",
        3: "合照",
    }
    for count, category in expected.items():
        photo = _write_photo(tmp_path / f"face_{count}.jpg")
        group = app_module.GroupState(images=[photo], winner=photo, finished=True)
        session = _session(tmp_path, group)
        session.meta[photo] = {"face_count": count}

        app_module.apply_group(group, str(tmp_path), dry_run=False, mode="copy", session=session)

        assert (tmp_path / "winners" / category / f"face_{count}.jpg").exists()
