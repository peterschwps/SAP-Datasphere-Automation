from dataclasses import dataclass
from enum import StrEnum

MAXIMUM_BATCH_CONCURRENCY = 32


class CommandProgressPhase(StrEnum):
    """
    Lifecycle phases of a command execution.
    """
    STARTED = "started"
    ADVANCED = "advanced"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class BatchItemFinalStatus(StrEnum):
    """
    Final statuses of a completed batch item.
    """
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


def validate_max_concurrency(max_concurrency: int) -> None:
    """
    Validates that a concurrency setting is within the supported limit.

    Args:
        max_concurrency (int): Number of operations allowed to run at once.

    Raises:
        ValueError: If the value is not in between the valid range.
    """
    if (
        isinstance(max_concurrency, bool)
        or not isinstance(max_concurrency, int)
        or not 0 < max_concurrency <= MAXIMUM_BATCH_CONCURRENCY
    ):
        raise ValueError(
            "Maximum concurrency must be an integer between 1 and "
            f"{MAXIMUM_BATCH_CONCURRENCY}."
        )


@dataclass(frozen=True, slots=True)
class BatchItemResult:
    """
    Result of a completed task inside a batch. Can be used to persist results
    while the batch execution is still running.

    The structure of the result object depends on the command that was called.
    """
    command: str
    item_index: int
    total_items: int
    result: object


@dataclass(frozen=True, slots=True)
class BatchSummary:
    """
    Results of a batch execution. Only created after the batch is completed.
    """
    total: int
    succeeded: int
    failed: int
    skipped: int
    timed_out: int


@dataclass(frozen=True, slots=True)
class CommandProgress:
    """
    Progress of a command execution. Contains metadata information about the
    batch if the command is executing a batch operation.
    """
    command: str
    phase: CommandProgressPhase
    message: str | None = None
    completed_items: int | None = None
    total_items: int | None = None
    succeeded_items: int | None = None
    failed_items: int | None = None
    skipped_items: int | None = None
    timed_out_items: int | None = None
    item_index: int | None = None
