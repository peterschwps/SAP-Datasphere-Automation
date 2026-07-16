from types import SimpleNamespace
from typing import Any, Protocol, cast

import pytest
from datasphere_api import (
    DatasphereClient,
    TaskChainCancelled,
    TaskChainTimeout,
)
from datasphere_core import (
    CommandCancelledError,
    CommandContext,
    CommandProgress,
    CommandTimeoutError,
    StartTaskChainRequest,
    StartTaskChainResult,
    start_task_chain,
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


async def test_start_task_chain_maps_completed_result() -> None:
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        assert (chain, space) == ("CHAIN_A", "SPACE_A")
        assert timeout_seconds == 3600.0
        return True, {"status": "COMPLETED", "runTime": 65432}

    result = await start_task_chain(
        CommandContext(client=_client(run)),
        StartTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    assert result == StartTaskChainResult(
        chain="CHAIN_A",
        space="SPACE_A",
        status="completed",
        sap_status="COMPLETED",
        runtime_seconds=65,
    )


@pytest.mark.parametrize(
    ("details", "status", "sap_status"),
    [
        ({}, "start_failed", None),
        ({"status": "FAILED"}, "failed", "FAILED"),
    ],
)
async def test_start_task_chain_maps_failures(
    details: dict[str, Any],
    status: str,
    sap_status: str | None,
) -> None:
    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        return False, details

    result = await start_task_chain(
        CommandContext(client=_client(run)),
        StartTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    assert result.status == status
    assert result.sap_status == sap_status
    assert result.runtime_seconds is None


async def test_start_task_chain_reports_progress() -> None:
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

    await start_task_chain(
        CommandContext(client=_client(run), progress=report),
        StartTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )

    assert progress == [
        CommandProgress(command="taskchain.start", phase="started"),
        CommandProgress(command="taskchain.start", phase="completed"),
    ]


async def test_start_task_chain_times_out() -> None:
    progress: list[CommandProgress] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        raise TaskChainTimeout(chain, space, log_id=42)

    with pytest.raises(CommandTimeoutError) as error:
        await start_task_chain(
            CommandContext(client=_client(run), progress=report),
            StartTaskChainRequest(
                chain="CHAIN_A",
                space="SPACE_A",
                timeout_seconds=0.001,
            ),
        )

    assert error.value.operation_id == "42"
    assert progress == [
        CommandProgress(command="taskchain.start", phase="started"),
        CommandProgress(command="taskchain.start", phase="timed_out"),
    ]


async def test_start_task_chain_propagates_unexpected_error() -> None:
    progress: list[CommandProgress] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        raise RuntimeError("SAP request failed")

    with pytest.raises(RuntimeError, match="SAP request failed"):
        await start_task_chain(
            CommandContext(client=_client(run), progress=report),
            StartTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
        )

    assert progress == [
        CommandProgress(command="taskchain.start", phase="started"),
        CommandProgress(command="taskchain.start", phase="failed"),
    ]


async def test_start_task_chain_cancellation_retains_log_id() -> None:
    progress: list[CommandProgress] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def run(
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        raise TaskChainCancelled(chain, space, log_id=43)

    with pytest.raises(CommandCancelledError) as error:
        await start_task_chain(
            CommandContext(client=_client(run), progress=report),
            StartTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
        )

    assert error.value.operation_id == "43"
    assert progress[0] == CommandProgress(
        command="taskchain.start",
        phase="started",
    )
    assert progress[1].phase == "cancelled"
    assert "log ID: 43" in (progress[1].message or "")


@pytest.mark.parametrize(
    ("chain", "space", "timeout"),
    [
        ("", "SPACE_A", 1.0),
        ("CHAIN_A", " ", 1.0),
        ("CHAIN_A", "SPACE_A", 0.0),
        ("CHAIN_A", "SPACE_A", 86401.0),
        ("CHAIN_A", "SPACE_A", float("nan")),
    ],
)
def test_start_task_chain_request_validates_input(
    chain: str,
    space: str,
    timeout: float,
) -> None:
    with pytest.raises(ValueError):
        StartTaskChainRequest(
            chain=chain,
            space=space,
            timeout_seconds=timeout,
        )
