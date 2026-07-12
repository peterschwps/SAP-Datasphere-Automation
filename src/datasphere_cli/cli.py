def main() -> None:
    from datasphere_cli.utils.logging import configure_logging
    from datasphere_cli.utils.screens import DatasphereApp
    from datasphere_cli.utils.settings import load_settings

    configure_logging()
    load_settings()
    DatasphereApp().run(mouse=False)
