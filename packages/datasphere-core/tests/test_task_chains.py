import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from datasphere_api import DatasphereClient
from datasphere_core import CommandCancelledError, CommandContext
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


def _client(**task_chain_calls: Any) -> DatasphereClient:
    """
    Builds a client whose task chain resource starts one run and reports it
    as completed. Every call can be replaced through a keyword argument.
    """
    async def start(chain: str, space: str) -> int | None:
        return 123

    async def get_log(log_id: int, space: str) -> dict[str, Any]:
        return {"status": "COMPLETED", "runTime": 65432}

    return cast(
        DatasphereClient,
        SimpleNamespace(
            task_chains=SimpleNamespace(
                **{"start": start, "get_log": get_log, **task_chain_calls}
            )
        ),
    )


async def test_run_task_chain_maps_a_completed_run() -> None:
    """
    Checks that a completed run is mapped to its result fields.
    """
    async def start(chain: str, space: str) -> int | None:
        assert (chain, space) == ("CHAIN_A", "SPACE_A")
        return 123

    result = await run_task_chain(
        CommandContext(client=_client(start=start)),
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


async def test_run_task_chain_maps_a_chain_that_never_started() -> None:
    """
    Checks that a run without log details becomes a start failure.
    """
    async def start(chain: str, space: str) -> int | None:
        return None

    result = await run_task_chain(
        CommandContext(client=_client(start=start)),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    # Without any log details the run never reached Datasphere
    assert result.status is TaskChainStatus.START_FAILED
    assert result.runtime_seconds is None


async def test_run_task_chain_maps_a_timeout_to_its_status() -> None:
    """
    Checks that a timeout becomes a status instead of an exception.
    """
    async def start(chain: str, space: str) -> int | None:
        return 42

    # The run never leaves the running state, so the timeout decides
    async def get_log(log_id: int, space: str) -> dict[str, Any]:
        return {"status": "RUNNING", "runTime": 1000}

    result = await run_task_chain(
        CommandContext(client=_client(start=start, get_log=get_log)),
        RunTaskChainRequest(
            chain="CHAIN_A",
            space="SPACE_A",
            timeout_seconds=0.01,
        ),
    )

    assert result.status is TaskChainStatus.TIMED_OUT
    assert result.log_id == "42"


async def test_run_task_chain_reraises_a_cancellation_with_its_log_id() -> (
    None
):
    """
    Checks that a cancellation is re-raised with the log ID of the run.
    """
    async def start(chain: str, space: str) -> int | None:
        return 99

    async def get_log(log_id: int, space: str) -> dict[str, Any]:
        raise asyncio.CancelledError

    with pytest.raises(CommandCancelledError) as error:
        await run_task_chain(
            CommandContext(client=_client(start=start, get_log=get_log)),
            RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
        )

    # The log ID lets the caller follow the run that is still going remotely
    assert error.value.log_id == "99"


async def test_run_task_chain_batch_keeps_order_and_reports_progress() -> None:
    """
    Checks that a batch keeps the input order and reports its progress.
    """
    progress: list[CommandProgress] = []

    # Chain B fails, every other chain completes
    async def start(chain: str, space: str) -> int | None:
        return 2 if chain == "B" else 1

    async def get_log(log_id: int, space: str) -> dict[str, Any]:
        if log_id == 2:
            return {"status": "FAILED"}
        return {"status": "COMPLETED", "runTime": 1000}

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    result = await run_task_chain_batch(
        CommandContext(
            client=_client(start=start, get_log=get_log),
            progress_callback=report,
        ),
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
