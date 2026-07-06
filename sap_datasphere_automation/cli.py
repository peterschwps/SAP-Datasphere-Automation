def main() -> None:
    from sap_datasphere_automation.utils.filehandler import file_setup
    from sap_datasphere_automation.utils.screens import DatasphereApp

    file_setup()
    DatasphereApp().run(mouse=False)
