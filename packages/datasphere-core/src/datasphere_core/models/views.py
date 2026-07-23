import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from datasphere_core.models.common import (
    BatchSummary,
    validate_max_concurrency,
)

DEFAULT_VIEW_TIMEOUT_SECONDS = 3600.0
MAXIMUM_VIEW_TIMEOUT_SECONDS = 86400.0
DEFAULT_VIEW_MAX_CONCURRENCY = 10


class FindViewPersistenceCandidatesStatus(StrEnum):
    """
    Result status of finding persistence candidates using the view analyzer.
    """
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class FindViewAttributeMatchesStatus(StrEnum):
    """
    Result status of finding matching view attributes.
    """
    COMPLETED = "completed"
    FAILED = "failed"


class CreateViewPartitioningStatus(StrEnum):
    """
    Result status of creating view partitioning.
    """
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    INVALID_COLUMN = "invalid_column"
    FAILED = "failed"


class DeleteViewPartitioningStatus(StrEnum):
    """
    Result status of deleting view partitioning.
    """
    DELETED = "deleted"
    FAILED = "failed"


class PersistViewStatus(StrEnum):
    """
    Result status of persisting a view.
    """
    COMPLETED = "completed"
    START_FAILED = "start_failed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class UnpersistViewStatus(StrEnum):
    """
    Result status of removing persisted view data.
    """
    COMPLETED = "completed"
    ALREADY_ABSENT = "already_absent"
    START_FAILED = "start_failed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class LockViewPartitionsStatus(StrEnum):
    """
    Result status of locking view partitions.
    """
    LOCKED = "locked"
    NO_PARTITIONS = "no_partitions"
    FAILED = "failed"


class UnlockViewPartitionsStatus(StrEnum):
    """
    Result status of unlocking view partitions.
    """
    UNLOCKED = "unlocked"
    NO_PARTITIONS = "no_partitions"
    FAILED = "failed"


class _StatusResult(Protocol):
    """
    Protocol for a result dataclass. This is needed to validate batch results
    through a generic function.
    """

    @property
    def status(self) -> str:
        """
        A required attribute in all result dataclasses.

        Returns:
            str: Status value associated with the result.
        """
        ...


def _validate_text(name: str, value: str) -> None:
    """
    Validates that a required view-related text value is not empty.

    Args:
        name (str): Human-readable field name for validation errors.
        value (str): Text value to validate.

    Raises:
        ValueError: If the value is not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty.")


def _validate_timeout(timeout_seconds: float) -> None:
    """
    Validates a view operation timeout.

    Args:
        timeout_seconds (float): Positive finite timeout in seconds.

    Raises:
        ValueError: If the timeout is not positive, finite, or within the
                    supported maximum.
    """
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= MAXIMUM_VIEW_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "Timeout must be greater than zero and at most "
            f"{MAXIMUM_VIEW_TIMEOUT_SECONDS} seconds."
        )


def _validate_year(name: str, value: int) -> None:
    """
    Validates that a year parameter is an integer.

    Args:
        name (str): Human-readable field name for validation errors.
        value (int): Year value to validate.

    Raises:
        ValueError: If the value is not an integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer.")


def _validate_batch_requests[RequestT](
    requests: tuple[RequestT, ...],
    request_type: type[RequestT],
    max_concurrency: int,
) -> None:
    """
    Validates request types and concurrency for a batch.

    Args:
        requests (tuple[RequestT, ...]): Requests supplied to the batch.
        request_type (type[RequestT]): Expected request class.
        max_concurrency (int): Maximum number of concurrent operations.

    Raises:
        TypeError: If requests is not a tuple of the expected request type.
        ValueError: If the concurrency setting is invalid.
    """
    if not isinstance(requests, tuple):
        raise TypeError("Batch requests must be a tuple.")
    if not all(isinstance(request, request_type) for request in requests):
        raise TypeError(
            f"Batch requests must contain {request_type.__name__} objects."
        )
    validate_max_concurrency(max_concurrency)


