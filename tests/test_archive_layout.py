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


def test_apply_group_archives_winners_by_date_and_losers_by_reason(tmp_path):
    winner = _write_photo(tmp_path / "winner.jpg")
    blurry = _write_photo(tmp_path / "blurry.jpg")
    duplicate = _write_photo(tmp_path / "duplicate.jpg")
    group = app_module.GroupState(
        images=[winner, blurry, duplicate],
        winner=winner,
        losers=[blurry, duplicate],
        finished=True,
        auto_reject_reasons={blurry: "主体失焦"},
    )
    session = _session(tmp_path, group)
    session.meta[winner] = {"datetime": "2026-06-20T10:20:30"}

    app_module.apply_group(group, str(tmp_path), dry_run=False, mode="copy", session=session)

    assert (tmp_path / "winners" / "2026-06-20" / "winner.jpg").exists()
    assert (tmp_path / "losers" / "模糊" / "blurry.jpg").exists()
    assert (tmp_path / "losers" / "重复落选" / "duplicate.jpg").exists()


def test_restore_rejected_archives_to_review_folder(tmp_path):
    loser = _write_photo(tmp_path / "loser.jpg")
    group = app_module.GroupState(
        images=[loser],
        losers=[loser],
        finished=True,
        auto_rejected=[loser],
        auto_reject_reasons={loser: "主体闭眼"},
    )
    session = _session(tmp_path, group)
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
    assert (tmp_path / "review" / "召回保留" / "loser.jpg").exists()
