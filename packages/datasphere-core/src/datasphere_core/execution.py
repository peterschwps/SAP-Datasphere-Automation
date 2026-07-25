import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import cast

from datasphere_core.context import CommandContext
from datasphere_core.errors import CommandTimeoutError
from datasphere_core.models.common import (
    BatchItemFinalStatus,
    BatchItemResult,
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
    validate_max_concurrency,
)

type CommandOperation[RequestT, ResultT] = Callable[
    [CommandContext, RequestT],
    Awaitable[ResultT],
]
type BatchOperation[RequestT, ResultT] = Callable[
    [BatchExecution, RequestT],
    Awaitable[ResultT],
]


@dataclass(slots=True)
class BatchProgressState:
    """
    Mutable dataclass to hold metadata information about a batch run.
    """
    total_items: int | None = None
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    timed_out: int = 0

    @property
    def completed_items(self) -> int:
        return self.succeeded + self.failed + self.skipped + self.timed_out

    def record(self, status: BatchItemFinalStatus) -> None:
        """
        Records the outcome of one completed batch item by adding it to the
        corresponding counter.

        Args:
            status (BatchItemFinalStatus): Status of the batch item execution.
        """
        match status:
            case BatchItemFinalStatus.SUCCEEDED:
                self.succeeded += 1
            case BatchItemFinalStatus.FAILED:
                self.failed += 1
            case BatchItemFinalStatus.SKIPPED:
                self.skipped += 1
            case BatchItemFinalStatus.TIMED_OUT:
                self.timed_out += 1

    def to_summary(self) -> BatchSummary:
        """
        Creates a summary from the recorded batch outcomes. This summary
        displays the result of the full batch exection.

        Returns:
            BatchSummary: Aggregate outcome counts for completed items.
        """
        return BatchSummary(
            total=self.completed_items,
            succeeded=self.succeeded,
            failed=self.failed,
            skipped=self.skipped,
            timed_out=self.timed_out,
        )


@dataclass(slots=True)
class BatchExecution:
    """
    Runtime state and shared operations for batch executions. Supplied to the
    all batch operations.
    """
    context: CommandContext
    command: str
    progress_state: BatchProgressState
    _progress_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def set_total_items(self, total_items: int) -> None:
        """
        Sets the total number of items within the batch.

        Args:
            total_items (int): Total number of items in the batch.
        """
        self.progress_state.total_items = total_items

    async def complete_item(
        self,
        *,
        item_index: int,
        final_status: BatchItemFinalStatus,
        result: object,
    ) -> None:
        """
        Records and reports one completed batch item and its result. Reports
        will only be delivered if the caller supplied callbacks.

        Args:
            item_index (int): Index of the completed batch item.
            final_status (BatchItemFinalStatus): Final status of the completed
                                                 batch item.
            result (object): Command-specific batch item result.

        Raises:
            RuntimeError: If the total number of items is not known.
        """
        total_items = self.progress_state.total_items
        if total_items is None:
            raise RuntimeError(
                "Cannot report a batch item result without a total item count."
            )
        async with self._progress_lock:
            # Add result to counter of internal progress state
            self.progress_state.record(final_status)
            # Report phase 'advanced' for each completed batch item
            await self.context.report(
                CommandProgress(
                    command=self.command,
                    phase=CommandProgressPhase.ADVANCED,
                    completed_items=self.progress_state.completed_items,
                    total_items=total_items,
                    succeeded_items=self.progress_state.succeeded,
                    failed_items=self.progress_state.failed,
                    skipped_items=self.progress_state.skipped,
                    timed_out_items=self.progress_state.timed_out,
                    item_index=item_index,
                )
            )
            # Report actual result to the caller (if callback supplied)
            # This could be use to persist results of batch items while the
            # batch itself is still running
            await self.context.report_batch_item_result(
                BatchItemResult(
                    command=self.command,
                    item_index=item_index,
                    total_items=total_items,
                    result=result,
                )
            )

    async def execute_items[ItemT, ResultT](
        self,
        items: tuple[ItemT, ...],
        operation: CommandOperation[ItemT, ResultT],
        *,
        max_concurrency: int,
        classify: Callable[[ResultT], BatchItemFinalStatus],
    ) -> tuple[ResultT, ...]:
        """
        Handles the execution of all items in a batch. Calls the required
        methods to report status updates and results.

        Args:
            items (tuple[ItemT, ...]): Items to execute.
            operation (CommandOperation[ItemT, ResultT]): Operation to apply to
                                                          items.
            max_concurrency (int): Maximum number of concurrent operations.
            classify (Callable[[ResultT], BatchItemFinalStatus]): Callable to
                                                                  categorize
                                                                  each item
                                                                  result.

        Returns:
            tuple[ResultT, ...]: Item results in input order.
        """
        self.set_total_items(len(items))

        async def execute_indexed(indexed_item: tuple[int, ItemT]) -> ResultT:
            """
            Executes one batch item and handles its result. This function is
            used to handle all batch items in the async loop.

            Args:
                indexed_item (tuple[int, ItemT]): Tuple with the index of the
                                                  batch item and the item
                                                  itself.

            Returns:
                ResultT: Result of the operation.
            """
            index, item = indexed_item
            result = await operation(self.context, item)
            await self.complete_item(
                item_index=index,
                final_status=classify(result),
                result=result,
            )
            return result

        return await execute_with_concurrency_limit(
            items=tuple(enumerate(items)),
            operation=execute_indexed,
            max_concurrency=max_concurrency,
        )

    def to_summary(self) -> BatchSummary:
        """
        Creates a summary from the recorded batch outcomes. This summary
        displays the result of the full batch exection.

        Returns:
            BatchSummary: Aggregate outcome counts for completed items.
        """
        return self.progress_state.to_summary()


