def main() -> None:
    from datasphere_cli.utils.filehandler import file_setup
    from datasphere_cli.utils.logging import configure_logging
    from datasphere_cli.utils.screens import DatasphereApp
    from datasphere_cli.utils.settings import load_settings

    configure_logging()
    load_settings()
    file_setup()
    DatasphereApp().run(mouse=False)
