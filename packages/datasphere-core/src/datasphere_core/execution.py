import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import replace
from functools import wraps
from typing import Any, Protocol

from datasphere_core.context import CommandContext
from datasphere_core.errors import CommandTimeoutError
from datasphere_core.models.common import (
    BatchItemResult,
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
    CommandStatus,
    Outcome,
    validate_max_concurrency,
)

# Type alias for a command handler: receives RequestT and returns ResultT
type CommandHandler[RequestT, ResultT] = Callable[
    [CommandContext, RequestT],
    Awaitable[ResultT],
]

# Lifecycle phase each outcome ends in. Skipped items are not a failure, so
# they complete like a success.
_TERMINAL_PHASES = {
    Outcome.SUCCEEDED: CommandProgressPhase.COMPLETED,
    Outcome.SKIPPED: CommandProgressPhase.COMPLETED,
    Outcome.FAILED: CommandProgressPhase.FAILED,
    Outcome.TIMED_OUT: CommandProgressPhase.TIMED_OUT,
}


class StatusResult(Protocol):
    """
    Structural type of every single item result. This includes single commands
    as well as the items within a batch.
    """

    @property
    def status(self) -> CommandStatus:
        """
        Returns the status of the command result.
        """
        ...


class BatchResult(Protocol):
    """
    Structural type for the final result of a batch command.
    """

    @property
    def summary(self) -> BatchSummary:
        """
        Returns the aggregate outcome counts of the batch.
        """
        ...


def summarize(counts: Counter[Outcome]) -> BatchSummary:
    """
    Builds the summary of a batch run from its recorded outcomes.

    Args:
        counts (Counter[Outcome]): Number of items recorded per outcome.

    Returns:
        BatchSummary: Aggregate outcome counts of the batch.
    """
    return BatchSummary(
        total=sum(counts.values()),
        succeeded=counts[Outcome.SUCCEEDED],
        failed=counts[Outcome.FAILED],
        skipped=counts[Outcome.SKIPPED],
        timed_out=counts[Outcome.TIMED_OUT],
    )


def batch_progress(
    command: str,
    phase: CommandProgressPhase,
    summary: BatchSummary,
    *,
    total_items: int | None = None,
    item_index: int | None = None,
) -> CommandProgress:
    """
    Builds a progress update that carries the current batch counters.

    Args:
        command (str): Name of the command (e.g. 'views.persist_batch').
        phase (CommandProgressPhase): Phase to report. Refers to the whole
                                      batch, except for 'advanced' which
                                      reports one completed item.
        summary (BatchSummary): Outcome counts recorded so far.
        total_items (int | None, optional): Total number of items in the batch.
                                            Falls back to the recorded items,
                                            which is exact once the batch
                                            finished. Defaults to None.
        item_index (int | None, optional): Index of the completed batch item.
                                           Defaults to None.

    Returns:
        CommandProgress: Progress update including the batch counters.
    """
    return CommandProgress(
        command=command,
        phase=phase,
        completed_items=summary.total,
        total_items=summary.total if total_items is None else total_items,
        succeeded_items=summary.succeeded,
        failed_items=summary.failed,
        skipped_items=summary.skipped,
        timed_out_items=summary.timed_out,
        item_index=item_index,
    )


