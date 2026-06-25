import os

import app as app_module


def test_app_main_sets_runtime_env(monkeypatch):
    called = {}

    monkeypatch.setattr(app_module, "setup_logger", lambda folder=None: None)
    monkeypatch.setattr(app_module, "_port_is_available", lambda host, port: True)
    monkeypatch.setattr(app_module.threading, "Timer", lambda *args, **kwargs: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(app_module.app, "run", lambda **kwargs: called.update(kwargs))
    monkeypatch.setattr(app_module, "SCRIPT_TOKEN", None)
    monkeypatch.setattr(app_module.sys, "argv", ["app.py", "--runtime", "cpu", "--port", "6060", "--no-browser"])

    app_module.main()

    assert os.environ["PIC_SELECTER_RUNTIME"] == "cpu"
    assert called["port"] == 6060


def test_app_main_reuses_existing_server(monkeypatch):
    called = {"run": False, "opened": None}

    monkeypatch.setattr(app_module, "setup_logger", lambda folder=None: None)
    monkeypatch.setattr(app_module, "_port_is_available", lambda host, port: False)
    monkeypatch.setattr(app_module, "_probe_existing_app", lambda port: True)
    monkeypatch.setattr(app_module, "_port_has_this_app_process", lambda port: False)
    monkeypatch.setattr(app_module.webbrowser, "open", lambda url: called.update(opened=url))
    monkeypatch.setattr(app_module.app, "run", lambda **kwargs: called.update(run=True))
    monkeypatch.setattr(app_module.sys, "argv", ["app.py", "--port", "6060"])

    app_module.main()

    assert called["run"] is False
    assert called["opened"] == "http://localhost:6060"


def test_app_main_reuses_existing_app_process_when_http_probe_hangs(monkeypatch):
    called = {"run": False, "opened": None}

    monkeypatch.setattr(app_module, "setup_logger", lambda folder=None: None)
    monkeypatch.setattr(app_module, "_port_is_available", lambda host, port: False)
    monkeypatch.setattr(app_module, "_probe_existing_app", lambda port: False)
    monkeypatch.setattr(app_module, "_port_has_this_app_process", lambda port: True)
    monkeypatch.setattr(app_module.webbrowser, "open", lambda url: called.update(opened=url))
    monkeypatch.setattr(app_module.app, "run", lambda **kwargs: called.update(run=True))
    monkeypatch.setattr(app_module.sys, "argv", ["app.py", "--port", "6060"])

    app_module.main()

    assert called["run"] is False
    assert called["opened"] == "http://localhost:6060"


def test_app_main_finds_next_port_when_occupied_by_other_program(monkeypatch):
    called = {}

    monkeypatch.setattr(app_module, "setup_logger", lambda folder=None: None)
    monkeypatch.setattr(app_module, "_port_is_available", lambda host, port: port == 6061)
    monkeypatch.setattr(app_module, "_probe_existing_app", lambda port: False)
    monkeypatch.setattr(app_module, "_port_has_this_app_process", lambda port: False)
    monkeypatch.setattr(app_module.threading, "Timer", lambda *args, **kwargs: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(app_module.app, "run", lambda **kwargs: called.update(kwargs))
    monkeypatch.setattr(app_module.sys, "argv", ["app.py", "--port", "6060", "--no-browser"])

    app_module.main()

    assert called["port"] == 6061


def test_apply_runtime_selection_resets_cached_device(monkeypatch):
    from pic_selecter import vision
    vision._DEVICE = "sentinel"
    monkeypatch.setenv("PIC_SELECTER_RUNTIME", "auto")

    app_module._apply_runtime_selection("cpu")

    assert os.environ["PIC_SELECTER_RUNTIME"] == "cpu"
    assert vision._DEVICE is None