def _validate_batch_result[ResultT: _StatusResult](
    results: tuple[ResultT, ...],
    result_type: type[ResultT],
    summary: BatchSummary,
    *,
    succeeded: tuple[str, ...],
    failed: tuple[str, ...],
    skipped: tuple[str, ...] = (),
    timed_out: tuple[str, ...] = (),
) -> None:
    """
    Validates result types, known statuses and the aggregate outcome counts.

    Args:
        results (tuple[ResultT, ...]): Results produced by the batch.
        result_type (type[ResultT]): Expected result class.
        summary (BatchSummary): Summary to compare with the result statuses.
        succeeded (tuple[str, ...]): Statuses counted as successful.
        failed (tuple[str, ...]): Statuses counted as failed.
        skipped (tuple[str, ...], optional): Statuses counted as skipped.
                                             Defaults to an empty tuple.
        timed_out (tuple[str, ...], optional): Statuses counted as timed out.
                                               Defaults to an empty tuple.

    Raises:
        TypeError: If results is not a tuple of the expected result type.
        ValueError: If a status is unknown or the summary is inconsistent.
    """
    # Validate results
    if not isinstance(results, tuple) or not all(
        isinstance(result, result_type) for result in results
    ):
        raise TypeError(
            f"Batch results must contain {result_type.__name__} objects."
        )

    # Validate status counts
    known = set(succeeded + failed + skipped + timed_out)
    if any(result.status not in known for result in results):
        raise ValueError("Batch result contains an unknown status.")

    # Validate summary
    expected = BatchSummary(
        total=len(results),
        succeeded=sum(result.status in succeeded for result in results),
        failed=sum(result.status in failed for result in results),
        skipped=sum(result.status in skipped for result in results),
        timed_out=sum(result.status in timed_out for result in results),
    )
    if summary != expected:
        raise ValueError("Batch summary does not match batch results.")


@dataclass(frozen=True, slots=True)
class ViewPersistenceCandidate:
    """
    One result from the view analyzer that matches the requested candidate
    score.
    """
    view: str
    space: str
    score: int | float
    business_name: str | None = None
    is_persisted: bool | None = None

    def __post_init__(self) -> None:
        """
        Validates identifiers and the analyzer score.

        Raises:
            ValueError: If an identifier is empty or the score is not finite.
        """
        _validate_text("View", self.view)
        _validate_text("Space", self.space)
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(self.score)
        ):
            raise ValueError("Candidate score must be a finite number.")


@dataclass(frozen=True, slots=True)
class FindViewPersistenceCandidatesRequest:
    """
    Input for finding persistence candidates in one analyzed view.
    """
    view: str
    space: str
    candidate_score: int | float = 10
    timeout_seconds: float = DEFAULT_VIEW_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """
        Validates identifiers, score, and analysis timeout.

        Raises:
            ValueError: If an identifier, score, or timeout is invalid.
        """
        _validate_text("View", self.view)
        _validate_text("Space", self.space)
        if (
            isinstance(self.candidate_score, bool)
            or not isinstance(self.candidate_score, (int, float))
            or not math.isfinite(self.candidate_score)
        ):
            raise ValueError("Candidate score must be a finite number.")
        _validate_timeout(self.timeout_seconds)


@dataclass(frozen=True, slots=True)
class FindViewPersistenceCandidatesResult:
    """
    Result of finding persistence candidates in one analyzed view.
    """
    view: str
    space: str
    status: FindViewPersistenceCandidatesStatus
    candidates: tuple[ViewPersistenceCandidate, ...]
    operation_id: str | None = None

    def __post_init__(self) -> None:
        """
        Validates that all candidates have the expected model type.

        Raises:
            TypeError: If candidates is not a tuple of persistence candidates.
        """
        if not isinstance(self.candidates, tuple) or not all(
            isinstance(candidate, ViewPersistenceCandidate)
            for candidate in self.candidates
        ):
            raise TypeError(
                "Candidates must contain ViewPersistenceCandidate objects."
            )


