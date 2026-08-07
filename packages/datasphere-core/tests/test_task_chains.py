import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
from datasphere_core import CommandCancelledError, CommandContext
from datasphere_core.commands.shared import task_logs
from datasphere_core.commands.task_chains import (
    run_task_chain,
    run_task_chain_batch,
)
from datasphere_core.models.common import (
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
)
from datasphere_core.models.task_chains import (
    RunTaskChainBatchRequest,
    RunTaskChainRequest,
    RunTaskChainResult,
    TaskChainStatus,
)

START_PATH = "/dwaas-core/tf/SPACE_A/taskchains/CHAIN_A/start"
LOGS_PATH = "/dwaas-core/tf/SPACE_A/logs"


def _log(status: str, **extra: Any) -> httpx.Response:
    """
    Builds the answer of the task log endpoint for one run.
    """
    return httpx.Response(200, json=[{"status": status, **extra}])


@respx.mock
async def test_run_task_chain_maps_a_completed_run(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a completed run is mapped to its result fields.
    """
    start = respx.post(path=START_PATH).mock(
        return_value=httpx.Response(202, json={"logId": 123})
    )
    respx.get(path=LOGS_PATH).mock(
        return_value=_log("COMPLETED", runTime=65432)
    )

    result = await run_task_chain(
        context(),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    # The millisecond runtime is rounded to whole seconds
    assert result == RunTaskChainResult(
        chain="CHAIN_A",
        space="SPACE_A",
        status=TaskChainStatus.COMPLETED,
        log_status="COMPLETED",
        log_id="123",
        runtime_seconds=65,
    )

    # Every request carries its own identifier for the tenant logs
    assert start.calls.last.request.headers["x-request-id"]


@respx.mock
async def test_run_task_chain_announces_its_start(
    context: Callable[..., CommandContext],
    caplog,
) -> None:
    """
    Checks that a run announces itself before it waits for the tenant.
    """
    respx.post(path=START_PATH).mock(
        return_value=httpx.Response(202, json={"logId": 123})
    )
    respx.get(path=LOGS_PATH).mock(return_value=_log("COMPLETED"))

    with caplog.at_level(logging.DEBUG, logger="datasphere_core"):
        await run_task_chain(
            context(),
            RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
        )

    # A batch runs this command per item, so every chain reports its start
    assert caplog.records[0].getMessage() == (
        "Starting task chain 'CHAIN_A' in space 'SPACE_A'..."
    )
    assert caplog.records[0].levelname == "INFO"


@respx.mock
async def test_a_running_chain_reports_its_runtime(
    context: Callable[..., CommandContext],
    monkeypatch,
    caplog,
) -> None:
    """
    Checks that a chain that keeps running says so while it is waited for.
    """
    respx.post(path=START_PATH).mock(
        return_value=httpx.Response(202, json={"logId": 123})
    )

    # One running poll before the run completes, and an interval of zero, so
    # the message appears without waiting for it
    respx.get(path=LOGS_PATH).mock(
        side_effect=[_log("RUNNING"), _log("COMPLETED", runTime=1000)]
    )
    monkeypatch.setattr(task_logs, "ANNOUNCE_INTERVAL_SECONDS", 0)

    with caplog.at_level(logging.DEBUG, logger="datasphere_core"):
        await run_task_chain(
            context(),
            RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
        )

    messages = [record.getMessage() for record in caplog.records]
    assert (
        "Waiting for task chain 'CHAIN_A' to finish. "
        "Current runtime 00:00:00." in messages
    )


@respx.mock
async def test_run_task_chain_maps_a_chain_that_never_started(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a refused start becomes a start failure.
    """
    respx.post(path=START_PATH).mock(return_value=httpx.Response(400))
    logs = respx.get(path=LOGS_PATH)

    result = await run_task_chain(
        context(),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    # Without a log ID there is nothing to poll
    assert result.status is TaskChainStatus.START_FAILED
    assert result.runtime_seconds is None
    assert not logs.called


@respx.mock
async def test_run_task_chain_maps_a_timeout_to_its_status(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a timeout becomes a status instead of an exception.
    """
    respx.post(path=START_PATH).mock(
        return_value=httpx.Response(202, json={"logId": 42})
    )
    respx.get(path=LOGS_PATH).mock(return_value=_log("RUNNING", runTime=1000))

    result = await run_task_chain(
        context(),
        RunTaskChainRequest(
            chain="CHAIN_A",
            space="SPACE_A",
            timeout_seconds=0.01,
        ),
    )

    assert result.status is TaskChainStatus.TIMED_OUT
    assert result.log_id == "42"


@respx.mock
async def test_run_task_chain_reraises_a_cancellation_with_its_log_id(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a cancellation is re-raised with the log ID of the run.
    """
    respx.post(path=START_PATH).mock(
        return_value=httpx.Response(202, json={"logId": 99})
    )

    # respx refuses a BaseException as side effect, so it is raised inside
    def cancel(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    respx.get(path=LOGS_PATH).mock(side_effect=cancel)

    with pytest.raises(CommandCancelledError) as error:
        await run_task_chain(
            context(),
            RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
        )

    # The log ID lets the caller follow the run that is still going remotely
    assert error.value.log_id == "99"


@respx.mock
async def test_run_task_chain_batch_keeps_order_and_reports_progress(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a batch keeps the input order and reports its progress.
    """
    progress: list[CommandProgress] = []

    # Chain B fails, every other chain completes
    for chain in ("A", "B", "C"):
        respx.post(
            path=f"/dwaas-core/tf/SPACE_A/taskchains/{chain}/start"
        ).mock(
            return_value=httpx.Response(
                202, json={"logId": 2 if chain == "B" else 1}
            )
        )

    def log_for(request: httpx.Request) -> httpx.Response:
        if request.url.params["taskLogId"] == "2":
            return _log("FAILED")
        return _log("COMPLETED", runTime=1000)

    respx.get(path=LOGS_PATH).mock(side_effect=log_for)

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    result = await run_task_chain_batch(
        context(progress_callback=report),
        RunTaskChainBatchRequest(
            requests=tuple(
                RunTaskChainRequest(chain=chain, space="SPACE_A")
                for chain in ("A", "B", "C")
            ),
            max_concurrency=2,
        ),
    )

    assert [item.chain for item in result.results] == ["A", "B", "C"]
    assert [item.status for item in result.results] == [
        TaskChainStatus.COMPLETED,
        TaskChainStatus.FAILED,
        TaskChainStatus.COMPLETED,
    ]
    assert result.summary == BatchSummary(
        total=3,
        succeeded=2,
        failed=1,
        skipped=0,
        timed_out=0,
    )

    # One failed chain makes the whole batch end in the failed phase
    assert [update.phase for update in progress] == [
        CommandProgressPhase.STARTED,
        CommandProgressPhase.STARTED,
        CommandProgressPhase.ADVANCED,
        CommandProgressPhase.ADVANCED,
        CommandProgressPhase.ADVANCED,
        CommandProgressPhase.FAILED,
    ]


def test_request_rejects_an_unusable_timeout() -> None:
    """
    Checks that a timeout outside the supported range is rejected.
    """
    with pytest.raises(ValueError, match="Timeout"):
        RunTaskChainRequest(chain="A", space="S", timeout_seconds=0)
