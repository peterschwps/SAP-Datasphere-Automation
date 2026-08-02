import logging
import os.path
import textwrap
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Any

from rich import get_console

# Define constants
LEVEL_LOGS = logging.DEBUG  # Logging level for output to logs
LEVEL_STREAM = logging.DEBUG  # Logging level for output to stdout (console)

# Configure path for logs
PROJECT_PATH = os.getcwd()
DIRECTORY_LOGS = os.path.join(PROJECT_PATH, ".logs")

# Name of the datasphere-api library logger to capture its output
LIBRARY_LOGGER_NAME = "datasphere_api"

# Mapping of the logging levels to the rich colors
FORMATS = {
    logging.DEBUG: "#223548",
    logging.INFO: "#188918",
    logging.WARNING: "#C35500",
    logging.ERROR: "#D20A0A",
    logging.CRITICAL: "bold #AA0808",
}

# Set up the logger
logger = logging.getLogger(__name__)


# Create formatter class for multiline strings
class MultiLineFormatter(logging.Formatter):
    """
    Formatter Class to handle multi-line messages, inherits from the logging
    module.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Converts one log record into the indented output format. Multi-line
        messages keep the column layout of the header, so the separators line
        up across every line of the record.

        Args:
            record (logging.LogRecord): Log record to format.

        Returns:
            str: Formatted message wrapped in the rich color of its level.
        """
        message = record.getMessage()
        is_exception = record.exc_info is not None
        try:
            multiline_message = len(message.split("\n")) > 1
        except AttributeError:
            multiline_message = False

        # Keep the original message, because the same record object
        # reaches every handler and is blanked below
        original_msg = record.msg
        original_args = record.args

        # Blank the message to format the header on its own
        # Args have to go too, or %-formatting fails on the empty message
        if not is_exception:
            record.msg = ""
            record.args = None
        header = super().format(record)

        if multiline_message and not is_exception:
            # Blank out every header segment but keep the pipes, so the
            # following lines stay in the columns of the first one
            empty_filler = "|".join(
                [" " * len(segment) for segment in header.split("|")]
            )
            msg = textwrap.indent(
                message.split("\n")[0], " " * len(header)
            ).lstrip()
            for line in message.split("\n")[1:]:
                msg += textwrap.indent("\n" + line, empty_filler)

        elif not multiline_message and not is_exception:
            msg = textwrap.indent(message, " " * len(header)).lstrip()

        else:
            # Rewrite the exception as error type plus traceback
            # Clearing both fields sends the recursion into the branch above
            record.msg = (
                f"*** {type(record.msg).__name__} ***\n{record.exc_text}"
            )
            record.exc_info = None
            record.exc_text = None
            return self.format(record)

        record.msg = original_msg
        record.args = original_args
        log_message = header + msg
        return f"[{FORMATS[record.levelno]}]{log_message}[/]"


# Handler to print messages with rich
class RichPrintHandler(logging.StreamHandler):
    """
    Logging handler that prints messages through the rich console.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        """
        Initializes the handler with the shared rich console.

        Args:
            *args (Any): Positional arguments of the stream handler.
            **kwargs (Any): Keyword arguments of the stream handler.
        """
        super().__init__(*args, **kwargs)
        self.console = get_console()

    def emit(self, record: logging.LogRecord) -> None:
        """
        Prints one formatted log record to the console.

        Args:
            record (logging.LogRecord): Log record to print.
        """
        self.console.print(self.format(record), highlight=False)


# Set up formatters
FILE_FORMAT = MultiLineFormatter(
    fmt="{asctime}.{msecs:03.0f} | {levelname:^15s} | {filename:^30s} |"
    + "{:^20s}".format("Line: {lineno:04}")
    + "| {message}",
    datefmt="%Y-%m-%d | %H:%M:%S",
    style="{",
)

STREAM_FORMAT = MultiLineFormatter(
    fmt="{asctime}.{msecs:03.0f} | {levelname:^10s}" + "| {message}",
    datefmt="%Y-%m-%d | %H:%M:%S",
    style="{",
)


def configure_logging() -> None:
    """
    Configures the application logger and the datasphere-api library
    logger with the rich stream handler and the daily rotating file
    handler. Creates the log directory if it doesn't exist yet.
    """
    # Create log directory if it doesn't exist
    if not os.path.exists(DIRECTORY_LOGS):
        os.makedirs(DIRECTORY_LOGS)

    # Set up timed rotating file handler (creates one log file per day)
    file_handler = TimedRotatingFileHandler(
        filename=(
            f"{DIRECTORY_LOGS}/{datetime.now().year}"
            f"{datetime.now().month:02}"
            f"{datetime.now().day:02}.log"
        ),
        when="midnight",
        encoding="utf-8",
    )
    file_handler.setFormatter(FILE_FORMAT)
    file_handler.setLevel(LEVEL_LOGS)

    # Set up stream handler
    stream_handler = RichPrintHandler()
    stream_handler.setFormatter(STREAM_FORMAT)
    stream_handler.setLevel(LEVEL_STREAM)

    # Attach both handlers to our logger and the library logger
    library_logger = logging.getLogger(LIBRARY_LOGGER_NAME)
    for log in (logger, library_logger):
        log.addHandler(file_handler)
        log.addHandler(stream_handler)
        log.setLevel(logging.DEBUG)  # filtered by handlers
        log.propagate = False
