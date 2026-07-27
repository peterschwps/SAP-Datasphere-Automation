import asyncio
from types import SimpleNamespace
from typing import Any, Protocol, cast

import pytest
from datasphere_api import (
    DatasphereClient,
    TaskChainCancelled,
    TaskChainTimeout,
)
from datasphere_core import CommandCancelledError, CommandContext
from datasphere_core.commands.task_chains import (
    run_task_chain,
    run_task_chain_batch,
)
from datasphere_core.models.common import (
    MAXIMUM_BATCH_CONCURRENCY,
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
)
from datasphere_core.models.task_chains import (
    RunTaskChainBatchRequest,
    RunTaskChainBatchResult,
    RunTaskChainRequest,
    RunTaskChainResult,
    TaskChainStatus,
)


class RunTaskChain(Protocol):
    async def __call__(
        self,
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]: ...


def _client(run: RunTaskChain) -> DatasphereClient:
    return cast(
        DatasphereClient,
        SimpleNamespace(task_chains=SimpleNamespace(run=run)),
    )


async def test_run_task_chain_maps_completed_result() -> None:
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        assert (chain, space) == ("CHAIN_A", "SPACE_A")
        assert timeout_seconds == 3600.0
        return True, {
            "status": "COMPLETED",
            "runTime": 65432,
            "logId": 123,
        }

    result = await run_task_chain(
        CommandContext(client=_client(run)),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    assert result == RunTaskChainResult(
        chain="CHAIN_A",
        space="SPACE_A",
        status=TaskChainStatus.COMPLETED,
        sap_status="COMPLETED",
        log_id="123",
        runtime_seconds=65,
    )


@pytest.mark.parametrize(
    ("details", "expected_status", "sap_status", "log_id"),
    [
        ({}, "start_failed", None, None),
        ({"status": "FAILED", "logId": "42"}, "failed", "FAILED", "42"),
    ],
)
async def test_run_task_chain_maps_expected_failures(
    details: dict[str, Any],
    expected_status: str,
    sap_status: str | None,
    log_id: str | None,
) -> None:
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        return False, details

    result = await run_task_chain(
        CommandContext(client=_client(run)),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    assert result.status == expected_status
    assert result.sap_status == sap_status
    assert result.log_id == log_id
    assert result.runtime_seconds is None


async def test_run_task_chain_reports_canonical_lifecycle() -> None:
    progress: list[CommandProgress] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        return True, {"status": "COMPLETED", "runTime": 1000}

    await run_task_chain(
        CommandContext(client=_client(run), progress_callback=report),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    assert progress == [
        CommandProgress(
            command="task_chains.run",
            phase=CommandProgressPhase.STARTED,
        ),
        CommandProgress(
            command="task_chains.run",
            phase=CommandProgressPhase.COMPLETED,
        ),
    ]


async def test_run_task_chain_timeout_retains_log_id() -> None:
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        raise TaskChainTimeout(chain, space, log_id=42)

    result = await run_task_chain(
        CommandContext(client=_client(run)),
        RunTaskChainRequest(
            chain="CHAIN_A",
            space="SPACE_A",
            timeout_seconds=0.001,
        ),
    )

    assert result == RunTaskChainResult(
        chain="CHAIN_A",
        space="SPACE_A",
        status=TaskChainStatus.TIMED_OUT,
        log_id="42",
    )


async def test_run_task_chain_cancellation_retains_log_id() -> None:
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        raise TaskChainCancelled(chain, space, log_id=43)

    with pytest.raises(CommandCancelledError) as error:
        await run_task_chain(
            CommandContext(client=_client(run)),
            RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
        )

    assert error.value.log_id == "43"


async def test_run_task_chain_batch_is_bounded_ordered_and_typed() -> None:
    active = 0
    maximum_active = 0
    progress: list[CommandProgress] = []
    release_first_item = asyncio.Event()

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            if chain == "A":
                await release_first_item.wait()
            if chain == "C":
                raise TaskChainTimeout(chain, space, log_id=103)
            if chain == "B":
                return False, {"status": "FAILED", "logId": 102}
            if chain == "D":
                release_first_item.set()
                return False, {}
            return True, {
                "status": "COMPLETED",
                "runTime": 1000,
                "logId": 101,
            }
        finally:
            active -= 1

    requests = tuple(
        RunTaskChainRequest(chain=chain, space="SPACE_A")
        for chain in ("A", "B", "C", "D")
    )
    result = await run_task_chain_batch(
        CommandContext(client=_client(run), progress_callback=report),
        RunTaskChainBatchRequest(requests=requests, max_concurrency=2),
    )

    assert result == RunTaskChainBatchResult(
        results=(
            RunTaskChainResult(
                chain="A",
                space="SPACE_A",
                status=TaskChainStatus.COMPLETED,
                sap_status="COMPLETED",
                log_id="101",
                runtime_seconds=1,
            ),
            RunTaskChainResult(
                chain="B",
                space="SPACE_A",
                status=TaskChainStatus.FAILED,
                sap_status="FAILED",
                log_id="102",
            ),
            RunTaskChainResult(
                chain="C",
                space="SPACE_A",
                status=TaskChainStatus.TIMED_OUT,
                log_id="103",
            ),
            RunTaskChainResult(
                chain="D",
                space="SPACE_A",
                status=TaskChainStatus.START_FAILED,
            ),
        ),
        summary=BatchSummary(
            total=4,
            succeeded=1,
            failed=2,
            skipped=0,
            timed_out=1,
        ),
    )
    assert maximum_active == 2
    assert [update.phase for update in progress] == [
        "started",
        "advanced",
        "advanced",
        "advanced",
        "advanced",
        "timed_out",
    ]
    assert progress == [
        CommandProgress(
            command="task_chains.run_batch",
            phase=CommandProgressPhase.STARTED,
            completed_items=0,
            total_items=4,
            succeeded_items=0,
            failed_items=0,
            skipped_items=0,
            timed_out_items=0,
        ),
        CommandProgress(
            command="task_chains.run_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=1,
            total_items=4,
            succeeded_items=0,
            failed_items=1,
            skipped_items=0,
            timed_out_items=0,
            item_index=1,
        ),
        CommandProgress(
            command="task_chains.run_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=2,
            total_items=4,
            succeeded_items=0,
            failed_items=1,
            skipped_items=0,
            timed_out_items=1,
            item_index=2,
        ),
        CommandProgress(
            command="task_chains.run_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=3,
            total_items=4,
            succeeded_items=0,
            failed_items=2,
            skipped_items=0,
            timed_out_items=1,
            item_index=3,
        ),
        CommandProgress(
            command="task_chains.run_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=4,
            total_items=4,
            succeeded_items=1,
            failed_items=2,
            skipped_items=0,
            timed_out_items=1,
            item_index=0,
        ),
        CommandProgress(
            command="task_chains.run_batch",
            phase=CommandProgressPhase.TIMED_OUT,
            completed_items=4,
            total_items=4,
            succeeded_items=1,
            failed_items=2,
            skipped_items=0,
            timed_out_items=1,
        ),
    ]


async def test_run_task_chain_batch_cancellation_is_terminal() -> None:
    operation_started = asyncio.Event()
    progress: list[CommandProgress] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        operation_started.set()
        await asyncio.Event().wait()
        raise AssertionError("Unreachable")

    task = asyncio.create_task(
        run_task_chain_batch(
            CommandContext(client=_client(run), progress_callback=report),
            RunTaskChainBatchRequest(
                requests=(RunTaskChainRequest(chain="A", space="SPACE_A"),)
            ),
        )
    )
    await operation_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert [update.phase for update in progress] == [
        "started",
        "cancelled",
    ]
    assert progress[-1] == CommandProgress(
        command="task_chains.run_batch",
        phase=CommandProgressPhase.CANCELLED,
        completed_items=0,
        total_items=1,
        succeeded_items=0,
        failed_items=0,
        skipped_items=0,
        timed_out_items=0,
    )


@pytest.mark.parametrize(
    "timeout",
    [
        0.0,
        86401.0,
        float("nan"),
        float("inf"),
    ],
)
def test_run_task_chain_request_validates_timeout(
    timeout: float,
) -> None:
    with pytest.raises(ValueError):
        RunTaskChainRequest(
            chain="CHAIN_A",
            space="SPACE_A",
            timeout_seconds=timeout,
        )


@pytest.mark.parametrize(
    "max_concurrency",
    [0, -1, True, 1.5, MAXIMUM_BATCH_CONCURRENCY + 1],
)
def test_batch_request_validates_max_concurrency(
    max_concurrency: Any,
) -> None:
    with pytest.raises(ValueError):
        RunTaskChainBatchRequest(
            requests=(),
            max_concurrency=max_concurrency,
        )
