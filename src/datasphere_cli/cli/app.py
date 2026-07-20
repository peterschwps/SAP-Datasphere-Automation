import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Entrypoint for the SAP-Datasphere-CLI.

    Args:
        argv (Sequence[str] | None, optional): Optional arguments to directly
                                               execute a task.
                                               Defaults to None.

    Returns:
        int: Exit code.
    """

    # Non-interactive mode: if arguments are provided, run the direct command
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        from datasphere_cli.cli.commands import run

        return run(arguments)

    # Non-interactive mode: if no arguments are provided, start the TUI
    from datasphere_cli.cli.screens import DatasphereApp
    from datasphere_cli.files.workspace import file_setup
    from datasphere_cli.logging import configure_logging
    from datasphere_cli.settings import load_settings

    configure_logging()
    load_settings()
    file_setup()
    DatasphereApp().run(mouse=False)
    return 0
