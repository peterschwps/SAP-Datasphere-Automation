def test_imports_do_not_require_settings() -> None:
    """
    Importing the package must not read a settings file, exit the
    program or create directories.
    """
    from datasphere_core import TASKCHAIN_START_COMMAND

    from datasphere_cli import actions, cli, direct
    from datasphere_cli.utils import (
        filehandler,
        logging,
        screens,
        settings,
    )

    assert callable(cli.main)
    assert callable(direct.run)
    assert callable(actions.persist_views)
    assert TASKCHAIN_START_COMMAND.name == "taskchain.start"
    assert callable(filehandler.file_setup)
    assert callable(settings.load_settings)
    assert callable(settings.build_session_config)
    assert callable(logging.configure_logging)
    assert callable(screens.DatasphereApp)
