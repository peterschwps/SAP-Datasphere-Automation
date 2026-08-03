from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

from datasphere_core.models.common import (
    BatchSummary,
    CommandStatus,
    Outcome,
    validate_max_concurrency,
)

DEFAULT_ANALYTICAL_MODEL_MAX_CONCURRENCY = 10
DEFAULT_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS = 300.0
MAXIMUM_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS = 3600.0
DEFAULT_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS = 3600.0
MAXIMUM_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS = 86400.0


class AnalyticalModelDependencyStatus(StrEnum):
    """
    Resolution status of one analytical model dependency. Dependencies are
    parts of a result, not batch items, so they carry no outcome.
    """
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"


class AnalyticalModelPersistenceItemStatus(StrEnum):
    """
    Persistence measurement status of one model dependency. Dependencies are
    parts of a result, not batch items, so they carry no outcome.
    """
    COMPLETED = "completed"
    ALREADY_PERSISTED = "already_persisted"
    DEPENDENCY_NOT_FOUND = "dependency_not_found"
    PERSIST_FAILED = "persist_failed"
    PERSIST_TIMED_OUT = "persist_timed_out"
    CLEANUP_FAILED = "cleanup_failed"
    CLEANUP_TIMED_OUT = "cleanup_timed_out"


class AnalyticalModelDependenciesStatus(CommandStatus):
    """
    Result status of resolving the view dependencies of an analytical model.
    """
    COMPLETED = "completed", Outcome.SUCCEEDED
    DEPENDENCY_NOT_FOUND = "dependency_not_found", Outcome.FAILED
    ANALYTICAL_MODEL_NOT_FOUND = (
        "analytical_model_not_found",
        Outcome.SKIPPED,
    )


class AnalyticalModelPersistenceStatus(CommandStatus):
    """
    Aggregate persistence measurement status of one analytical model.
    """
    COMPLETED = "completed", Outcome.SUCCEEDED
    FAILED = "failed", Outcome.FAILED
    TIMED_OUT = "timed_out", Outcome.TIMED_OUT
    ANALYTICAL_MODEL_NOT_FOUND = (
        "analytical_model_not_found",
        Outcome.SKIPPED,
    )


def validate_timeout(timeout_seconds: float) -> None:
    """
    Validates an analytical model operation timeout. An invalid timeout would
    either fail immediately or keep the caller waiting far longer than
    intended.

    Args:
        timeout_seconds (float): Timeout of one operation in seconds.

    Raises:
        ValueError: If the timeout is not within the supported range.
    """
    maximum = MAXIMUM_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS
    if not 0 < timeout_seconds <= maximum:
        raise ValueError(
            "Timeout must be greater than zero and at most "
            f"{maximum} seconds."
        )


def validate_model_selection(
    analytical_models: tuple["AnalyticalModelReference", ...] | None,
    space: str | None,
) -> None:
    """
    Validates the analytical model selection. A space filter selects models by
    discovery, so combining it with explicit models would be ambiguous.

    Args:
        analytical_models (tuple[AnalyticalModelReference, ...] | None):
            Explicit models to process, or None for discovery.
        space (str | None): Space used for discovery, or None when explicit
                            model references are supplied.

    Raises:
        ValueError: If a space is combined with explicit model references.
    """
    if analytical_models is not None and space is not None:
        raise ValueError(
            "Space cannot be combined with explicit analytical models."
        )


@dataclass(frozen=True, slots=True)
class AnalyticalModelReference:
    """
    Reference to one analytical model.
    """
    name: str
    space: str


@dataclass(frozen=True, slots=True)
class AnalyticalModelViewDependency:
    """
    View dependency of an analytical model. The space is only known for
    resolved dependencies.
    """
    view_id: str
    view_name: str
    space: str | None
    status: AnalyticalModelDependencyStatus


@dataclass(frozen=True, slots=True)
class GetAnalyticalModelViewDependenciesRequest:
    """
    Input for resolving one analytical model's view dependencies.
    """
    analytical_model_name: str
    space: str


@dataclass(frozen=True, slots=True)
class GetAnalyticalModelViewDependenciesResult:
    """
    Result of resolving one analytical model's view dependencies.
    """
    analytical_model_name: str
    space: str
    status: AnalyticalModelDependenciesStatus
    analytical_model_id: str | None = None
    dependencies: tuple[AnalyticalModelViewDependency, ...] = ()


