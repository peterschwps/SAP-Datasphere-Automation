import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest
from datasphere_api import DatasphereClient
from datasphere_core import CommandContext
from datasphere_core.errors import CommandTimeoutError
from datasphere_core.execution import (
    BatchReporter,
    batch_command,
    command,
    execute_with_concurrency_limit,
    run_batch,
)
from datasphere_core.models.common import (
    MAXIMUM_BATCH_CONCURRENCY,
    BatchItemResult,
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
    CommandStatus,
    Outcome,
)


class ExampleStatus(CommandStatus):
    """
    Status used to exercise the execution core without a real command.
    """
    DONE = "done", Outcome.SUCCEEDED
    SKIPPED = "skipped", Outcome.SKIPPED
    BROKEN = "broken", Outcome.FAILED
    EXPIRED = "expired", Outcome.TIMED_OUT


@dataclass(frozen=True, slots=True)
class ExampleResult:
    name: str
    status: ExampleStatus


@dataclass(frozen=True, slots=True)
class ExampleBatchResult:
    results: tuple[ExampleResult, ...]
    summary: BatchSummary


def _context() -> tuple[
    CommandContext,
    list[CommandProgress],
    list[BatchItemResult],
]:
    """
    Builds a context that records every progress and batch item report.
    """
    progress: list[CommandProgress] = []
    items: list[BatchItemResult] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def report_item(update: BatchItemResult) -> None:
        items.append(update)

    context = CommandContext(
        client=cast(DatasphereClient, SimpleNamespace()),
        progress_callback=report,
        batch_item_result_callback=report_item,
    )
    return context, progress, items


async def _work(context: CommandContext, name: str) -> ExampleResult:
    """
    Maps an item name to the status it should produce.
    """
    _ = context
    statuses = {
        "ok": ExampleStatus.DONE,
        "skip": ExampleStatus.SKIPPED,
        "bad": ExampleStatus.BROKEN,
        "slow": ExampleStatus.EXPIRED,
    }
    return ExampleResult(name=name, status=statuses[name])


def test_status_members_carry_their_outcome() -> None:
    """
    Checks that every status member exposes the outcome it belongs to.
    """
    # The outcome replaces the per-command classification functions
    assert ExampleStatus.DONE.outcome is Outcome.SUCCEEDED
    assert ExampleStatus.SKIPPED.outcome is Outcome.SKIPPED
    assert ExampleStatus("broken") is ExampleStatus.BROKEN
    assert ExampleStatus.EXPIRED == "expired"


async def test_command_reports_started_and_completed() -> None:
    """
    Checks that a single command reports its start and its completion.
    """
    context, progress, _ = _context()
    run = command("example.run")(_work)

    result = await run(context, "ok")

    assert result.status is ExampleStatus.DONE
    assert [update.phase for update in progress] == [
        CommandProgressPhase.STARTED,
        CommandProgressPhase.COMPLETED,
    ]


@pytest.mark.parametrize(
    ("item", "phase"),
    [
        ("skip", CommandProgressPhase.COMPLETED),
        ("bad", CommandProgressPhase.FAILED),
        ("slow", CommandProgressPhase.TIMED_OUT),
    ],
)
async def test_command_derives_terminal_phase_from_status(
    item: str,
    phase: CommandProgressPhase,
) -> None:
    """
    Checks that a command derives its terminal phase from the outcome.

    Args:
        item (str): Item name selecting the status to produce.
        phase (CommandProgressPhase): Phase the status has to end in.
    """
    context, progress, _ = _context()
    run = command("example.run")(_work)

    await run(context, item)

    # A skipped item is not a failure and therefore completes
    assert progress[-1].phase is phase


async def test_command_reports_timeout_and_reraises() -> None:
    """
    Checks that a command timeout is reported and then re-raised.
    """
    context, progress, _ = _context()

    async def fail(context: CommandContext, item: str) -> ExampleResult:
        _ = context, item
        raise CommandTimeoutError("took too long")

    run = command("example.run")(fail)

    with pytest.raises(CommandTimeoutError):
        await run(context, "ok")

    assert progress[-1].phase is CommandProgressPhase.TIMED_OUT
    assert progress[-1].message == "took too long"


async def test_command_reports_cancellation_and_reraises() -> None:
    """
    Checks that a cancellation is reported and then re-raised.
    """
    context, progress, _ = _context()

    async def cancel(context: CommandContext, item: str) -> ExampleResult:
        _ = context, item
        raise asyncio.CancelledError("stopped")

    run = command("example.run")(cancel)

    with pytest.raises(asyncio.CancelledError):
        await run(context, "ok")

    assert progress[-1].phase is CommandProgressPhase.CANCELLED


async def test_run_batch_keeps_order_and_counts_outcomes() -> None:
    """
    Checks that a batch keeps the input order and counts every outcome.
    """
    context, progress, items = _context()

    results, summary = await run_batch(
        context,
        "example.run_batch",
        ("ok", "bad", "skip", "slow", "ok"),
        _work,
        max_concurrency=2,
    )

    # Results keep the input order even though they finish concurrently
    assert [result.name for result in results] == [
        "ok",
        "bad",
        "skip",
        "slow",
        "ok",
    ]
    assert summary == BatchSummary(
        total=5,
        succeeded=2,
        failed=1,
        skipped=1,
        timed_out=1,
    )

    # Every completed item is reported once, with its index
    assert [update.phase for update in progress] == [
        CommandProgressPhase.ADVANCED
    ] * 5
    assert sorted(update.item_index for update in items) == [0, 1, 2, 3, 4]
    assert all(update.total_items == 5 for update in items)


