import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from datasphere_core.context import CommandContext
from datasphere_core.errors import CommandCancelledError, CommandTimeoutError

# Reads the task log of one started run
type LogFetcher = Callable[[int, str], Awaitable[dict[str, Any]]]

# Seconds between two polls of a running task log
POLL_INTERVAL_SECONDS = 1


async def _await_task_log(
    fetch: LogFetcher,
    *,
    log_id: int,
    space: str,
    timeout_seconds: float | None,
) -> tuple[bool, dict[str, Any]]:
    """
    Polls the task log of a started run until it leaves the running state.

    Args:
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
            details = await fetch(log_id, space)

            # The log itself does not carry its own ID
            details["logId"] = log_id

            status = details["status"]
            if status == "COMPLETED":
                return True, details
            if status != "RUNNING":
                return False, details
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def run_persistence(
    context: CommandContext,
    *,
    view: str,
    space: str,
    timeout_seconds: float | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Persists one view and waits for the run to finish. Does not check whether
    the view is persisted already.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.
        timeout_seconds (float | None, optional): Maximum polling duration.
                                                  Defaults to None.

    Raises:
        CommandTimeoutError: If the run is still going when the timeout
                             expires. It continues remotely.
        CommandCancelledError: If polling is cancelled after the run started.
                               It continues remotely.

    Returns:
        tuple[bool, dict[str, Any]]: Whether the run completed, and its log
                                     details. Both are empty if the run never
                                     started.
    """
    log_id = await context.client.views.start_persistence(view, space)
    if log_id is None:
        return False, {}

    try:
        return await _await_task_log(
            context.client.views.get_extended_log,
            log_id=log_id,
            space=space,
            timeout_seconds=timeout_seconds,
        )
    except TimeoutError:
        raise CommandTimeoutError(
            f"Persistence of view '{view}' in '{space}' timed out. "
            "The remote operation may continue.",
            log_id=str(log_id),
        ) from None
    except asyncio.CancelledError:
        raise CommandCancelledError(
            f"Persistence of view '{view}' in '{space}' was cancelled. "
            "The remote operation may continue.",
            log_id=str(log_id),
        ) from None


async def run_persistence_removal(
    context: CommandContext,
    *,
    view: str,
    space: str,
    timeout_seconds: float | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Removes the persisted data of one view and waits for the run to finish.
    Views without persisted data are reported as done without starting a run.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.
        timeout_seconds (float | None, optional): Maximum polling duration.
                                                  Defaults to None.

    Raises:
        CommandTimeoutError: If the run is still going when the timeout
                             expires. It continues remotely.
        CommandCancelledError: If polling is cancelled after the run started.
                               It continues remotely.

    Returns:
        tuple[bool, dict[str, Any]]: Whether the removal succeeded, and its log
                                     details. Empty details mean that nothing
                                     had to be removed, or that no run started.
    """
    # An unreadable monitor cannot tell whether there is anything to remove
    monitor_details = await context.client.views.get_monitor_details(
        view,
        space,
    )
    if "dataPersistency" not in monitor_details:
        return False, {}
    if monitor_details["dataPersistency"] != "Persisted":
        return True, {}

    log_id = await context.client.views.start_persistence_removal(view, space)
    if log_id is None:
        return False, {}

    try:
        return await _await_task_log(
            context.client.views.get_extended_log,
            log_id=log_id,
            space=space,
            timeout_seconds=timeout_seconds,
        )
    except TimeoutError:
        raise CommandTimeoutError(
            f"Removing the persistence of view '{view}' in '{space}' timed "
            "out. The remote operation may continue.",
            log_id=str(log_id),
        ) from None
    except asyncio.CancelledError:
        raise CommandCancelledError(
            f"Removing the persistence of view '{view}' in '{space}' was "
            "cancelled. The remote operation may continue.",
            log_id=str(log_id),
        ) from None


async def run_chain(
    context: CommandContext,
    *,
    chain: str,
    space: str,
    timeout_seconds: float | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Starts one task chain and waits for the run to finish.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        chain (str): Technical name of the task chain.
        space (str): Technical name of the Datasphere space.
        timeout_seconds (float | None, optional): Maximum polling duration.
                                                  Defaults to None.

    Raises:
        CommandTimeoutError: If the run is still going when the timeout
                             expires. It continues remotely.
        CommandCancelledError: If polling is cancelled after the run started.
                               It continues remotely.

    Returns:
        tuple[bool, dict[str, Any]]: Whether the run completed, and its log
                                     details. Both are empty if the run never
                                     started.
    """
    log_id = await context.client.task_chains.start(chain, space)
    if log_id is None:
        return False, {}

    try:
        return await _await_task_log(
            context.client.task_chains.get_log,
            log_id=log_id,
            space=space,
            timeout_seconds=timeout_seconds,
        )
    except TimeoutError:
        raise CommandTimeoutError(
            f"Task chain '{chain}' in '{space}' timed out. "
            "The remote operation may continue.",
            log_id=str(log_id),
        ) from None
    except asyncio.CancelledError:
        raise CommandCancelledError(
            f"Task chain '{chain}' in '{space}' was cancelled. "
            "The remote operation may continue.",
            log_id=str(log_id),
        ) from None
