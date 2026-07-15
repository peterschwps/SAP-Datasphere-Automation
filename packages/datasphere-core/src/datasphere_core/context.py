from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from datasphere_api import DatasphereClient

from datasphere_core.models import CommandProgress

type ProgressCallback = Callable[[CommandProgress], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CommandContext:
    """
    Runtime dependencies available to command handlers (e.g. start_task_chain).
    """
    # Authenticated DatasphereClient
    client: DatasphereClient

    # Optional callback to report progress updates to the caller
    # (not used in the CLI, but used in the MCP)
    progress: ProgressCallback | None = None

    async def report(self, update: CommandProgress) -> None:
        """
        Reports progress if the caller supplied a callback.

        Args:
            update (CommandProgress): Runtime update to report to the progress
                                      callback (carriers information about a
                                      specific task).
        """
        if self.progress is not None:
            await self.progress(update)