async def test_run_batch_mutes_the_lifecycle_of_its_items() -> None:
    """
    Checks that batch items do not report their own command lifecycle.
    """
    context, progress, _ = _context()
    item_command = command("example.run")(_work)

    await run_batch(
        context,
        "example.run_batch",
        ("ok", "bad"),
        item_command,
        max_concurrency=2,
    )

    # A registered command may be used as the item operation. It must not
    # report its own 'started' and terminal phases per item.
    assert [update.phase for update in progress] == [
        CommandProgressPhase.ADVANCED
    ] * 2
    assert {update.command for update in progress} == {"example.run_batch"}


async def test_run_batch_bounds_concurrency() -> None:
    """
    Checks that a batch never exceeds its concurrency limit.
    """
    context, _, _ = _context()
    active = 0
    peak = 0

    async def work(context: CommandContext, item: str) -> ExampleResult:
        nonlocal active, peak
        _ = context
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return ExampleResult(name=item, status=ExampleStatus.DONE)

    await run_batch(
        context,
        "example.run_batch",
        tuple(str(index) for index in range(20)),
        work,
        max_concurrency=3,
    )

    assert peak == 3


async def test_batch_command_derives_phase_from_summary() -> None:
    """
    Checks that the terminal phase of a batch follows its summary.
    """
    context, progress, _ = _context()

    async def batch(
        context: CommandContext,
        items: tuple[str, ...],
    ) -> ExampleBatchResult:
        results, summary = await run_batch(
            context,
            "example.run_batch",
            items,
            _work,
            max_concurrency=2,
        )
        return ExampleBatchResult(results=results, summary=summary)

    run = batch_command("example.run_batch")(batch)

    await run(context, ("ok", "skip"))
    assert progress[-1].phase is CommandProgressPhase.COMPLETED

    progress.clear()
    await run(context, ("ok", "bad"))
    assert progress[-1].phase is CommandProgressPhase.FAILED

    # A timeout outranks a failure in the terminal phase
    progress.clear()
    await run(context, ("bad", "slow"))
    assert progress[-1].phase is CommandProgressPhase.TIMED_OUT


async def test_batch_reporter_reports_every_item_it_is_given() -> None:
    """
    Checks that the reporter delivers items right away, even out of order.
    """
    context, progress, items = _context()
    reporter = BatchReporter(context, "example.run_batch", 2)

    broken = ExampleResult(name="b", status=ExampleStatus.BROKEN)
    await reporter.complete(1, broken)

    # The item is reported right away, not once the batch is complete
    assert [update.item_index for update in items] == [1]
    assert progress[-1].total_items == 2
    assert progress[-1].completed_items == 1

    done = ExampleResult(name="a", status=ExampleStatus.DONE)
    await reporter.complete(0, done)

    # Items may arrive out of order, the summary counts them all the same
    assert [update.item_index for update in items] == [1, 0]
    assert reporter.summary == BatchSummary(
        total=2,
        succeeded=1,
        failed=1,
        skipped=0,
        timed_out=0,
    )
    assert [update.phase for update in progress] == [
        CommandProgressPhase.ADVANCED
    ] * 2


async def test_execute_with_concurrency_limit_keeps_order() -> None:
    """
    Checks that bounded execution returns its results in input order.
    """
    async def double(value: int) -> int:
        await asyncio.sleep(0.01 if value % 2 else 0)
        return value * 2

    results = await execute_with_concurrency_limit(
        items=(1, 2, 3, 4),
        operation=double,
        max_concurrency=2,
    )

    assert results == (2, 4, 6, 8)


async def test_failing_item_cancels_the_remaining_items() -> None:
    """
    Checks that a failing item cancels the items still running.
    """
    context, _, _ = _context()
    started = 0
    finished = 0

    async def work(context: CommandContext, item: str) -> ExampleResult:
        nonlocal started, finished
        _ = context
        started += 1
        if item == "boom":
            raise RuntimeError("boom")
        await asyncio.sleep(0.05)
        finished += 1
        return ExampleResult(name=item, status=ExampleStatus.DONE)

    with pytest.raises(RuntimeError, match="boom"):
        await run_batch(
            context,
            "example.run_batch",
            ("slow_one", "boom", "slow_two"),
            work,
            max_concurrency=3,
        )

    # The pending items must not keep running after the batch failed
    assert started == 3
    assert finished == 0


@pytest.mark.parametrize(
    "max_concurrency",
    [0, -1, MAXIMUM_BATCH_CONCURRENCY + 1],
)
async def test_run_batch_rejects_unsupported_concurrency(
    max_concurrency: int,
) -> None:
    """
    Checks that a batch rejects a concurrency limit outside the range.

    Args:
        max_concurrency (int): Unsupported concurrency limit to reject.
    """
    context, _, _ = _context()

    with pytest.raises(ValueError, match="Maximum concurrency"):
        await run_batch(
            context,
            "example.run_batch",
            ("ok",),
            _work,
            max_concurrency=max_concurrency,
        )
