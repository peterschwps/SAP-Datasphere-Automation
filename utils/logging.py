import inspect
import logging
import os.path
import textwrap
from collections.abc import Callable
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
if not os.path.exists(DIRECTORY_LOGS):
    os.makedirs(DIRECTORY_LOGS)

# Mapping of the logging levels to the rich colors
FORMATS = {
    logging.DEBUG: "blue",
    logging.INFO: "green",
    logging.WARNING: "yellow",
    logging.ERROR: "red",
    logging.CRITICAL: "bold red",
}

# Set up the logger
logger = logging.getLogger(__name__)


# Create formatter class for multiline strings
class MultiLineFormatter(logging.Formatter):
    """
    Formatter Class to handle multi-line messages, inherits from the logging
    module.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

    def format(self, record: logging.LogRecord) -> str:
        """
        Method that receives a LogRecord and converts it to the desired format.

        ARGS:
            - record: logging.LogRecord

        Returns:
            - str: formatted string
        """

        # Overwrite filename if call comes from wrapper function
        # (uses extra param 'location')
        # Otherwise logging.py would always be the filename in the log file
        log_data = record.__dict__
        if (
            log_data["funcName"] == "wrapper"
            and log_data["module"] == "logging"
        ) and "location" in log_data:
            log_data["filename"] = log_data["location"]

        # Get logging message (resolve %-formatting with args)
        message = record.getMessage()

        # Check if exception
        is_exception = record.exc_info is not None

        # Check if multiline message
        try:
            multiline_message = len(message.split("\n")) > 1
        except AttributeError:
            multiline_message = False

        # Save original msg/args to avoid mutating the record across handlers
        original_msg = record.msg
        original_args = record.args

        # Set msg to empty string (unless it is an exception) and clear args
        # to prevent %-formatting on an empty msg
        if not is_exception:
            record.msg = ""
            record.args = None

        # Format record (with empty message) to create header
        header = super().format(record)

        # Indent message by length of header (record without message)
        if multiline_message and not is_exception:
            # Create filler for line indentation matching the spaces
            # of the format
            empty_filler = "|".join(
                [" " * len(segment) for segment in header.split("|")]
            )

            # Indent first line and add header to the front
            msg = textwrap.indent(
                message.split("\n")[0], " " * len(header)
            ).lstrip()

            # Add all other lines without the header, only using the separation
            # signs (pipe symbols)
            for line in message.split("\n")[1:]:
                msg += textwrap.indent("\n" + line, empty_filler)

        elif not multiline_message and not is_exception:
            msg = textwrap.indent(message, " " * len(header)).lstrip()

        else:
            # Reformat message by adding type of error as the first line and
            # traceback as the consecutive lines
            record.msg = (
                f"*** {type(record.msg).__name__} ***\n{record.exc_text}"
            )

            # Set exception info and text to None so
            record.exc_info = None
            record.exc_text = None

            # Recursively call function (won't be detected as an error now and
            # handled like a normal record object)
            return self.format(record)

        # Restore original msg/args so other handlers see the unmodified record
        record.msg = original_msg
        record.args = original_args

        # Concatenate header and computed message
        log_message = header + msg
        return f"[{FORMATS[record.levelno]}]{log_message}[/]"


# Handler to print messages with rich
class RichPrintHandler(logging.StreamHandler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.console = get_console()
        self.console._highlight = False

    def emit(self, record: logging.LogRecord) -> None:
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

# Set up timed rotating file handler (creates one log file per day)
file_handler = TimedRotatingFileHandler(
    filename=(
        f"{DIRECTORY_LOGS}/{datetime.now().year}{datetime.now().month:02}"
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

# Add handlers to logger
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# Set level for logger (filtered by handlers)
logger.setLevel(logging.DEBUG)


# Wrapper to track execution time of a function
def track_time(func: Any) -> Callable[[Any], None]:
    """
    A decorator function to automatically log the execution time of a function.
    Uses the log level 'debug'.
    """

    def wrapper(*args: tuple[Any, ...], **kwargs: dict[str, Any]) -> None:
        # Start timer, function and calculate execution time
        start = datetime.now()
        func(*args, **kwargs)
        execution_time = datetime.now() - start

        # Try to retrieve filename (TypeError for built-ins)
        try:
            filename = inspect.getfile(func).split("\\")[-1]
            logger.debug(
                "Execution time of '%s' from '%s': %s seconds.",
                func.__name__,
                filename,
                round(execution_time.total_seconds(), 3),
                extra={"location": filename},
            )
        except (TypeError, IndexError):
            logger.debug(
                "Execution time of '%s' from '%s': %s seconds.",
                func.__name__,
                filename,
                round(execution_time.total_seconds(), 3),
            )

    return wrapper
