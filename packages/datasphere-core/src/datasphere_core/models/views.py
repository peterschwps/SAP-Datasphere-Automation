from dataclasses import dataclass
from typing import TypedDict

from datasphere_core.models.common import (
    BatchSummary,
    CommandStatus,
    Outcome,
    validate_max_concurrency,
    validate_timeout,
)

DEFAULT_VIEW_TIMEOUT_SECONDS = 3600.0
MAXIMUM_VIEW_TIMEOUT_SECONDS = 86400.0
DEFAULT_VIEW_MAX_CONCURRENCY = 10


class FindViewPersistenceCandidatesStatus(CommandStatus):
    """
    Result status of finding persistence candidates using the view analyzer.
    """
    COMPLETED = "completed", Outcome.SUCCEEDED
    FAILED = "failed", Outcome.FAILED
    TIMED_OUT = "timed_out", Outcome.TIMED_OUT


class FindViewAttributeMatchesStatus(CommandStatus):
    """
    Result status of finding matching view attributes.
    """
    COMPLETED = "completed", Outcome.SUCCEEDED
    FAILED = "failed", Outcome.FAILED


class CreateViewPartitioningStatus(CommandStatus):
    """
    Result status of creating view partitioning.
    """
    CREATED = "created", Outcome.SUCCEEDED
    ALREADY_EXISTS = "already_exists", Outcome.SKIPPED
    INVALID_COLUMN = "invalid_column", Outcome.FAILED
    FAILED = "failed", Outcome.FAILED


class DeleteViewPartitioningStatus(CommandStatus):
    """
    Result status of deleting view partitioning.
    """
    DELETED = "deleted", Outcome.SUCCEEDED
    FAILED = "failed", Outcome.FAILED


class PersistViewStatus(CommandStatus):
    """
    Result status of persisting a view.
    """
    COMPLETED = "completed", Outcome.SUCCEEDED
    START_FAILED = "start_failed", Outcome.FAILED
    FAILED = "failed", Outcome.FAILED
    TIMED_OUT = "timed_out", Outcome.TIMED_OUT


class UnpersistViewStatus(CommandStatus):
    """
    Result status of removing persisted view data.
    """
    COMPLETED = "completed", Outcome.SUCCEEDED
    ALREADY_ABSENT = "already_absent", Outcome.SKIPPED
    START_FAILED = "start_failed", Outcome.FAILED
    FAILED = "failed", Outcome.FAILED
    TIMED_OUT = "timed_out", Outcome.TIMED_OUT


class LockViewPartitionsStatus(CommandStatus):
    """
    Result status of locking view partitions.
    """
    LOCKED = "locked", Outcome.SUCCEEDED
    NO_PARTITIONS = "no_partitions", Outcome.SKIPPED
    FAILED = "failed", Outcome.FAILED


class UnlockViewPartitionsStatus(CommandStatus):
    """
    Result status of unlocking view partitions.
    """
    UNLOCKED = "unlocked", Outcome.SUCCEEDED
    NO_PARTITIONS = "no_partitions", Outcome.SKIPPED
    FAILED = "failed", Outcome.FAILED


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


@dataclass(frozen=True, slots=True)
class FindViewPersistenceCandidatesRequest:
    """
    Input for finding persistence candidates in one analyzed view.
    """
    view: str
    space: str
    minimum_candidate_score: int | float = 10
    timeout_seconds: float = DEFAULT_VIEW_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """
        Validates the analysis timeout.

        Raises:
            ValueError: If the timeout is not within the supported range.
        """
        validate_timeout(
            self.timeout_seconds,
            MAXIMUM_VIEW_TIMEOUT_SECONDS,
        )


@dataclass(frozen=True, slots=True)
class FindViewPersistenceCandidatesResult:
    """
    Result of finding persistence candidates in one analyzed view.
    """
    view: str
    space: str
    status: FindViewPersistenceCandidatesStatus
    candidates: tuple[ViewPersistenceCandidate, ...]
    log_id: str | None = None


@dataclass(frozen=True, slots=True)
class FindViewPersistenceCandidatesBatchRequest:
    """
    Input for finding persistence candidates across multiple views with
    concurrency. Analyzes every view of the tenant if no explicit requests are
    supplied.
    """
    requests: tuple[FindViewPersistenceCandidatesRequest, ...] | None = None
    minimum_candidate_score: int | float = 10
    timeout_seconds: float = DEFAULT_VIEW_TIMEOUT_SECONDS
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the analysis timeout and the batch concurrency limit.

        Raises:
            ValueError: If the timeout or the concurrency limit is not within
                        the supported range.
        """
        validate_timeout(
            self.timeout_seconds,
            MAXIMUM_VIEW_TIMEOUT_SECONDS,
        )
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class FindViewPersistenceCandidatesBatchResult:
    """
    Ordered results of finding persistence candidates across multiple views in
    a batch.
    """
    results: tuple[FindViewPersistenceCandidatesResult, ...]
    summary: BatchSummary


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


@dataclass(frozen=True, slots=True)
class FindViewAttributeMatchesBatchRequest:
    """
    Input for finding matching attributes across multiple views with
    concurrency. Searches every view of the tenant if no explicit requests are
    supplied.
    """
    substring: str
    requests: tuple[FindViewAttributeMatchesRequest, ...] | None = None
    case_sensitive: bool = False
    max_concurrency: int = DEFAULT_VIEW_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is not within the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class FindViewAttributeMatchesBatchResult:
    """
    Ordered results of finding matching attributes across multiple views in a
    batch.
    """
    results: tuple[FindViewAttributeMatchesResult, ...]
    summary: BatchSummary


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
        Validates the partition year bounds. An inverted range would silently
        create no partitions at all.

        Raises:
            ValueError: If the start year is not less than the end year.
        """
        if self.start_year >= self.end_year:
            raise ValueError("Start year must be less than end year.")


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
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is not within the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class CreateViewPartitioningBatchResult:
    """
    Ordered results of creating partitions across multiple views in a batch.
    """
    results: tuple[CreateViewPartitioningResult, ...]
    summary: BatchSummary