@dataclass(frozen=True, slots=True)
class FindViewPersistenceCandidatesBatchRequest:
    """
    Input for finding persistence candidates across multiple views with
    concurrency.
    """
    requests: tuple[FindViewPersistenceCandidatesRequest, ...] | None = None
    candidate_score: int | float = 10
    timeout_seconds: float = DEFAULT_VIEW_TIMEOUT_SECONDS
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates batch options and consistency of explicit requests.

        Raises:
            TypeError: If explicit requests have an invalid type.
            ValueError: If score, timeout, concurrency, or request options are
                        inconsistent.
        """
        if (
            isinstance(self.candidate_score, bool)
            or not isinstance(self.candidate_score, (int, float))
            or not math.isfinite(self.candidate_score)
        ):
            raise ValueError("Candidate score must be a finite number.")
        _validate_timeout(self.timeout_seconds)
        validate_max_concurrency(self.max_concurrency)
        if self.requests is None:
            return
        _validate_batch_requests(
            self.requests,
            FindViewPersistenceCandidatesRequest,
            self.max_concurrency,
        )
        if any(
            item.candidate_score != self.candidate_score
            or item.timeout_seconds != self.timeout_seconds
            for item in self.requests
        ):
            raise ValueError(
                "Explicit requests must match the batch candidate score and "
                "timeout."
            )


@dataclass(frozen=True, slots=True)
class FindViewPersistenceCandidatesBatchResult:
    """
    Ordered results of finding persistence candidates across multiple views in
    a batch.
    """
    results: tuple[FindViewPersistenceCandidatesResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates result statuses and the aggregate outcome counts.

        Raises:
            TypeError: If results contains an unexpected result type.
            ValueError: If a status or summary is inconsistent.
        """
        _validate_batch_result(
            self.results,
            FindViewPersistenceCandidatesResult,
            self.summary,
            succeeded=(FindViewPersistenceCandidatesStatus.COMPLETED,),
            failed=(FindViewPersistenceCandidatesStatus.FAILED,),
            timed_out=(FindViewPersistenceCandidatesStatus.TIMED_OUT,),
        )


@dataclass(frozen=True, slots=True)
class FindViewAttributeMatchesRequest:
    """
    Input for finding attributes with a specific substring in one view.
    """
    view_id: str
    view: str
    space: str
    business_name: str
    substring: str
    case_sensitive: bool = False

    def __post_init__(self) -> None:
        """
        Validates identifiers, search text, and case-sensitivity settings.

        Raises:
            ValueError: If required text is empty or case_sensitive is not a
                        boolean.
        """
        _validate_text("View ID", self.view_id)
        _validate_text("View", self.view)
        _validate_text("Space", self.space)
        _validate_text("Business name", self.business_name)
        _validate_text("Substring", self.substring)
        if not isinstance(self.case_sensitive, bool):
            raise ValueError("Case-sensitive must be a boolean.")


@dataclass(frozen=True, slots=True)
class FindViewAttributeMatchesResult:
    """
    Result of finding attributes with a specific substring in one view.
    """
    view: str
    space: str
    business_name: str
    status: FindViewAttributeMatchesStatus
    attributes: tuple[str, ...]

    def __post_init__(self) -> None:
        """
        Validates that every matching attribute is a string.

        Raises:
            TypeError: If attributes is not a tuple of strings.
        """
        if not isinstance(self.attributes, tuple) or not all(
            isinstance(attribute, str) for attribute in self.attributes
        ):
            raise TypeError("Attributes must be a tuple of strings.")