async def _execute[ResultT](
    context: CommandContext,
    command: str,
    operation: Awaitable[ResultT],
    terminal: Callable[[ResultT], CommandProgress],
) -> ResultT:
    """
    Reports the lifecycle of one command execution around its operation.

    Args:
        context (CommandContext): CommandContext object to report updates to.
        command (str): Command name to use for the lifecycle updates.
        operation (Awaitable[ResultT]): Awaitable that executes the actual
                                        command.
        terminal (Callable[[ResultT], CommandProgress]): Callable building the
                                                         final progress update
                                                         from the result.

    Returns:
        ResultT: Result of the executed operation.
    """
    # Report start of the command
    await context.report(
        CommandProgress(command=command, phase=CommandProgressPhase.STARTED)
    )

    # Run the command and handle possible errors
    # IMPORTANT: CommandTimeoutError must be checked before Exception,
    #            otherwise it would be reported as a plain failure.
    try:
        result = await operation

    except CommandTimeoutError as error:
        await context.report(
            CommandProgress(
                command=command,
                phase=CommandProgressPhase.TIMED_OUT,
                message=str(error),
            )
        )
        raise

    except asyncio.CancelledError as error:
        await context.report(
            CommandProgress(
                command=command,
                phase=CommandProgressPhase.CANCELLED,
                message=str(error) or None,
            )
        )
        raise

    except Exception:
        await context.report(
            CommandProgress(
                command=command,
                phase=CommandProgressPhase.FAILED,
            )
        )
        raise

    # Report the outcome of the completed command
    await context.report(terminal(result))
    return result


def command[RequestT, ResultT: StatusResult](
    name: str,
) -> Callable[
    [CommandHandler[RequestT, ResultT]],
    CommandHandler[RequestT, ResultT],
]:
    """
    Decorator fabric that turns a command handler into a registered single
    command. The decorated function reports its own lifecycle and derives the
    final phase from the outcome of its result status.

    **Example:** The command ``REFRESH_REMOTE_TABLE_STATISTICS_COMMAND_NAME``
    refers to the string ``remote_tables.refresh_statistics``. The decorator
    ``@command(REFRESH_REMOTE_TABLE_STATISTICS_COMMAND_NAME)`` is used to wrap
    the function ``refresh_remote_table_statistics`` that executes the
    business logic, This passes the name of the command as the ``name`` of this
    function and return a new decorator ``decorate(handler)``. All of this
    happens during the import time, once per command.
    The new decorator will only be triggered when the underlying function is
    called. In that case it will wrap the function implementing the business
    logic with the ``execute`` method. Since the
    ``refresh_remote_table_statistics`` method only returns an awaitable, the
    actual operation won't be started until it is await within the ``_execute``
    method that the decorator calls.

    Args:
        name (str): Command name to use for the lifecycle updates.

    Returns:
        Callable: Decorator wrapping the handler with lifecycle reporting.
    """

    def decorate(
        handler: CommandHandler[RequestT, ResultT],
    ) -> CommandHandler[RequestT, ResultT]:
        """
        Wraps one command handler with its lifecycle reporting.

        Args:
            handler (CommandHandler[RequestT, ResultT]): Handler doing the
                                                         actual work.

        Returns:
            CommandHandler[RequestT, ResultT]: Handler reporting its own
                                               lifecycle.
        """

        @wraps(handler)
        async def execute(
            context: CommandContext,
            request: RequestT,
        ) -> ResultT:
            """
            Runs the handler and reports the lifecycle around it.

            Args:
                context (CommandContext): CommandContext object to report
                                          updates to.
                request (RequestT): Request passed to the handler.

            Returns:
                ResultT: Result of the handler.
            """
            return await _execute(
                context=context,
                command=name,
                operation=handler(context, request),
                terminal=lambda result: CommandProgress(
                    command=name,
                    phase=_TERMINAL_PHASES[result.status.outcome],
                ),
            )

        return execute

    return decorate


