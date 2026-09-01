import shutil
import zipfile

from pic_selecter import material_organizer


def _zip_file(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def _direct_delete(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def test_parse_route_category_normalizes_wotu_names():
    assert material_organizer.parse_route_category(
        "无水印_7.18惠州冲浪_风景(已显示&已修未显示).zip"
    ) == ("7.18惠州冲浪", "风景")
    assert material_organizer.parse_route_category(
        "无水印_7.18惠州冲浪_合照(已显示&已修未显示)"
    ) == ("7.18惠州冲浪", "合照")
    assert material_organizer.parse_route_category(
        "无水印_7.18惠州冲浪_群像(已显示&已修未显示)"
    ) == ("7.18惠州冲浪", "合照")
    assert material_organizer.parse_route_category(
        "无水印_260711梅子坪_肖像权说明(已显示&已修未显示).zip"
    ) == ("260711梅子坪", "肖像权说明")


def test_organize_materials_extracts_deletes_archives_and_groups_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(material_organizer, "move_to_trash", _direct_delete)
    _zip_file(
        tmp_path / "无水印_7.18惠州冲浪_风景(已显示&已修未显示).zip",
        {"无水印_7.18惠州冲浪_风景(已显示&已修未显示)/已显示/a.jpg": b"a"},
    )
    _zip_file(
        tmp_path / "无水印_7.18惠州冲浪_合照(已显示&已修未显示).zip",
        {"b.jpg": b"b"},
    )
    _zip_file(
        tmp_path / "无水印_7.18惠州冲浪_肖像权说明(已显示&已修未显示).zip",
        {"无水印_7.18惠州冲浪_肖像权说明(已显示&已修未显示)/note.jpg": b"note"},
    )
    duplicate = tmp_path / "旧路线(1)"
    duplicate.mkdir()
    original = tmp_path / "旧路线"
    original.mkdir()

    summary = material_organizer.organize_materials(tmp_path)

    assert summary.extracted_archives == 3
    assert summary.deleted_archives == 3
    assert summary.deleted_duplicate_dirs == 1
    assert (tmp_path / "7.18惠州冲浪" / "风景" / "a.jpg").read_bytes() == b"a"
    assert not (tmp_path / "7.18惠州冲浪" / "风景" / "已显示").exists()
    assert not (tmp_path / "7.18惠州冲浪" / "风景" / "7.18惠州冲浪").exists()
    assert (tmp_path / "7.18惠州冲浪" / "合照" / "b.jpg").read_bytes() == b"b"
    assert (tmp_path / "7.18惠州冲浪" / "肖像权说明" / "note.jpg").read_bytes() == b"note"
    assert not list(tmp_path.glob("*.zip"))
    assert not duplicate.exists()
    assert original.exists()


def test_organize_existing_route_dirs_keeps_name_collisions(tmp_path, monkeypatch):
    monkeypatch.setattr(material_organizer, "move_to_trash", _direct_delete)
    scenic = tmp_path / "无水印_7.18惠州冲浪_风光(已显示&已修未显示)"
    people = tmp_path / "无水印_7.18惠州冲浪_人像(已显示&已修未显示)"
    scenic.mkdir()
    people.mkdir()
    (scenic / "same.jpg").write_bytes(b"a")
    (people / "same.jpg").write_bytes(b"b")

    summary = material_organizer.organize_materials(tmp_path)

    assert summary.organized_dirs == 2
    assert (tmp_path / "7.18惠州冲浪" / "风景" / "same.jpg").read_bytes() == b"a"
    assert (tmp_path / "7.18惠州冲浪" / "人像" / "same.jpg").read_bytes() == b"b"
    assert not scenic.exists()
    assert not people.exists()


def test_organize_flattens_already_nested_route_category_status_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(material_organizer, "move_to_trash", _direct_delete)
    nested = tmp_path / "7.18惠州冲浪" / "风景" / "7.18惠州冲浪" / "风景" / "已显示"
    nested.mkdir(parents=True)
    (nested / "a.jpg").write_bytes(b"a")

    summary = material_organizer.organize_materials(tmp_path)

    assert summary.moved_files == 1
    assert (tmp_path / "7.18惠州冲浪" / "风景" / "a.jpg").read_bytes() == b"a"
    assert not (tmp_path / "7.18惠州冲浪" / "风景" / "7.18惠州冲浪").exists()
