def test_imports_do_not_require_settings() -> None:
    """
    Importing the package must not read a settings file, exit the
    program or create directories.
    """
    from sap_datasphere_automation import actions, cli
    from sap_datasphere_automation.utils import (
        filehandler,
        logging,
        screens,
    )

    assert callable(cli.main)
    assert callable(actions.persist_views)
    assert callable(filehandler.load_settings)
    assert callable(filehandler.build_config)
    assert callable(logging.configure_logging)
    assert callable(screens.DatasphereApp)
