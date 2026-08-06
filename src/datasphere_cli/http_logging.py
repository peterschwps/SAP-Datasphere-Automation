import os
from pathlib import Path

from datasphere_core import start_http_logging

from datasphere_cli.files.workspace import http_logging_path

# Environment variable switching the logging on, and the one overriding the
# file it is written to
HTTP_LOGGING_VARIABLE = "DATASPHERE_HTTP_LOGGING"
HTTP_LOGGING_FILE_VARIABLE = "DATASPHERE_HTTP_LOGGING_FILE"

# Value the variable has to carry, every other one leaves logging off
_ENABLED_VALUE = "1"


def configure_http_logging(root: str | Path | None = None) -> Path | None:
    """
    Starts logging every request and response when the environment asks for
    it. Creates nothing otherwise, so an ordinary run never finds a
    workspace it did not ask for.

    Args:
        root (str | Path | None, optional): Explicit workspace root. Uses the
                                            current working directory when
                                            None. Defaults to None.

    Returns:
        Path | None: Path of the log file, or None while logging is off.
    """
    if os.environ.get(HTTP_LOGGING_VARIABLE) != _ENABLED_VALUE:
        return None

    override = os.environ.get(HTTP_LOGGING_FILE_VARIABLE)
    path = start_http_logging(
        Path(override) if override else http_logging_path(root)
    )
    return path
