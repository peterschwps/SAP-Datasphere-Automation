from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from datasphere_api import DatasphereClient

from datasphere_core.models.common import BatchItemResult, CommandProgress

type ProgressCallback = Callable[[CommandProgress], Awaitable[None]]
type BatchItemResultCallback = Callable[[BatchItemResult], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CommandContext:
    """
    Runtime dependencies available to command handlers.
    """
    # Authenticated DatasphereClient
    client: DatasphereClient

    # Optional callback to report progress of the command call
    # This reports very general progress of the command, e.g. if it has been
    # started, completed, failed etc.
    progress_callback: ProgressCallback | None = None

    # Optional callback to report the result after finishing a batch item
    # This sends the actual result of the execution and can be used to persist
    # every result of completed items while the command is still running.
    batch_item_result_callback: BatchItemResultCallback | None = None

    async def report(self, command_progress: CommandProgress) -> None:
        """
        Reports progress updates if the caller supplied a callback.

        Args:
            command_progress (CommandProgress): Latest command status to report
                                                to the progress callback
                                                (carriers information about a
                                                specific task).
        """
        if self.progress_callback is not None:
            await self.progress_callback(command_progress)

    async def report_batch_item_result(
        self,
        batch_item_result: BatchItemResult,
    ) -> None:
        """
        Reports a result after completing a batch item if the caller supplied
        a callback.

        Args:
            batch_item_result (BatchItemResult): Result of a single batch item
                                                 to report back to the
                                                 checkpoint callback. This can
                                                 be used to persist results
                                                 while the batch execution is
                                                 still running.
        """
        if self.batch_item_result_callback is not None:
            await self.batch_item_result_callback(batch_item_result)
