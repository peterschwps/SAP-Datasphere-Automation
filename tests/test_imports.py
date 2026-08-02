from pathlib import Path


def test_tui_import_has_no_settings_or_workspace_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that importing the TUI modules touches neither disk nor settings.
    """
    from datasphere_cli import settings as settings_module

    settings_file = tmp_path / "config" / "settings.toml"
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(settings_module, "settings", None)
    monkeypatch.chdir(tmp_path)

    from datasphere_cli import actions, cli, logging
    from datasphere_cli.cli import screens, task_chains
    from datasphere_cli.files import storage, workspace

    assert callable(cli.main)
    assert callable(task_chains.run)
    assert callable(actions.persist_views_from_file)
    assert callable(workspace.file_setup)
    assert callable(storage.read_task_csv)
    assert callable(logging.configure_logging)
    assert callable(screens.DatasphereApp)
    # Loading the settings on import would create the file and open a
    # browser, and the workspace must only appear once the TUI really starts
    assert settings_module.settings is None
    assert not settings_file.exists()
    assert not (tmp_path / "datasphere").exists()
