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


class RunTaskChain(Protocol):
    async def __call__(
        self,
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]: ...


def _client(run: RunTaskChain) -> DatasphereClient:
    """
    Builds a client whose task chain resource uses the supplied run function.
    """
    return cast(
        DatasphereClient,
        SimpleNamespace(task_chains=SimpleNamespace(run=run)),
    )


async def test_run_task_chain_maps_a_completed_run() -> None:
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        assert (chain, space) == ("CHAIN_A", "SPACE_A")
        assert timeout_seconds == 3600.0
        return True, {"status": "COMPLETED", "runTime": 65432, "logId": 123}

    result = await run_task_chain(
        CommandContext(client=_client(run)),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    # The millisecond runtime is rounded to whole seconds
    assert result == RunTaskChainResult(
        chain="CHAIN_A",
        space="SPACE_A",
        status=TaskChainStatus.COMPLETED,
        sap_status="COMPLETED",
        log_id="123",
        runtime_seconds=65,
    )


async def test_run_task_chain_maps_a_chain_that_never_started() -> None:
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        return False, {}

    result = await run_task_chain(
        CommandContext(client=_client(run)),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    # Without any log details the run never reached Datasphere
    assert result.status is TaskChainStatus.START_FAILED
    assert result.runtime_seconds is None


async def test_run_task_chain_maps_a_timeout_to_its_status() -> None:
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        raise TaskChainTimeout(chain, space, log_id=42)

    result = await run_task_chain(
        CommandContext(client=_client(run)),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    assert result.status is TaskChainStatus.TIMED_OUT
    assert result.log_id == "42"


async def test_run_task_chain_reraises_a_cancellation_with_its_log_id() -> (
    None
):
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        raise TaskChainCancelled(chain, space, log_id=99)

    with pytest.raises(CommandCancelledError) as error:
        await run_task_chain(
            CommandContext(client=_client(run)),
            RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
        )

    # The log ID lets the caller follow the run that is still going remotely
    assert error.value.log_id == "99"


async def test_run_task_chain_batch_keeps_order_and_reports_progress() -> None:
    progress: list[CommandProgress] = []

    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        if chain == "B":
            return False, {"status": "FAILED", "logId": 2}
        return True, {"status": "COMPLETED", "logId": 1, "runTime": 1000}

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    result = await run_task_chain_batch(
        CommandContext(client=_client(run), progress_callback=report),
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
    with pytest.raises(ValueError, match="Timeout"):
        RunTaskChainRequest(chain="A", space="S", timeout_seconds=0)
