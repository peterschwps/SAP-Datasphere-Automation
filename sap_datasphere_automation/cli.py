def main() -> None:
    from sap_datasphere_automation.utils.filehandler import (
        file_setup,
        load_settings,
    )
    from sap_datasphere_automation.utils.logging import configure_logging
    from sap_datasphere_automation.utils.screens import DatasphereApp

    configure_logging()
    load_settings()
    file_setup()
    DatasphereApp().run(mouse=False)