def _lifecycle_progress(
    command: str,
    phase: CommandProgressPhase,
    *,
    message: str | None = None,
    batch_progress_state: BatchProgressState | None = None,
) -> CommandProgress:
    """
    Build a CommandProgress object from the supplied arguments. Differentiates
    between the progress of a single command execution (e.g. persisting a view)
    and the progress of a batch execution (e.g. persisting multiple views).

    Args:
        command (str): Name of the command (e.g. 'views.persist').
        phase (CommandProgressPhase): Phase of the command. If the command is a
                                      batch execution it refers to the whole
                                      batch, not a single item.
        message (str | None, optional): Message to provide feedback to the
                                        caller. This can be used to reroute an
                                        error message. Defaults to None.
        batch_progress_state (BatchProgressState | None, optional):
            Object holding metadata information about a batch execution.
            Defaults to None.

    Returns:
        CommandProgress: Object representing the current progress of a command
                         execution.
    """
    # If the progress only belongs to a single command execution
    if batch_progress_state is None:
        return CommandProgress(
            command=command,
            phase=phase,
            message=message,
        )

    # If the progress belongs to a batch execution
    return CommandProgress(
        command=command,
        phase=phase,
        message=message,
        completed_items=batch_progress_state.completed_items,
        total_items=batch_progress_state.total_items,
        succeeded_items=batch_progress_state.succeeded,
        failed_items=batch_progress_state.failed,
        skipped_items=batch_progress_state.skipped,
        timed_out_items=batch_progress_state.timed_out,
    )


def batch_result_phase(summary: BatchSummary) -> CommandProgressPhase:
    """
    Maps a batch summary to its exact terminal lifecycle phase. Checks if any
    items failed or timed out.

    Args:
        summary (BatchSummary): Result summary of a completed batch run.

    Returns:
        CommandProgressPhase: Phase of a command execution.
    """
    if summary.timed_out:
        return CommandProgressPhase.TIMED_OUT
    if summary.failed:
        return CommandProgressPhase.FAILED
    return CommandProgressPhase.COMPLETED


async def execute_command[RequestT, ResultT](
    context: CommandContext,
    command: str,
    request: RequestT,
    operation: CommandOperation[RequestT, ResultT],
    *,
    result_phase: Callable[[ResultT], CommandProgressPhase] | None = None,
) -> ResultT:
    """
    Initiates the execution of a single operation. The handling of the
    execution itself is done by the 'operation'.

    Args:
        context (CommandContext): CommandContext object to report updates to.
        command (str): Command name used for lifecycle updates.
        request (RequestT): Request passed to the command operation.
        operation (CommandOperation[RequestT, ResultT]): Callable that executes
                                                         the single command.
        result_phase (Callable[[ResultT], CommandProgressPhase] | None, optional):
            Optional callable that evaluates the result of the operation and
            returns a CommandProgressPhase. Defaults to None.

    Returns:
        ResultT: Result of the executed operation.
    """  # noqa: E501
    async def run_operation() -> ResultT:
        return await operation(context, request)

    return await _handle_operation_lifecycle(
        context=context,
        command=command,
        operation=run_operation,
        result_phase=result_phase,
    )


async def execute_batch[RequestT, ResultT](
    context: CommandContext,
    command: str,
    request: RequestT,
    operation: BatchOperation[RequestT, ResultT],
    *,
    total_items: int | None = None,
    result_phase: Callable[[ResultT], CommandProgressPhase] | None = None,
) -> ResultT:
    """
    Initiates the execution of a batch operation. The handling of the execution
    itself is done by the 'operation'.

    Args:
        context (CommandContext): CommandContext object to report updates to.
        command (str): Command name used for lifecycle updates.
        request (RequestT): Request passed to the batch operation.
        operation (BatchOperation[RequestT, ResultT]): Callable that executes
                                                       the batch.
        total_items (int | None, optional): Initial number of items in the
                                            batch. Defaults to None.
        result_phase (Callable[[ResultT], CommandProgressPhase] | None, optional):
            Optional callable that evaluates the result of the operation and
            returns a CommandProgressPhase. Defaults to None.

    Returns:
        ResultT: Result of the executed batch operation.
    """  # noqa: E501
    progress_state = BatchProgressState(total_items=total_items)
    execution = BatchExecution(
        context=context,
        command=command,
        progress_state=progress_state,
    )

    async def run_operation() -> ResultT:
        """
        Calls the batch operation.

        Returns:
            ResultT: Result of the fully executed batch operation.
        """
        return await operation(execution, request)

    return await _handle_operation_lifecycle(
        context=context,
        command=command,
        operation=run_operation,
        result_phase=result_phase,
        batch_progress_state=progress_state,
    )