@dataclass(frozen=True, slots=True)
class GetAnalyticalModelViewDependenciesBatchRequest:
    """
    Input for resolving the view dependencies of all analytical models or of a
    selected set of analytical models.
    """
    analytical_models: tuple[AnalyticalModelReference, ...] | None = None
    space: str | None = None
    deduplicate_views: bool = False
    max_concurrency: int = DEFAULT_ANALYTICAL_MODEL_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the model selection and the batch concurrency limit.

        Raises:
            ValueError: If a space is combined with explicit analytical models
                        or the concurrency limit is not within the supported
                        range.
        """
        validate_model_selection(self.analytical_models, self.space)
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class GetAnalyticalModelViewDependenciesBatchResult:
    """
    Ordered results of resolving the view dependencies of analytical models in
    a batch.
    """
    results: tuple[GetAnalyticalModelViewDependenciesResult, ...]
    summary: BatchSummary


@dataclass(frozen=True, slots=True)
class MeasureAnalyticalModelViewPersistenceRequest:
    """
    Input for measuring the persistence runtime of all view dependencies of one
    analytical model.
    """
    analytical_model_name: str
    space: str
    timeout_seconds: float = (
        DEFAULT_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS
    )
    max_concurrency: int = DEFAULT_ANALYTICAL_MODEL_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the persistence timeout and the concurrency limit.

        Raises:
            ValueError: If the timeout or the concurrency limit is not within
                        the supported range.
        """
        validate_timeout(self.timeout_seconds)
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class MeasureAnalyticalModelViewPersistenceItemResult:
    """
    Result of measuring the persistence runtime of one view as a dependency of
    an analytical model.
    """
    view_id: str
    view_name: str
    space: str | None
    status: AnalyticalModelPersistenceItemStatus
    previously_persisted: bool | None = None
    runtime_seconds: int | None = None
    persistence_log_status: str | None = None
    persistence_log_id: str | None = None
    cleanup_log_status: str | None = None
    cleanup_log_id: str | None = None
    persistence_removed: bool | None = None
    manual_intervention: bool = False


@dataclass(frozen=True, slots=True)
class MeasureAnalyticalModelViewPersistenceResult:
    """
    Result of measuring the persistence runtime of all view dependencies of one
    analytical model.
    """
    analytical_model_name: str
    space: str
    status: AnalyticalModelPersistenceStatus
    analytical_model_id: str | None = None
    dependencies: tuple[
        MeasureAnalyticalModelViewPersistenceItemResult, ...
    ] = ()


@dataclass(frozen=True, slots=True)
class MeasureAnalyticalModelViewPersistenceBatchRequest:
    """
    Input for measuring the persistence runtime of all view dependencies of all
    or selected analytical models with concurrency.
    """
    analytical_models: tuple[AnalyticalModelReference, ...] | None = None
    space: str | None = None
    timeout_seconds: float = (
        DEFAULT_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS
    )
    max_concurrency: int = DEFAULT_ANALYTICAL_MODEL_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the model selection, the persistence timeout, and the batch
        concurrency limit.

        Raises:
            ValueError: If a space is combined with explicit analytical models
                        or the timeout or concurrency limit is not within the
                        supported range.
        """
        validate_model_selection(self.analytical_models, self.space)
        validate_timeout(self.timeout_seconds)
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class MeasureAnalyticalModelViewPersistenceBatchResult:
    """
    Ordered results of measuring the persistence runtime of the view
    dependencies of analytical models in a batch.
    """
    results: tuple[MeasureAnalyticalModelViewPersistenceResult, ...]
    summary: BatchSummary


# Full analytical model details as returned by the repository search
# (as of 13.07.2025)
AnalyticalModelsDetailsDict = TypedDict(
    "AnalyticalModelsDetailsDict",
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
        "is_shared": None,
        "is_shared_tag": None,
        "kind": str,
        "last_accessed": str | None,
        "last_accessed_globally": str | None,
        "modification_date": str,
        "name": str,
        "object_status": str,
        "object_status_description": str,
        "object_status_icon": str,
        "release_date": None,
        "release_state": None,
        "release_state_description": None,
        "release_state_icon": None,
        "remote_connection": None,
        "remote_connection_type": None,
        "remote_connection_type_description": None,
        "remote_entity": None,
        "repository_package": None,
        "repository_package_name": None,
        "space_description": str,
        "space_id": str,
        "space_name": str,
        "space_permission_user_is_member_in_source_space_id": str,
        "space_type": None,
        "technical_type": str,
        "technical_type_description": str,
        "technical_type_icon": str,
        "user_is_member_in_source_space_id": str,
        "business_purpose_entHierarchies": list[dict],
    },
)