@dataclass(frozen=True, slots=True)
class DeleteViewPartitioningRequest:
    """
    Input for deleting partitioning from one view.
    """
    view: str
    space: str


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
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is not within the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class DeleteViewPartitioningBatchResult:
    """
    Ordered results of deleting partitioning across multiple views in a batch.
    """
    results: tuple[DeleteViewPartitioningResult, ...]
    summary: BatchSummary


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
        Validates the persistence timeout.

        Raises:
            ValueError: If the timeout is not within the supported range.
        """
        validate_timeout(
            self.timeout_seconds,
            MAXIMUM_VIEW_TIMEOUT_SECONDS,
        )


@dataclass(frozen=True, slots=True)
class PersistViewResult:
    """
    Result of persisting one view.
    """
    view: str
    space: str
    status: PersistViewStatus
    log_status: str | None = None
    log_id: str | None = None
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
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is not within the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class PersistViewBatchResult:
    """
    Ordered results for persisting multiple views in a batch.
    """
    results: tuple[PersistViewResult, ...]
    summary: BatchSummary


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
        Validates the unpersistence timeout.

        Raises:
            ValueError: If the timeout is not within the supported range.
        """
        validate_timeout(
            self.timeout_seconds,
            MAXIMUM_VIEW_TIMEOUT_SECONDS,
        )


@dataclass(frozen=True, slots=True)
class UnpersistViewResult:
    """
    Result of removing persisted data from one view.
    """
    view: str
    space: str
    status: UnpersistViewStatus
    log_status: str | None = None
    log_id: str | None = None
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
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is not within the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class UnpersistViewBatchResult:
    """
    Ordered results of removing persisted data from multiple views in a batch.
    """
    results: tuple[UnpersistViewResult, ...]
    summary: BatchSummary


@dataclass(frozen=True, slots=True)
class LockViewPartitionsRequest:
    """
    Input for locking partitions through a requested year for one view.
    """
    view: str
    space: str
    until_year: int


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
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is not within the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class LockViewPartitionsBatchResult:
    """
    Ordered results of locking partitions through requested years across
    multiple views in a batch.
    """
    results: tuple[LockViewPartitionsResult, ...]
    summary: BatchSummary


@dataclass(frozen=True, slots=True)
class UnlockViewPartitionsRequest:
    """
    Input for unlocking all partitions of one view.
    """
    view: str
    space: str


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
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is not within the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class UnlockViewPartitionsBatchResult:
    """
    Ordered results of unlocking all partitions across multiple views in a
    batch.
    """
    results: tuple[UnlockViewPartitionsResult, ...]
    summary: BatchSummary


# Full view details as returned by the repository search
# (as of 10.07.2025)
ViewDetailsDict = TypedDict(
    "ViewDetailsDict",
    {
        "@com.sap.vocabularies.Search.v1.Ranking": int | float,
        "@com.sap.vocabularies.Search.v1.WhyFound": dict,
        "@odata.context": str,
        "business_name": str,
        "business_purpose_purpose": None,
        "business_type": str,
        "business_type_description": str,
        "business_type_icon": str,
        "capabilities_list": None,
        "changed_by_user_name": str | None,
        "creation_date": str,
        "creator_user_name": str | None,
        "decommissioning_date": None,
        "deployment_date": str | None,
        "deployment_folder_id": None,
        "deployment_folder_id_ext": None,
        "deployment_folder_name": None,
        "deployment_name": None,
        "deployment_status": str,
        "deployment_status_description": str,
        "deployment_status_icon": str,
        "deprecation_date": None,
        "description": None,
        "exposed_for_consumption": str,
        "exposed_for_consumption_id": str,
        "favorites_user_id": None,
        "folder_icon": str | None,
        "folder_id": str | None,
        "folder_id_ext": str | None,
        "folder_name": str | None,
        "id": str,
        "is_shared": str | None,
        "is_shared_tag": str | None,
        "kind": str,
        "last_accessed": str | None,
        "last_accessed_globally": str | None,
        "modification_date": str,
        "name": str,
        "object_status": str,
        "object_status_description": str,
        "object_status_icon": str,
        "release_date": str | None,
        "release_state": str,
        "release_state_description": str,
        "release_state_icon": str,
        "remote_connection": None,
        "remote_connection_type": None,
        "remote_connection_type_description": None,
        "remote_entity": None,
        "repository_package": str | None,
        "repository_package_name": str | None,
        "space_description": str,
        "space_id": str,
        "space_name": str,
        "space_permission_user_is_member_in_source_space_id": str,
        "space_type": None,
        "technical_type": str,
        "technical_type_description": str,
        "technical_type_icon": str,
        "user_is_member_in_source_space_id": str,
        "business_purpose_description@com.sap.vocabularies.Search.v1.Snippets": str | None,  # noqa: E501
        "@com.sap.vocabularies.Search.v1.ParentHierarchies": list[dict],
    },
)
