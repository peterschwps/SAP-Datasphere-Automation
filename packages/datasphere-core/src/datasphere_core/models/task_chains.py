import math
from dataclasses import dataclass
from enum import StrEnum

from datasphere_core.models.common import (
    BatchSummary,
    validate_max_concurrency,
)

DEFAULT_TASK_CHAIN_MAX_CONCURRENCY = 10
DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS = 60 * 60  # one hour
MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS = 60 * 60 * 24  # one day


class TaskChainStatus(StrEnum):
    """
    Result status of one task chain execution.
    """
    COMPLETED = "completed"
    FAILED = "failed"
    START_FAILED = "start_failed"
    TIMED_OUT = "timed_out"


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
            ValueError: If timeout is invalid.
        """
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds
            <= MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS
        ):
            raise ValueError(
                "Timeout must be greater than zero and at most "
                f"{MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS} seconds."
            )


@dataclass(frozen=True, slots=True)
class RunTaskChainResult:
    """
    Result of one task chain execution.
    """
    chain: str
    space: str
    status: TaskChainStatus
    sap_status: str | None = None
    operation_id: str | None = None
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
        Validates item types and the batch concurrency limit.

        Raises:
            TypeError: If requests is not a tuple of RunTaskChainRequest.
            ValueError: If the concurrency limit is outside the supported
                        range.
        """
        if not isinstance(self.requests, tuple):
            raise TypeError("Batch requests must be a tuple.")
        if not all(
            isinstance(request, RunTaskChainRequest)
            for request in self.requests
        ):
            raise TypeError(
                "Batch requests must contain RunTaskChainRequest objects."
            )
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class RunTaskChainBatchResult:
    """
    Ordered results of a running task chains in a batch.
    """
    results: tuple[RunTaskChainResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates result types and the aggregate outcome counts.

        Raises:
            TypeError: If results is not a tuple of RunTaskChainResult.
            ValueError: If the summary does not match the result statuses.
        """
        if not isinstance(self.results, tuple) or not all(
            isinstance(result, RunTaskChainResult) for result in self.results
        ):
            raise TypeError(
                "Batch results must contain RunTaskChainResult objects."
            )
        expected = BatchSummary(
            total=len(self.results),
            succeeded=sum(
                result.status is TaskChainStatus.COMPLETED
                for result in self.results
            ),
            failed=sum(
                result.status
                in (TaskChainStatus.FAILED, TaskChainStatus.START_FAILED)
                for result in self.results
            ),
            skipped=0,
            timed_out=sum(
                result.status is TaskChainStatus.TIMED_OUT
                for result in self.results
            ),
        )
        if self.summary != expected:
            raise ValueError("Batch summary does not match batch results.")
