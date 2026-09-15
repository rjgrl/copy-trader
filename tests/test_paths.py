"""Tests for frozen/dev path resolution."""

from __future__ import annotations

from pathlib import Path

import app.utils.paths as paths


def test_dev_persistent_root_is_project_root(monkeypatch) -> None:
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    root = paths.get_persistent_root()
    assert root == paths.get_project_root()
    assert (root / "app").is_dir() or root.name == "copy-trader"


def test_frozen_persistent_root_uses_localappdata(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = paths.get_persistent_root()
    assert root == tmp_path / "TelegramMT5Copier"
    assert root.is_dir()
    assert paths.get_default_data_dir() == root / "data"
    assert paths.get_default_log_dir() == root / "logs"
    assert paths.get_env_file_path() == root / ".env"


def test_resolve_user_path_relative(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    resolved = paths.resolve_user_path("data")
    assert resolved == tmp_path / "TelegramMT5Copier" / "data"


def test_settings_defaults_follow_persistent_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from app.config.settings import AppSettings, reset_settings_cache

    reset_settings_cache()
    settings = AppSettings()
    assert settings.data_dir == tmp_path / "TelegramMT5Copier" / "data"
    assert settings.log_dir == tmp_path / "TelegramMT5Copier" / "logs"
    assert settings.database_path == settings.data_dir / "copier.db"
    assert "MEIPASS" not in str(settings.data_dir).upper()