@dataclass(frozen=True, slots=True)
class FindViewAttributeMatchesBatchRequest:
    """
    Input for finding matching attributes across multiple views with
    concurrency.
    """
    substring: str
    requests: tuple[FindViewAttributeMatchesRequest, ...] | None = None
    case_sensitive: bool = False
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates search options and consistency of explicit requests.

        Raises:
            TypeError: If explicit requests have an invalid type.
            ValueError: If search, case-sensitivity, concurrency, or request
                        options are inconsistent.
        """
        _validate_text("Substring", self.substring)
        if not isinstance(self.case_sensitive, bool):
            raise ValueError("Case-sensitive must be a boolean.")
        validate_max_concurrency(self.max_concurrency)
        if self.requests is None:
            return
        _validate_batch_requests(
            self.requests,
            FindViewAttributeMatchesRequest,
            self.max_concurrency,
        )
        if any(
            item.substring != self.substring
            or item.case_sensitive != self.case_sensitive
            for item in self.requests
        ):
            raise ValueError(
                "Explicit requests must match the batch substring and "
                "case-sensitivity setting."
            )


@dataclass(frozen=True, slots=True)
class FindViewAttributeMatchesBatchResult:
    """
    Ordered results of finding matching attributes across multiple views in a
    batch.
    """
    results: tuple[FindViewAttributeMatchesResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates the batch result.

        Raises:
            TypeError: If results contains an unexpected result type.
            ValueError: If a status or summary is inconsistent.
        """
        _validate_batch_result(
            self.results,
            FindViewAttributeMatchesResult,
            self.summary,
            succeeded=(FindViewAttributeMatchesStatus.COMPLETED,),
            failed=(FindViewAttributeMatchesStatus.FAILED,),
        )


@dataclass(frozen=True, slots=True)
class CreateViewPartitioningRequest:
    """
    Input for creating a yearly partition range for one view.
    """
    view: str
    space: str
    attribute: str
    start_year: int
    end_year: int
    overwrite_existing: bool = False

    def __post_init__(self) -> None:
        """
        Validates partition identifiers, year bounds, and overwrite behavior.

        Raises:
            ValueError: If a field is invalid or the start year is not less
                        than the end year.
        """
        _validate_text("View", self.view)
        _validate_text("Space", self.space)
        _validate_text("Attribute", self.attribute)
        _validate_year("Start year", self.start_year)
        _validate_year("End year", self.end_year)
        if self.start_year >= self.end_year:
            raise ValueError("Start year must be less than end year.")
        if not isinstance(self.overwrite_existing, bool):
            raise ValueError("Overwrite-existing must be a boolean.")


@dataclass(frozen=True, slots=True)
class CreateViewPartitioningResult:
    """
    Result of creating a yearly partition range for one view.
    """
    view: str
    space: str
    status: CreateViewPartitioningStatus


@dataclass(frozen=True, slots=True)
class CreateViewPartitioningBatchRequest:
    """
    Input for creating partitions across multiple views with concurrency.
    """
    requests: tuple[CreateViewPartitioningRequest, ...]
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch request.

        Raises:
            TypeError: If requests is not a tuple of partition requests.
            ValueError: If the concurrency setting is invalid.
        """
        _validate_batch_requests(
            self.requests,
            CreateViewPartitioningRequest,
            self.max_concurrency,
        )


@dataclass(frozen=True, slots=True)
class CreateViewPartitioningBatchResult:
    """
    Ordered results of creating partitions across multiple views in a batch.
    """
    results: tuple[CreateViewPartitioningResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates the batch result.

        Raises:
            TypeError: If results contains an unexpected result type.
            ValueError: If a status or summary is inconsistent.
        """
        _validate_batch_result(
            self.results,
            CreateViewPartitioningResult,
            self.summary,
            succeeded=(CreateViewPartitioningStatus.CREATED,),
            failed=(
                CreateViewPartitioningStatus.INVALID_COLUMN,
                CreateViewPartitioningStatus.FAILED,
            ),
            skipped=(CreateViewPartitioningStatus.ALREADY_EXISTS,),
        )


@dataclass(frozen=True, slots=True)
class DeleteViewPartitioningRequest:
    """
    Input for deleting partitioning from one view.
    """
    view: str
    space: str

    def __post_init__(self) -> None:
        """
        Validates the view and space identifiers.

        Raises:
            ValueError: If the view or space identifier is empty.
        """
        _validate_text("View", self.view)
        _validate_text("Space", self.space)


@dataclass(frozen=True, slots=True)
class DeleteViewPartitioningResult:
    """
    Result of deleting partitioning from one view.
    """
    view: str
    space: str
    status: DeleteViewPartitioningStatus


