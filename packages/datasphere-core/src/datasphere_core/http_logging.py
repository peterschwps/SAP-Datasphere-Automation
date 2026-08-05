import atexit
import json
import logging
import os
import platform
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

# Raise this whenever the record format changes, so a reader can tell the
# formats apart
HTTP_LOGGING_VERSION = 1

# Carry the identifier and the start time of a request under this key
_EXTENSION_KEY = "datasphere_http_logging"


class HttpLogging:
    """
    Append-only JSON Lines writer for one run. Every event becomes one line
    and is flushed right away, so an interrupted run keeps everything that
    happened up to the interruption.
    """

    def __init__(self, path: Path) -> None:
        """
        Opens the log file and prepares the event counter.

        Args:
            path (Path): File to write to. Replaces the file of a previous
                         run.
        """
        self.path = path
        self.run_id = uuid4().hex
        self._sequence = 0
        self._lock = threading.Lock()
        self._started = time.perf_counter()

        # Pin the newline, because a reader splits the file on '\n' and
        # would otherwise find a stray carriage return on Windows
        self._file: TextIO | None = path.open(
            "w",
            encoding="utf-8",
            newline="\n",
        )

    @property
    def event_count(self) -> int:
        """
        Returns the number of events written so far.

        Returns:
            int: Number of events written to the log file.
        """
        return self._sequence

    def write(self, event: str, fields: dict[str, Any]) -> None:
        """
        Writes one event as a single JSON line. A failing log switches
        itself off instead of taking the program down with it.

        Args:
            event (str): Name of the event, for example 'http_request'.
            fields (dict[str, Any]): Payload merged into the envelope.
        """
        with self._lock:
            if self._file is None:
                return
            try:
                self._sequence += 1
                record = {
                    "version": HTTP_LOGGING_VERSION,
                    "sequence": self._sequence,
                    "timestamp": datetime.now(UTC).isoformat(
                        timespec="milliseconds"
                    ),
                    "event": event,
                    "run_id": self.run_id,
                    "thread": threading.current_thread().name,
                    **fields,
                }

                # Degrade an unexpected type to its repr instead of raising
                self._file.write(
                    json.dumps(
                        record,
                        default=str,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                self._file.write("\n")
                self._file.flush()

            except Exception:
                # Report once and stay off from here on
                self._file = None
                logger.warning(
                    "Unable to write the HTTP log. Logging is now off."
                )

    def close(self) -> None:
        """
        Closes the log file. Does nothing when it is closed already.
        """
        with self._lock:
            if self._file is None:
                return
            file = self._file
            self._file = None
            try:
                file.close()
            except Exception:
                logger.warning("Unable to close the HTTP log.")

    def elapsed_milliseconds(self) -> float:
        """
        Returns the time that passed since the log was opened.

        Returns:
            float: Milliseconds since the log file was opened.
        """
        return (time.perf_counter() - self._started) * 1000


_current: HttpLogging | None = None
_registered = False


def _package_version(name: str) -> str:
    """
    Reads the installed version of one package.

    Args:
        name (str): Distribution name of the package.

    Returns:
        str: Installed version, or 'dev' when the package is not installed.
    """
    try:
        return version(name)
    except PackageNotFoundError:
        return "dev"


def is_http_logging() -> bool:
    """
    Returns whether the requests of this run are logged. Every caller that
    would have to build a payload asks this first, so switched-off logging
    costs one lookup.

    Returns:
        bool: Whether events are recorded.
    """
    return _current is not None


def start_http_logging(path: str | Path) -> Path:
    """
    Starts logging every request and response of this run. Replaces the
    file of a previous run and records the opening event.

    Args:
        path (str | Path): File to write to.

    Returns:
        Path: Path of the log file.
    """
    global _current, _registered
    stop_http_logging()

    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _current = HttpLogging(log_path)

    # Close the file on exit, because the program leaves through sys.exit()
    # in more than one place
    if not _registered:
        atexit.register(stop_http_logging)
        _registered = True

    record(
        "run_started",
        pid=os.getpid(),
        cwd=str(Path.cwd()),
        argv=list(sys.argv),
        python=sys.version.split()[0],
        platform=platform.platform(),
        core_version=_package_version("datasphere-core"),
    )
    return log_path


def stop_http_logging() -> None:
    """
    Records the closing event and closes the log file. Does nothing while
    nothing is logged.
    """
    global _current
    if _current is None:
        return
    record(
        "run_finished",
        duration_ms=round(_current.elapsed_milliseconds(), 3),
        # Count the closing event itself, so the number matches the lines of
        # a complete log file
        event_count=_current.event_count + 1,
    )
    current = _current
    _current = None
    current.close()


def record(event: str, /, **fields: Any) -> None:
    """
    Records one event. Callers building an expensive payload guard the call
    with is_http_logging().

    Args:
        event (str): Name of the event, for example 'http_request'.
        **fields (Any): Payload merged into the envelope of the event.
    """
    current = _current
    if current is None:
        return
    current.write(event, fields)


def http_logging_hooks() -> dict[str, list[Callable[..., Awaitable[None]]]]:
    """
    Returns the httpx event hooks recording every request and response.
    Stays empty while logging is off, so a client built without logging
    carries no interception at all.

    Returns:
        dict[str, list[Callable[..., Awaitable[None]]]]: Mapping for the
                                                         'event_hooks'
                                                         argument of an
                                                         httpx client.
    """
    if not is_http_logging():
        return {}
    return {"request": [_on_request], "response": [_on_response]}


async def _on_request(request: httpx.Request) -> None:
    """
    Records one outgoing request with its headers and body.

    Args:
        request (httpx.Request): Request about to be sent.
    """
    if not is_http_logging():
        return

    # Carry the identifier on the request itself, because httpx hands the
    # very same object to the response hook. A registry keyed by the request
    # would leak entries whenever the transport raises before the response.
    request_id = uuid4().hex
    request.extensions[_EXTENSION_KEY] = (request_id, time.perf_counter())

    # Skip a streaming upload, because reading it here would consume it
    try:
        content: bytes | None = request.content
    except httpx.RequestNotRead:
        content = None

    record(
        "http_request",
        request_id=request_id,
        method=request.method,
        url=str(request.url),
        path=request.url.path,
        headers=dict(request.headers),
        body=_body(content),
        body_bytes=None if content is None else len(content),
        tenant_request_id=request.headers.get("x-request-id"),
    )


async def _on_response(response: httpx.Response) -> None:
    """
    Records one response with its headers and body.

    Args:
        response (httpx.Response): Response the tenant returned.
    """
    if not is_http_logging():
        return

    # Read the body here, because httpx calls this hook before the client
    # reads it. The result is cached, so the caller reads it for free. This
    # rules out streaming responses, which this library never sends.
    await response.aread()

    request_id, started = response.request.extensions.get(
        _EXTENSION_KEY,
        (None, None),
    )
    record(
        "http_response",
        request_id=request_id,
        status_code=response.status_code,
        reason_phrase=response.reason_phrase,
        http_version=response.http_version,
        headers=dict(response.headers),
        body=_body(response.content),
        body_bytes=len(response.content),
        # Measure by hand, because 'elapsed' is only set once the stream
        # closed and raises until then
        duration_ms=(
            None
            if started is None
            else round((time.perf_counter() - started) * 1000, 3)
        ),
        redirect_to=(
            str(response.headers.get("location"))
            if response.has_redirect_location
            else None
        ),
    )


def _body(content: bytes | None) -> Any:
    """
    Turns one body into the most useful representation. JSON becomes a real
    object, so a reader can query the log without decoding a string first.
    The content type is not consulted, because a tenant serves JSON with the
    wrong one often enough.

    Args:
        content (bytes | None): Body of a request or a response. None when
                                the body was never read.

    Returns:
        Any: Object for a JSON body, text for a readable one, the byte count
             for anything else, and None for an empty body.
    """
    if not content:
        return None
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {"binary_bytes": len(content)}
    try:
        return json.loads(text)
    except ValueError:
        return text
