def main() -> None:
    from datasphere_cli.utils.filehandler import (
        file_setup,
        load_settings,
    )
    from datasphere_cli.utils.logging import configure_logging
    from datasphere_cli.utils.screens import DatasphereApp

    configure_logging()
    load_settings()
    file_setup()
    DatasphereApp().run(mouse=False)
