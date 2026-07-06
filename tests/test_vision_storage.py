import os

from pic_selecter import vision


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield b"model-zip"


def test_model_storage_is_project_local_and_migrates_legacy_cache(tmp_path):
    project_root = tmp_path / "project"
    legacy_cache = tmp_path / "legacy_home" / ".cache"

    old_hf = legacy_cache / "huggingface" / "hub" / "models--facebook--dinov2-small" / "refs"
    old_hf.mkdir(parents=True)
    (old_hf / "main").write_text("ed25f3a", encoding="utf-8")

    old_torch = legacy_cache / "torch" / "hub" / "checkpoints"
    old_torch.mkdir(parents=True)
    (old_torch / "mobilenet_v2-7ebf99e0.pth").write_bytes(b"torch-weight")

    old_insight = legacy_cache / "pic_selecter" / "insightface" / "models" / "buffalo_l"
    old_insight.mkdir(parents=True)
    (old_insight / "det_10g.onnx").write_bytes(b"onnx-weight")

    env_keys = [
        "HF_HOME",
        "HUGGINGFACE_HUB_CACHE",
        "HF_HUB_CACHE",
        "HUGGINGFACE_ASSETS_CACHE",
        "TRANSFORMERS_CACHE",
        "HF_XET_CACHE",
        "TORCH_HOME",
    ]
    old_env = {key: os.environ.get(key) for key in env_keys}

    old_ready = vision._MODEL_STORAGE_READY
    old_project_root = vision._project_root
    old_legacy_cache_base = vision._legacy_cache_base
    try:
        vision._MODEL_STORAGE_READY = False
        vision._project_root = lambda: project_root
        vision._legacy_cache_base = lambda: legacy_cache

        vision._ensure_model_storage_configured()

        models_root = project_root / "models"
        assert vision._cache_dir() == models_root
        assert os.environ["HF_HOME"] == str(models_root / "huggingface")
        assert os.environ["HF_HUB_CACHE"] == str(models_root / "huggingface" / "hub")
        assert os.environ["HF_ENDPOINT"] == vision.HF_MIRROR
        assert os.environ["TORCH_HOME"] == str(models_root / "torch")

        assert (models_root / "huggingface" / "hub" / "models--facebook--dinov2-small" / "refs" / "main").exists()
        assert (models_root / "torch" / "hub" / "checkpoints" / "mobilenet_v2-7ebf99e0.pth").exists()
        assert (models_root / "insightface" / "models" / "buffalo_l" / "det_10g.onnx").exists()

        assert not (legacy_cache / "huggingface" / "hub" / "models--facebook--dinov2-small").exists()
        assert not (legacy_cache / "torch" / "hub" / "checkpoints" / "mobilenet_v2-7ebf99e0.pth").exists()
        assert not (legacy_cache / "torch" / "hub" / "clip" / "RN50.pt").exists()
        assert not (legacy_cache / "torch" / "hub" / "pyiqa").exists()
        assert not (legacy_cache / "pic_selecter" / "insightface").exists()
    finally:
        vision._MODEL_STORAGE_READY = old_ready
        vision._project_root = old_project_root
        vision._legacy_cache_base = old_legacy_cache_base
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_download_file_ignores_locked_fixed_tmp_name(tmp_path, monkeypatch):
    dest = tmp_path / "buffalo_l.zip"
    locked_tmp_name = dest.with_suffix(dest.suffix + ".tmp")
    locked_tmp_name.mkdir()

    def fake_get(url, stream, timeout, verify):
        return _FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)

    vision._download_file("https://example.test/buffalo_l.zip", dest)

    assert dest.read_bytes() == b"model-zip"
    assert locked_tmp_name.is_dir()
    assert not list(tmp_path.glob("buffalo_l.zip.*.tmp"))


def test_prewarm_step_wraps_network_timeout():
    def fail():
        raise OSError("[WinError 10060] 由于连接方在一段时间后没有正确答复")

    try:
        vision._prewarm_step("DINOv2", fail)
    except vision.VisionUnavailable as e:
        message = str(e)
    else:
        raise AssertionError("expected VisionUnavailable")

    assert "DINOv2 模型下载超时" in message
    assert "WinError 10060" in message
