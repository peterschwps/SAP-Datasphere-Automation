import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

from datasphere_core.models.common import validate_max_concurrency


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