async def _handle_operation_lifecycle[ResultT](
    context: CommandContext,
    command: str,
    operation: Callable[[], Awaitable[ResultT]],
    *,
    result_phase: Callable[[ResultT], CommandProgressPhase] | None,
    batch_progress_state: BatchProgressState | None = None,
) -> ResultT:
    """
    Executes an operation and reports its lifecycle updates. An operation can
    be the execution of a single command/tasks or running multiple tasks as a
    batch.

    Args:
        context (CommandContext): CommandContext object to report updates to.
        command (str): Command name used for lifecycle updates.
        operation (Callable[[], Awaitable[ResultT]]): Operation to execute.
        result_phase (Callable[[ResultT], CommandProgressPhase] | None):
            Optional callable that evaluates the operation result.
        batch_progress_state (BatchProgressState | None, optional):
            Progress state for a batch operation. Defaults to None.

    Returns:
        ResultT: Result of the executed operation.
    """
    # Report start of operation
    command_progress = _lifecycle_progress(
        command=command,
        phase=CommandProgressPhase.STARTED,
        batch_progress_state=batch_progress_state,
    )
    await context.report(command_progress)

    # Execute operation and report errors / cancellations
    # This operation function either handles a single command or a batch with
    # all its items!
    try:
        result = await operation()

    except CommandTimeoutError as error:
        command_progress = _lifecycle_progress(
            command=command,
            phase=CommandProgressPhase.TIMED_OUT,
            message=str(error),
            batch_progress_state=batch_progress_state,
        )
        await context.report(command_progress)
        raise

    except asyncio.CancelledError as error:
        command_progress = _lifecycle_progress(
            command=command,
            phase=CommandProgressPhase.CANCELLED,
            message=str(error) or None,
            batch_progress_state=batch_progress_state,
        )
        await context.report(command_progress)
        raise

    except Exception:
        command_progress = _lifecycle_progress(
            command=command,
            phase=CommandProgressPhase.FAILED,
            batch_progress_state=batch_progress_state,
        )
        await context.report(command_progress)
        raise

    # Evaluate result with supplied callback function or set to 'completed'
    phase = (
        result_phase(result)
        if result_phase is not None
        else CommandProgressPhase.COMPLETED
    )

    # Report end of operation
    command_progress = _lifecycle_progress(
        command=command,
        phase=phase,
        batch_progress_state=batch_progress_state,
    )
    await context.report(command_progress)
    return result


async def execute_with_concurrency_limit[InputT, OutputT](
    items: tuple[InputT, ...],
    operation: Callable[[InputT], Awaitable[OutputT]],
    *,
    max_concurrency: int,
) -> tuple[OutputT, ...]:
    """
    Executes an asynchronous operation for each input item.
    Runs at most 'max_concurrency' tasks simultaneously.

    Args:
        items (tuple[InputT, ...]): Tuple of items to use when applying the
                                    specified operation.
        operation (Callable[[InputT], Awaitable[OutputT]]): Asynchronous
                                                            function that
                                                            receives an item as
                                                            the input and
                                                            returns an
                                                            awaitable output.
        max_concurrency (int): Maximum amount of concurrent tasks.

    Raises:
        RuntimeError: If results are missing after completing all tasks.

    Returns:
        tuple[OutputT, ...]: Tuple with all results of the operations. Results
                             retain the same order as the items input.
    """
    # Validation of input params
    validate_max_concurrency(max_concurrency)
    if not items:
        return ()

    # Create unique object as placeholder for missing results ("sentinel")
    missing = object()
    results: list[OutputT | object] = [missing] * len(items)
    next_index = 0

    async def worker() -> None:
        """
        Executes an operation using an item of items at next_index and saves
        the result to the same index in the results list.
        """
        nonlocal next_index  # to increase variable of the surrounding function
        while next_index < len(items):
            index = next_index
            next_index += 1
            results[index] = await operation(items[index])

    # Create workers
    worker_count = min(max_concurrency, len(items))
    workers = [asyncio.create_task(worker()) for _ in range(worker_count)]

    # Execute all tasks
    try:
        await asyncio.gather(*workers)

    # Cancel all workers on BaseException (includes asyncio.CancelledError)
    except BaseException:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise  # to re-raise the exception

    # Check for any missing results
    if any(result is missing for result in results):
        raise RuntimeError("Bounded operation did not produce every result.")

    return cast(tuple[OutputT, ...], tuple(results))
