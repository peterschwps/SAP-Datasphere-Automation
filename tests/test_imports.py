from pathlib import Path


def test_tui_import_has_no_settings_or_workspace_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from datasphere_cli import settings as settings_module

    settings_file = tmp_path / "config" / "settings.toml"
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(settings_module, "settings", None)
    monkeypatch.chdir(tmp_path)

    from datasphere_cli import actions, cli, logging
    from datasphere_cli.cli import commands, screens
    from datasphere_cli.files import storage, workspace

    assert callable(cli.main)
    assert callable(commands.run)
    assert callable(actions.persist_views_from_file)
    assert callable(workspace.file_setup)
    assert callable(storage.read_task_csv)
    assert callable(logging.configure_logging)
    assert callable(screens.DatasphereApp)
    assert settings_module.settings is None
    assert not settings_file.exists()
    assert not (tmp_path / "datasphere").exists()