def batch_command[RequestT, ResultT: BatchResult](
    name: str,
) -> Callable[
    [CommandHandler[RequestT, ResultT]],
    CommandHandler[RequestT, ResultT],
]:
    """
    Decorator fabric that turns a command handler into a registered batch
    command. The decorated function reports its own lifecycle and derives the
    final phase from the summary of its batch result.

    Args:
        name (str): Command name to use for the lifecycle updates.

    Returns:
        Callable: Decorator wrapping the handler with lifecycle reporting.
    """

    def decorate(
        handler: CommandHandler[RequestT, ResultT],
    ) -> CommandHandler[RequestT, ResultT]:
        """
        Wraps one command handler with its lifecycle reporting.

        Args:
            handler (CommandHandler[RequestT, ResultT]): Handler doing the
                                                         actual work.

        Returns:
            CommandHandler[RequestT, ResultT]: Handler reporting its own
                                               lifecycle.
        """

        @wraps(handler)
        async def execute(
            context: CommandContext,
            request: RequestT,
        ) -> ResultT:
            """
            Runs the handler and reports the lifecycle around it.

            Args:
                context (CommandContext): CommandContext object to report
                                          updates to.
                request (RequestT): Request passed to the handler.

            Returns:
                ResultT: Result of the handler.
            """
            return await _execute(
                context=context,
                command=name,
                operation=handler(context, request),
                terminal=lambda result: batch_progress(
                    command=name,
                    phase=_batch_phase(result.summary),
                    summary=result.summary,
                ),
            )

        return execute

    return decorate


def _batch_phase(summary: BatchSummary) -> CommandProgressPhase:
    """
    Maps a batch summary to the terminal lifecycle phase of the batch.

    Args:
        summary (BatchSummary): Result summary of a completed batch run.

    Returns:
        CommandProgressPhase: Timed out, failed, or completed phase.
    """
    if summary.timed_out:
        return CommandProgressPhase.TIMED_OUT
    if summary.failed:
        return CommandProgressPhase.FAILED
    return CommandProgressPhase.COMPLETED


async def _gather(tasks: list[asyncio.Task[Any]]) -> list[Any]:
    """
    Awaits every task and cancels the remaining ones if any task fails.

    Args:
        tasks (list[asyncio.Task[Any]]): Tasks to await.

    Returns:
        list[Any]: Results of all tasks in the order of the input tasks.
    """
    try:
        return await asyncio.gather(*tasks)

    # Cancel all pending tasks on BaseException (includes CancelledError)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise  # to re-raise the exception


async def execute_with_concurrency_limit[InputT, OutputT](
    items: tuple[InputT, ...],
    operation: Callable[[InputT], Awaitable[OutputT]],
    *,
    max_concurrency: int,
) -> tuple[OutputT, ...]:
    """
    Simple wrapper that executes an asynchronous operation for each input item
    without reporting any progress to the callback or creating a summary. Can
    be used to run concurrent tasks at places, where the outcome of the
    execution is needed to further process the batch and should not be reported
    to the caller.
    Runs at most ``max_concurrency`` operations simultaneously.

    Args:
        items (tuple[InputT, ...]): Items to apply the operation to.
        operation (Callable[[InputT], Awaitable[OutputT]]): Asynchronous
                                                            function receiving
                                                            one item and
                                                            returning its
                                                            result.
        max_concurrency (int): Maximum amount of concurrent operations.

    Returns:
        tuple[OutputT, ...]: Results of all operations. Results retain the same
                             order as the items input.
    """
    validate_max_concurrency(max_concurrency)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def execute(item: InputT) -> OutputT:
        """
        Runs the operation for one item once the semaphore admits it.

        Args:
            item (InputT): Item to apply the operation to.

        Returns:
            OutputT: Result of the operation.
        """
        async with semaphore:
            return await operation(item)

    tasks = [asyncio.create_task(execute(item)) for item in items]
    return tuple(await _gather(tasks))


