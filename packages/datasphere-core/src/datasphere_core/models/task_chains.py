from dataclasses import dataclass

from datasphere_core.models.common import (
    BatchSummary,
    CommandStatus,
    Outcome,
    validate_max_concurrency,
    validate_timeout,
)

DEFAULT_TASK_CHAIN_MAX_CONCURRENCY = 10
DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS = 60 * 60  # one hour
MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS = 60 * 60 * 24  # one day


class TaskChainStatus(CommandStatus):
    """
    Result status of one task chain execution.
    """
    COMPLETED = "completed", Outcome.SUCCEEDED
    FAILED = "failed", Outcome.FAILED
    START_FAILED = "start_failed", Outcome.FAILED
    TIMED_OUT = "timed_out", Outcome.TIMED_OUT


@dataclass(frozen=True, slots=True)
class RunTaskChainRequest:
    """
    Input for one task chain execution.
    """
    chain: str
    space: str
    timeout_seconds: float = DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """
        Validates the task chain timeout.

        Raises:
            ValueError: If the timeout is not within the supported range.
        """
        validate_timeout(
            self.timeout_seconds,
            MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS,
        )


@dataclass(frozen=True, slots=True)
class RunTaskChainResult:
    """
    Result of one task chain execution.
    """
    chain: str
    space: str
    status: TaskChainStatus
    log_status: str | None = None
    log_id: str | None = None
    runtime_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class RunTaskChainBatchRequest:
    """
    Input for running task chains with concurrency.
    """
    requests: tuple[RunTaskChainRequest, ...]
    max_concurrency: int = DEFAULT_TASK_CHAIN_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is outside the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class RunTaskChainBatchResult:
    """
    Ordered results of running task chains in a batch.
    """
    results: tuple[RunTaskChainResult, ...]
    summary: BatchSummary
