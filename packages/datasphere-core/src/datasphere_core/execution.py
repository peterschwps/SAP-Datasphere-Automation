import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from datasphere_core.context import CommandContext
from datasphere_core.errors import CommandTimeoutError
from datasphere_core.models.common import (
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
    validate_max_concurrency,
)


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
        return "timed_out"
    if summary.failed:
        return "failed"
    return "completed"


async def execute_command[ResultT](
    context: CommandContext,
    command: str,
    operation: Callable[[], Awaitable[ResultT]],
    *,
    result_phase: Callable[[ResultT], CommandProgressPhase] | None = None,
) -> ResultT:
    """
    Initiates the execution of a single operation. The handling of the
    execution itself is done by the 'operation'.

    Args:
        context (CommandContext): CommandContext object to report updates to.
        command (str): Command name used for lifecycle updates.
        operation (Callable[[], Awaitable[ResultT]]): Callable that executes
                                                      the single command.
        result_phase (Callable[[ResultT], CommandProgressPhase] | None, optional):
            Optional callable that evaluates the result of the operation and
            returns a CommandProgressPhase. Defaults to None.

    Returns:
        ResultT: Result of the executed operation.
    """  # noqa: E501
    return await _handle_operation_lifecycle(
        context=context,
        command=command,
        operation=operation,
        result_phase=result_phase,
    )


async def execute_batch[ResultT](
    context: CommandContext,
    command: str,
    operation: Callable[[BatchProgressState], Awaitable[ResultT]],
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
        operation (Callable[[BatchProgressState], Awaitable[ResultT]]):
            Callable that executes the batch and updates the supplied batch
            progress state.
        total_items (int | None, optional): Initial number of items in the
                                            batch. Defaults to None.
        result_phase (Callable[[ResultT], CommandProgressPhase] | None, optional):
            Optional callable that evaluates the result of the operation and
            returns a CommandProgressPhase. Defaults to None.

    Returns:
        ResultT: Result of the executed batch operation.
    """  # noqa: E501
    progress_state = BatchProgressState(total_items=total_items)

    async def run_operation() -> ResultT:
        """
        Executes the batch operation with its progress state. Passes the
        BatchProgressState to the operation so it can report updates while
        execution single tasks of the batch.

        Returns:
            ResultT: Result of the executed batch operation.
        """
        return await operation(progress_state)

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
        phase="started",
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
            phase="timed_out",
            message=str(error),
            batch_progress_state=batch_progress_state,
        )
        await context.report(command_progress)
        raise

    except asyncio.CancelledError as error:
        command_progress = _lifecycle_progress(
            command=command,
            phase="cancelled",
            message=str(error) or None,
            batch_progress_state=batch_progress_state,
        )
        await context.report(command_progress)
        raise

    except Exception:
        command_progress = _lifecycle_progress(
            command=command,
            phase="failed",
            batch_progress_state=batch_progress_state,
        )
        await context.report(command_progress)
        raise

    # Evaluate result with supplied callback function or set to 'completed'
    phase = result_phase(result) if result_phase is not None else "completed"

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