async def run_batch[ItemT, ItemResultT: StatusResult](
    context: CommandContext,
    command: str,
    items: tuple[ItemT, ...],
    operation: Callable[[CommandContext, ItemT], Awaitable[ItemResultT]],
    *,
    max_concurrency: int,
) -> tuple[tuple[ItemResultT, ...], BatchSummary]:
    """
    Runs one operation for every batch item with bounded concurrency and
    reports each completed item to the caller.

    The operation may be a registered command. Items therefore run with their
    progress muted, so a batch reports its own 'advanced' updates instead of
    one nested command lifecycle per item.

    Args:
        context (CommandContext): CommandContext object to report updates to.
        command (str): Command name used for the progress updates.
        items (tuple[ItemT, ...]): Items to execute.
        operation (Callable[[CommandContext, ItemT], Awaitable[ItemResultT]]):
            Operation to apply to every item.
        max_concurrency (int): Maximum amount of concurrent operations.

    Returns:
        tuple[tuple[ItemResultT, ...], BatchSummary]: Item results in input
                                                      order and the summary of
                                                      the batch.
    """
    validate_max_concurrency(max_concurrency)
    total_items = len(items)
    semaphore = asyncio.Semaphore(max_concurrency)
    lock = asyncio.Lock()
    counts: Counter[Outcome] = Counter()

    # Create new context which disables the per-item progress callback.
    # Otherwise each item would report phases like started, failed, etc.
    # During batch processing only 'advanced' is reported for each completed
    # item. All other phases like started, failed only refer to the back as a
    # whole.
    # This way the single-command functions can be reused during batch
    # processing.
    item_context = replace(context, progress_callback=None)

    async def execute(item_index: int, item: ItemT) -> ItemResultT:
        """
        Runs the operation for one item and reports the completed item.

        Args:
            item_index (int): Index of the batch item.
            item (ItemT): Item to apply the operation to.

        Returns:
            ItemResultT: Result of the operation.
        """
        async with semaphore:
            result = await operation(item_context, item)

        # Record and report under a lock to keep the counters consistent
        async with lock:
            counts[result.status.outcome] += 1
            await _report_item(
                context,
                command,
                item_index=item_index,
                total_items=total_items,
                result=result,
                counts=counts,
            )
        return result

    tasks = [
        asyncio.create_task(execute(item_index, item))
        for item_index, item in enumerate(items)
    ]
    results: tuple[ItemResultT, ...] = tuple(await _gather(tasks))
    return results, summarize(counts)


async def report_batch_results[ItemResultT: StatusResult](
    context: CommandContext,
    command: str,
    results: tuple[ItemResultT, ...],
) -> BatchSummary:
    """
    Records and reports results that were already computed. This is needed by
    commands that can only classify their items once every result is known
    (e.g. after deduplicating views across analytical models).

    Args:
        context (CommandContext): CommandContext object to report updates to.
        command (str): Command name used for the progress updates.
        results (tuple[ItemResultT, ...]): Completed results to report.

    Returns:
        BatchSummary: Aggregate outcome counts of the reported results.
    """
    total_items = len(results)
    counts: Counter[Outcome] = Counter()
    for item_index, result in enumerate(results):
        counts[result.status.outcome] += 1
        await _report_item(
            context,
            command,
            item_index=item_index,
            total_items=total_items,
            result=result,
            counts=counts,
        )
    return summarize(counts)


async def _report_item(
    context: CommandContext,
    command: str,
    *,
    item_index: int,
    total_items: int,
    result: object,
    counts: Counter[Outcome],
) -> None:
    """
    Reports one completed batch item and its result to the caller. Reports are
    only delivered if the caller supplied the matching callbacks.

    Args:
        context (CommandContext): CommandContext object to report updates to.
        command (str): Command name used for the progress updates.
        item_index (int): Index of the completed batch item.
        total_items (int): Total number of items in the batch.
        result (object): Command-specific batch item result.
        counts (Counter[Outcome]): Outcomes recorded so far.
    """
    # Report phase 'advanced' for the completed batch item
    await context.report(
        batch_progress(
            command,
            CommandProgressPhase.ADVANCED,
            summarize(counts),
            total_items=total_items,
            item_index=item_index,
        )
    )

    # Report the actual result to the caller (if a callback was supplied)
    # This can be used to persist results of batch items while the batch
    # itself is still running.
    await context.report_batch_item_result(
        BatchItemResult(
            command=command,
            item_index=item_index,
            total_items=total_items,
            result=result,
        )
    )
