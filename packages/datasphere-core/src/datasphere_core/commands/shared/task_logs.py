import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from datasphere_core.commands.shared.conversion import format_runtime
from datasphere_core.runtime.context import CommandContext

logger = logging.getLogger(__name__)

# Reads the task log of one started run
type LogFetcher = Callable[
    [CommandContext, int, str], Awaitable[dict[str, Any]]
]

# Seconds between two polls of a running task log
POLL_INTERVAL_SECONDS = 1

# Seconds between two messages about a run that is still going
ANNOUNCE_INTERVAL_SECONDS = 5


def announce_runtime(description: str, started: float, last: float) -> float:
    """
    Reports how long a run is already going, so a wait of minutes does not
    look like a hanging program. Stays quiet until the interval passed.

    Args:
        description (str): What is waited for, e.g. "view 'V_SALES'".
        started (float): Monotonic time the wait started at.
        last (float): Monotonic time of the last message.

    Returns:
        float: Monotonic time of the last message, moved forward whenever
               one was written.
    """
    now = time.monotonic()
    if now - last < ANNOUNCE_INTERVAL_SECONDS:
        return last
    logger.info(
        "Waiting for %s to finish. Current runtime %s.",
        description,
        format_runtime(now - started),
    )
    return now


async def await_task_log(
    context: CommandContext,
    fetch: LogFetcher,
    *,
    log_id: int,
    space: str,
    description: str,
    timeout_seconds: float | None,
) -> tuple[bool, dict[str, Any]]:
    """
    Polls the task log of a started run until it leaves the running state.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.
        fetch (LogFetcher): Reads the task log of the run.
        log_id (int): Task log ID of the started run.
        space (str): Technical name of the Datasphere space.
        description (str): What is waited for, e.g. "view 'V_SALES'". The
                           task log alone does not name it.
        timeout_seconds (float | None): Maximum polling duration, or None to
                                        poll without a limit.

    Raises:
        TimeoutError: If the run is still going when the timeout expires.

    Returns:
        tuple[bool, dict[str, Any]]: Whether the run completed, and its log
                                     details.
    """
    started = time.monotonic()
    announced = started
    async with asyncio.timeout(timeout_seconds):
        while True:
            # Announce at the top, so nothing is reported before the first
            # wait and both exits below stay untouched
            announced = announce_runtime(description, started, announced)
            details = await fetch(context, log_id, space)

            # The log itself does not carry its own ID
            details["logId"] = log_id

            status = details["status"]
            if status == "COMPLETED":
                return True, details
            if status != "RUNNING":
                return False, details
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