@dataclass(frozen=True, slots=True)
class DeleteViewPartitioningBatchRequest:
    """
    Input for deleting partitioning across multiple views with concurrency.
    """
    requests: tuple[DeleteViewPartitioningRequest, ...]
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch request.

        Raises:
            TypeError: If requests is not a tuple of deletion requests.
            ValueError: If the concurrency setting is invalid.
        """
        _validate_batch_requests(
            self.requests,
            DeleteViewPartitioningRequest,
            self.max_concurrency,
        )


@dataclass(frozen=True, slots=True)
class DeleteViewPartitioningBatchResult:
    """
    Ordered results of deleting partitioning across multiple views in a batch.
    """
    results: tuple[DeleteViewPartitioningResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates the batch result.

        Raises:
            TypeError: If results contains an unexpected result type.
            ValueError: If a status or summary is inconsistent.
        """
        _validate_batch_result(
            self.results,
            DeleteViewPartitioningResult,
            self.summary,
            succeeded=(DeleteViewPartitioningStatus.DELETED,),
            failed=(DeleteViewPartitioningStatus.FAILED,),
        )


@dataclass(frozen=True, slots=True)
class PersistViewRequest:
    """
    Input for persisting one view.
    """
    view: str
    space: str
    timeout_seconds: float = DEFAULT_VIEW_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """
        Validates view identifiers and the persistence timeout.

        Raises:
            ValueError: If an identifier or timeout is invalid.
        """
        _validate_text("View", self.view)
        _validate_text("Space", self.space)
        _validate_timeout(self.timeout_seconds)


@dataclass(frozen=True, slots=True)
class PersistViewResult:
    """
    Result of persisting one view.
    """
    view: str
    space: str
    status: PersistViewStatus
    sap_status: str | None = None
    operation_id: str | None = None
    runtime_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class PersistViewBatchRequest:
    """
    Input for persisting multiple views with concurrency.
    """
    requests: tuple[PersistViewRequest, ...]
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch request.

        Raises:
            TypeError: If requests is not a tuple of persistence requests.
            ValueError: If the concurrency setting is invalid.
        """
        _validate_batch_requests(
            self.requests,
            PersistViewRequest,
            self.max_concurrency,
        )


@dataclass(frozen=True, slots=True)
class PersistViewBatchResult:
    """
    Ordered results for persisting multiple views in a batch.
    """
    results: tuple[PersistViewResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates the batch result.

        Raises:
            TypeError: If results contains an unexpected result type.
            ValueError: If a status or summary is inconsistent.
        """
        _validate_batch_result(
            self.results,
            PersistViewResult,
            self.summary,
            succeeded=(PersistViewStatus.COMPLETED,),
            failed=(PersistViewStatus.START_FAILED, PersistViewStatus.FAILED),
            timed_out=(PersistViewStatus.TIMED_OUT,),
        )


@dataclass(frozen=True, slots=True)
class UnpersistViewRequest:
    """
    Input for removing persisted data from one view.
    """
    view: str
    space: str
    timeout_seconds: float = DEFAULT_VIEW_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """
        Validates view identifiers and the unpersistence timeout.

        Raises:
            ValueError: If an identifier or timeout is invalid.
        """
        _validate_text("View", self.view)
        _validate_text("Space", self.space)
        _validate_timeout(self.timeout_seconds)


@dataclass(frozen=True, slots=True)
class UnpersistViewResult:
    """
    Result of removing persisted data from one view.
    """
    view: str
    space: str
    status: UnpersistViewStatus
    sap_status: str | None = None
    operation_id: str | None = None
    runtime_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class UnpersistViewBatchRequest:
    """
    Input for removing persisted data from multiple views with concurrency.
    """
    requests: tuple[UnpersistViewRequest, ...]
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch request.

        Raises:
            TypeError: If requests is not a tuple of unpersistence requests.
            ValueError: If the concurrency setting is invalid.
        """
        _validate_batch_requests(
            self.requests,
            UnpersistViewRequest,
            self.max_concurrency,
        )


@dataclass(frozen=True, slots=True)
class UnpersistViewBatchResult:
    """
    Ordered results of removing persisted data from multiple views in a batch.
    """
    results: tuple[UnpersistViewResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates the batch result.

        Raises:
            TypeError: If results contains an unexpected result type.
            ValueError: If a status or summary is inconsistent.
        """
        _validate_batch_result(
            self.results,
            UnpersistViewResult,
            self.summary,
            succeeded=(UnpersistViewStatus.COMPLETED,),
            failed=(
                UnpersistViewStatus.START_FAILED,
                UnpersistViewStatus.FAILED,
            ),
            skipped=(UnpersistViewStatus.ALREADY_ABSENT,),
            timed_out=(UnpersistViewStatus.TIMED_OUT,),
        )


