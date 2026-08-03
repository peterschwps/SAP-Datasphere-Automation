import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from datasphere_core.context import CommandContext

# Reads the task log of one started run
type LogFetcher = Callable[
    [CommandContext, int, str], Awaitable[dict[str, Any]]
]

# Seconds between two polls of a running task log
POLL_INTERVAL_SECONDS = 1


async def await_task_log(
    context: CommandContext,
    fetch: LogFetcher,
    *,
    log_id: int,
    space: str,
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
        timeout_seconds (float | None): Maximum polling duration, or None to
                                        poll without a limit.

    Raises:
        TimeoutError: If the run is still going when the timeout expires.

    Returns:
        tuple[bool, dict[str, Any]]: Whether the run completed, and its log
                                     details.
    """
    async with asyncio.timeout(timeout_seconds):
        while True:
            details = await fetch(context, log_id, space)

            # The log itself does not carry its own ID
            details["logId"] = log_id

            status = details["status"]
            if status == "COMPLETED":
                return True, details
            if status != "RUNNING":
                return False, details
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
