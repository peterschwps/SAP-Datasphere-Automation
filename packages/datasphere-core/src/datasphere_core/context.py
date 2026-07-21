from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from datasphere_api import DatasphereClient

from datasphere_core.models import BatchItemResult, CommandProgress

type ProgressCallback = Callable[[CommandProgress], Awaitable[None]]
type CheckpointCallback = Callable[[BatchItemResult], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CommandContext:
    """
    Runtime dependencies available to command handlers.
    """

    # Authenticated DatasphereClient
    client: DatasphereClient

    # Optional callback to report progress of the command call
    progress: ProgressCallback | None = None

    # Optional callback to report completion after finishing a batch item
    checkpoint: CheckpointCallback | None = None

    async def report(self, update: CommandProgress) -> None:
        """
        Reports progress updates if the caller supplied a callback.

        Args:
            update (CommandProgress): Runtime update to report to the progress
                                      callback (carriers information about a
                                      specific task).
        """
        if self.progress is not None:
            await self.progress(update)

    async def report_batch_item_result(
        self,
        result: BatchItemResult,
    ) -> None:
        """
        Reports a result after completing a batch item if the caller supplied
        a callback.

        Args:
            result (BatchItemResult): Runtime update to report the completion
                                      of a batch item to the checkpoint
                                      callback.
        """
        if self.checkpoint is not None:
            await self.checkpoint(result)