@dataclass(frozen=True, slots=True)
class LockViewPartitionsRequest:
    """
    Input for locking partitions through a requested year for one view.
    """
    view: str
    space: str
    until_year: int

    def __post_init__(self) -> None:
        """
        Validates the view, space, and year parameters.

        Raises:
            ValueError: If an identifier is empty or the year is not an
                        integer.
        """
        _validate_text("View", self.view)
        _validate_text("Space", self.space)
        _validate_year("Until year", self.until_year)


@dataclass(frozen=True, slots=True)
class LockViewPartitionsResult:
    """
    Result of locking partitions through a requested year for one view.
    """
    view: str
    space: str
    status: LockViewPartitionsStatus


@dataclass(frozen=True, slots=True)
class LockViewPartitionsBatchRequest:
    """
    Input for locking partitions through requested years across multiple views
    with concurrency.
    """
    requests: tuple[LockViewPartitionsRequest, ...]
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch request.

        Raises:
            TypeError: If requests is not a tuple of lock requests.
            ValueError: If the concurrency setting is invalid.
        """
        _validate_batch_requests(
            self.requests,
            LockViewPartitionsRequest,
            self.max_concurrency,
        )


@dataclass(frozen=True, slots=True)
class LockViewPartitionsBatchResult:
    """
    Ordered results of locking partitions through requested years across
    multiple views in a batch.
    """
    results: tuple[LockViewPartitionsResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates the batch result.

        Raises:
            TypeError: If results contains an unexpected result type.
            ValueError: If a status or summary is inconsistent.
        """
        _validate_batch_result(
            self.results,
            LockViewPartitionsResult,
            self.summary,
            succeeded=(LockViewPartitionsStatus.LOCKED,),
            failed=(LockViewPartitionsStatus.FAILED,),
            skipped=(LockViewPartitionsStatus.NO_PARTITIONS,),
        )


@dataclass(frozen=True, slots=True)
class UnlockViewPartitionsRequest:
    """
    Input for unlocking all partitions of one view.
    """
    view: str
    space: str

    def __post_init__(self) -> None:
        """
        Validates the view and space identifiers.

        Raises:
            ValueError: If the view or space identifier is empty.
        """
        _validate_text("View", self.view)
        _validate_text("Space", self.space)


@dataclass(frozen=True, slots=True)
class UnlockViewPartitionsResult:
    """
    Result of unlocking all partitions of one view.
    """
    view: str
    space: str
    status: UnlockViewPartitionsStatus


@dataclass(frozen=True, slots=True)
class UnlockViewPartitionsBatchRequest:
    """
    Input for unlocking all partitions across multiple views with concurrency.
    """
    requests: tuple[UnlockViewPartitionsRequest, ...]
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch request.

        Raises:
            TypeError: If requests is not a tuple of unlock requests.
            ValueError: If the concurrency setting is invalid.
        """
        _validate_batch_requests(
            self.requests,
            UnlockViewPartitionsRequest,
            self.max_concurrency,
        )


@dataclass(frozen=True, slots=True)
class UnlockViewPartitionsBatchResult:
    """
    Ordered results of unlocking all partitions across multiple views in a
    batch.
    """
    results: tuple[UnlockViewPartitionsResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates the batch result.

        Raises:
            TypeError: If results contains an unexpected result type.
            ValueError: If a status or summary is inconsistent.
        """
        _validate_batch_result(
            self.results,
            UnlockViewPartitionsResult,
            self.summary,
            succeeded=(UnlockViewPartitionsStatus.UNLOCKED,),
            failed=(UnlockViewPartitionsStatus.FAILED,),
            skipped=(UnlockViewPartitionsStatus.NO_PARTITIONS,),
        )
