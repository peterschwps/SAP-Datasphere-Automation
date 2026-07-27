import asyncio
from dataclasses import dataclass
from typing import Any, cast

import pytest
from datasphere_core import (
    CommandContext,
    execute_batch,
    execute_command,
    execute_with_concurrency_limit,
)
from datasphere_core.execution import BatchExecution, BatchProgressState
from datasphere_core.models.common import (
    MAXIMUM_BATCH_CONCURRENCY,
    BatchItemFinalStatus,
    BatchItemResult,
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
)


@dataclass(frozen=True, slots=True)
class _BatchResult:
    results: tuple[int, ...]
    summary: BatchSummary


async def test_map_bounded_uses_at_most_maximum_worker_tasks() -> None:
    task_ids: set[int] = set()

    async def operation(value: int) -> int:
        task = asyncio.current_task()
        assert task is not None
        task_ids.add(id(task))
        await asyncio.sleep(0)
        return value * 2

    result = await execute_with_concurrency_limit(
        tuple(range(20)),
        operation,
        max_concurrency=3,
    )

    assert result == tuple(value * 2 for value in range(20))
    assert len(task_ids) == 3


@pytest.mark.parametrize(
    "max_concurrency",
    [0, -1, True, 1.5, MAXIMUM_BATCH_CONCURRENCY + 1],
)
async def test_map_bounded_validates_maximum_concurrency(
    max_concurrency: Any,
) -> None:
    with pytest.raises(ValueError):
        await execute_with_concurrency_limit(
            (), _identity, max_concurrency=max_concurrency
        )


def test_batch_progress_state_aggregates_mutable_counts() -> None:
    state = BatchProgressState(total_items=None)

    state.total_items = 4
    state.record(BatchItemFinalStatus.SUCCEEDED)
    state.record(BatchItemFinalStatus.FAILED)
    state.record(BatchItemFinalStatus.SKIPPED)
    state.record(BatchItemFinalStatus.TIMED_OUT)

    assert state.completed_items == 4
    assert state.total_items == 4
    assert state.to_summary() == BatchSummary(4, 1, 1, 1, 1)


async def _identity(value: int) -> int:
    return value


async def test_execute_command_passes_context_and_reports_lifecycle() -> None:
    progress: list[CommandProgress] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    context = CommandContext(
        client=cast(Any, object()),
        progress_callback=report,
    )

    async def operation(
        operation_context: CommandContext,
        request: int,
    ) -> int:
        assert operation_context is context
        return request * 2

    result = await execute_command(
        context,
        "test.execute",
        3,
        operation,
    )

    assert result == 6
    assert progress == [
        CommandProgress(
            command="test.execute",
            phase=CommandProgressPhase.STARTED,
        ),
        CommandProgress(
            command="test.execute",
            phase=CommandProgressPhase.COMPLETED,
        ),
    ]


async def test_execute_batch_runs_items_and_reports_results() -> None:
    progress: list[CommandProgress] = []
    item_results: list[BatchItemResult] = []
    events: list[tuple[str, int | None]] = []
    release_first_item = asyncio.Event()

    async def report(update: CommandProgress) -> None:
        progress.append(update)
        events.append((update.phase.value, update.item_index))

    async def report_item_result(update: BatchItemResult) -> None:
        item_results.append(update)
        events.append(("result", update.item_index))

    context = CommandContext(
        client=cast(Any, object()),
        progress_callback=report,
        batch_item_result_callback=report_item_result,
    )

    async def run_item(
        operation_context: CommandContext,
        item: int,
    ) -> int:
        assert operation_context is context
        if item == 0:
            await release_first_item.wait()
        elif item == 1:
            release_first_item.set()
        return item * 2

    async def operation(
        execution: BatchExecution,
        request: tuple[int, ...],
    ) -> _BatchResult:
        results = await execution.execute_items(
            request,
            run_item,
            max_concurrency=2,
            classify=lambda _: BatchItemFinalStatus.SUCCEEDED,
        )
        return _BatchResult(results, execution.to_summary())

    result = await execute_batch(
        context,
        "test.execute_batch",
        (0, 1, 2),
        operation,
        result_phase=lambda batch_result: (
            CommandProgressPhase.COMPLETED
            if not batch_result.summary.failed
            else CommandProgressPhase.FAILED
        ),
    )

    assert result == _BatchResult((0, 2, 4), BatchSummary(3, 3, 0, 0, 0))
    assert progress[0] == CommandProgress(
        command="test.execute_batch",
        phase=CommandProgressPhase.STARTED,
        completed_items=0,
        total_items=None,
        succeeded_items=0,
        failed_items=0,
        skipped_items=0,
        timed_out_items=0,
    )
    assert [update.item_index for update in progress[1:-1]] == [1, 2, 0]
    assert progress[-1] == CommandProgress(
        command="test.execute_batch",
        phase=CommandProgressPhase.COMPLETED,
        completed_items=3,
        total_items=3,
        succeeded_items=3,
        failed_items=0,
        skipped_items=0,
        timed_out_items=0,
    )
    assert item_results == [
        BatchItemResult("test.execute_batch", 1, 3, 2),
        BatchItemResult("test.execute_batch", 2, 3, 4),
        BatchItemResult("test.execute_batch", 0, 3, 0),
    ]
    assert events == [
        ("started", None),
        ("advanced", 1),
        ("result", 1),
        ("advanced", 2),
        ("result", 2),
        ("advanced", 0),
        ("result", 0),
        ("completed", None),
    ]
