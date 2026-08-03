import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from datasphere_core.context import CommandContext
from datasphere_core.errors import (
    CommandCancelledError,
    CommandTimeoutError,
    UnexpectedResponseError,
)
from datasphere_core.session import request_headers

logger = logging.getLogger(__name__)

# Reads the task log of one started run
type LogFetcher = Callable[
    [CommandContext, int, str], Awaitable[dict[str, Any]]
]

# Seconds between two polls of a running task log
POLL_INTERVAL_SECONDS = 1

# Seconds before the monitor is asked again after a silent answer
MONITOR_RETRY_INTERVAL_SECONDS = 1


async def _await_task_log(
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


async def _start_chain(
    context: CommandContext,
    chain: str,
    space: str,
) -> int | None:
    """
    Starts one task chain without waiting for its result.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.
        chain (str): Technical name of the task chain.
        space (str): Technical name of the Datasphere space.

    Returns:
        int | None: Task log ID of the started run, or None if the tenant
                    refused it.
    """
    response = await context.session.post(
        url=f"/dwaas-core/tf/{space}/taskchains/{chain}/start",
        json={
            "objectId": chain,
            "activity": "RUN_CHAIN",
            "applicationId": "TASK_CHAINS",
            "spaceId": space,
        },
        headers=request_headers(),
    )
    if response.status_code != 202:
        logger.error(
            "Error starting task chain '%s' in space '%s'. Skipping...",
            chain,
            space,
        )
        return None
    return response.json()["logId"]


async def _get_chain_log(
    context: CommandContext,
    log_id: int,
    space: str,
) -> dict[str, Any]:
    """
    Reads the task log of one task chain run.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.
        log_id (int): Task log ID of the run.
        space (str): Technical name of the Datasphere space.

    Returns:
        dict[str, Any]: Log details with 'status' and 'runTime'.
    """
    response = await context.session.get(
        url=f"/dwaas-core/tf/{space}/logs",
        params={"taskLogId": log_id},
        headers=request_headers(),
    )
    return response.json()[0]


async def _get_extended_log(
    context: CommandContext,
    log_id: int,
    space: str,
) -> dict[str, Any]:
    """
    Reads the extended task log of one view run.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.
        log_id (int): Task log ID of the run.
        space (str): Technical name of the Datasphere space.

    Returns:
        dict[str, Any]: Log details with 'status' and 'runTime'.
    """
    response = await context.session.get(
        url=f"/dwaas-core/tf/{space}/extendedlogs/{log_id}",
        headers=request_headers(),
    )
    return response.json()["logDetails"]


async def _get_monitor_details(
    context: CommandContext,
    view: str,
    space: str,
) -> dict[str, Any]:
    """
    Reads the monitor details of one view.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.

    Returns:
        dict[str, Any]: Monitor details, empty if the tenant refused to answer.
    """
    response = await context.session.get(
        url=f"/dwaas-core/monitor/{space}/persistedViews/{view}",
    )
    if response.status_code != 200:
        return {}
    return response.json()


async def _start_view_activity(
    context: CommandContext,
    view: str,
    space: str,
    activity: str,
) -> int | None:
    """
    Starts one activity on a view without waiting for its result. A refusal is
    reported by the caller, which is the one that knows what was refused.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.
        activity (str): Activity to run, for example 'PERSIST'.

    Returns:
        int | None: Task log ID of the started run, or None if the tenant
                    refused it.
    """
    response = await context.session.post(
        url="/dwaas-core/tf/directexecute",
        json={
            "applicationId": "VIEWS",
            "spaceId": space,
            "objectId": view,
            "activity": activity,
        },
        headers=request_headers(),
    )
    if response.status_code != 202:
        return None
    return response.json()["taskLogId"]


async def is_persisted(
    context: CommandContext,
    view: str,
    space: str,
) -> bool:
    """
    Checks whether one view currently holds persisted data. The monitor
    occasionally answers with nothing at all, so it is asked up to three times.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.

    Raises:
        UnexpectedResponseError: If the monitor stayed silent every time.

    Returns:
        bool: Whether the view holds persisted data.
    """
    for _ in range(3):
        monitor_details = await _get_monitor_details(context, view, space)
        if not monitor_details:
            await asyncio.sleep(MONITOR_RETRY_INTERVAL_SECONDS)
            continue
        return monitor_details.get("dataPersistency", "") == "Persisted"
    raise UnexpectedResponseError(
        f"Failed to check persistence of view '{view}' in '{space}'."
    )


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
    log_id = await _start_view_activity(context, view, space, "PERSIST")
    if log_id is None:
        logger.error(
            "Error starting persistence for view '%s' in '%s'. Skipping...",
            view,
            space,
        )
        return False, {}

    try:
        return await _await_task_log(
            context,
            _get_extended_log,
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
    monitor_details = await _get_monitor_details(context, view, space)
    if "dataPersistency" not in monitor_details:
        return False, {}
    if monitor_details["dataPersistency"] != "Persisted":
        return True, {}

    log_id = await _start_view_activity(
        context,
        view,
        space,
        "REMOVE_PERSISTED_DATA",
    )
    if log_id is None:
        logger.error(
            "Error removing persistence for view '%s' in '%s'. Skipping...",
            view,
            space,
        )
        return False, {}

    try:
        return await _await_task_log(
            context,
            _get_extended_log,
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
    log_id = await _start_chain(context, chain, space)
    if log_id is None:
        return False, {}

    try:
        return await _await_task_log(
            context,
            _get_chain_log,
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
