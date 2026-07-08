import asyncio
from collections.abc import Callable, Iterable


async def run_async_tasks(
    items: Iterable,
    function: Callable,
    thread_count: int = 1,
) -> None:
    """
    Executes the given function. 'Parallelizes' the tasks if the
    thread count is greater than 1.

    Args:
        items (Iterable): List of all arguments to be passed to the
                          function.
        function (Callable): Function to be executed.
        thread_count (int, optional): Amount of concurrent
                                      asynchronous tasks.
                                      Default is 1.
    """
    if thread_count > 1:
        semaphore = asyncio.Semaphore(thread_count)
        tasks = []
        for item in items:

            async def process_item(item):
                async with semaphore:
                    if isinstance(item, list | tuple):
                        await function(*item)
                    else:
                        await function(item)

            task = asyncio.create_task(process_item(item))
            tasks.append(task)
        await asyncio.gather(*tasks)

    else:
        for item in items:
            if isinstance(item, list | tuple):
                await function(*item)
            else:
                await function(item)
