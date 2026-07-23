import math
from dataclasses import dataclass
from enum import StrEnum

from datasphere_core.models.common import (
    BatchSummary,
    validate_max_concurrency,
)

DEFAULT_ANALYTICAL_MODEL_MAX_CONCURRENCY = 10
DEFAULT_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS = 300.0
MAXIMUM_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS = 3600.0
DEFAULT_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS = 3600.0
MAXIMUM_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS = 86400.0


class AnalyticalModelDependencyStatus(StrEnum):
    """
    Resolution status of one analytical model dependency.
    """
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"


class AnalyticalModelDependenciesStatus(StrEnum):
    """
    Result status of resolving analytical model dependencies.
    """
    COMPLETED = "completed"
    DEPENDENCY_NOT_FOUND = "dependency_not_found"
    ANALYTICAL_MODEL_NOT_FOUND = "analytical_model_not_found"


class AnalyticalModelPersistenceItemStatus(StrEnum):
    """
    Persistence measurement status of one model dependency.
    """
    COMPLETED = "completed"
    ALREADY_PERSISTED = "already_persisted"
    DEPENDENCY_NOT_FOUND = "dependency_not_found"
    PERSIST_FAILED = "persist_failed"
    PERSIST_TIMED_OUT = "persist_timed_out"
    CLEANUP_FAILED = "cleanup_failed"
    CLEANUP_TIMED_OUT = "cleanup_timed_out"


class AnalyticalModelPersistenceStatus(StrEnum):
    """
    Aggregate persistence measurement status of one analytical model.
    """
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ANALYTICAL_MODEL_NOT_FOUND = "analytical_model_not_found"


_DEPENDENCY_STATUSES = {
    AnalyticalModelDependencyStatus.RESOLVED,
    AnalyticalModelDependencyStatus.NOT_FOUND,
}
_DEPENDENCIES_STATUSES = {
    AnalyticalModelDependenciesStatus.COMPLETED,
    AnalyticalModelDependenciesStatus.DEPENDENCY_NOT_FOUND,
    AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND,
}
_PERSISTENCE_ITEM_STATUSES = {
    AnalyticalModelPersistenceItemStatus.COMPLETED,
    AnalyticalModelPersistenceItemStatus.ALREADY_PERSISTED,
    AnalyticalModelPersistenceItemStatus.DEPENDENCY_NOT_FOUND,
    AnalyticalModelPersistenceItemStatus.PERSIST_FAILED,
    AnalyticalModelPersistenceItemStatus.PERSIST_TIMED_OUT,
    AnalyticalModelPersistenceItemStatus.CLEANUP_FAILED,
    AnalyticalModelPersistenceItemStatus.CLEANUP_TIMED_OUT,
}
_PERSISTENCE_STATUSES = {
    AnalyticalModelPersistenceStatus.COMPLETED,
    AnalyticalModelPersistenceStatus.FAILED,
    AnalyticalModelPersistenceStatus.TIMED_OUT,
    AnalyticalModelPersistenceStatus.ANALYTICAL_MODEL_NOT_FOUND,
}


def _validate_non_empty(value: str, field: str) -> None:
    """
    Validates that a required text value is not empty.

    Args:
        value (str): Text value to validate.
        field (str): Human-readable field name for validation errors.

    Raises:
        ValueError: If the value is not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty.")


def _validate_optional_non_empty(value: str | None, field: str) -> None:
    """
    Validates an optional text value when it is present.

    Args:
        value (str | None): Optional text value to validate.
        field (str): Human-readable field name for validation errors.

    Raises:
        ValueError: If a present value is not a non-empty string.
    """
    if value is not None:
        _validate_non_empty(value, field)


def _validate_timeout(timeout_seconds: float) -> None:
    """
    Validates an analytical model operation timeout.

    Args:
        timeout_seconds (float): Positive finite timeout in seconds.

    Raises:
        ValueError: If the timeout is not positive, infinite, or not within the
                    supported maximum.
    """
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds
        <= MAXIMUM_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "Timeout must be greater than zero and at most "
            f"{MAXIMUM_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS} "
            "seconds."
        )


def _validate_model_selection(
    analytical_models: tuple["AnalyticalModelReference", ...] | None,
    space: str | None,
) -> None:
    """
    Validates the analytical model selection. Either the analytical_model or
    the space needs to be None.

    Args:
        analytical_models (tuple[AnalyticalModelReference, ...] | None):
            Explicit models to process, or None for discovery.
        space (str | None): Space used for discovery, or None when explicit
                            model references are supplied.

    Raises:
        TypeError: If explicit models are not a tuple of model references.
        ValueError: If a space is combined with explicit model references or
                    an identifier is empty.
    """
    _validate_optional_non_empty(space, "Space")
    if analytical_models is None:
        return
    if space is not None:
        raise ValueError(
            "Space cannot be combined with explicit analytical models."
        )
    if not isinstance(analytical_models, tuple) or not all(
        isinstance(model, AnalyticalModelReference)
        for model in analytical_models
    ):
        raise TypeError(
            "Analytical models must be a tuple of AnalyticalModelReference "
            "objects."
        )


@dataclass(frozen=True, slots=True)
class AnalyticalModelReference:
    """
    Reference to one analytical model.
    """
    analytical_model_name: str
    space: str

    def __post_init__(self) -> None:
        """
        Validates the analytical model name and space.

        Raises:
            ValueError: If either identifier is empty.
        """
        _validate_non_empty(
            self.analytical_model_name, "Analytical model name"
        )
        _validate_non_empty(self.space, "Space")


@dataclass(frozen=True, slots=True)
class AnalyticalModelViewDependency:
    """
    View dependency of an analytical model.
    """
    view_id: str
    view_name: str
    space: str | None
    status: AnalyticalModelDependencyStatus

    def __post_init__(self) -> None:
        """
        Validates the supplied attributes..

        Raises:
            ValueError: If an identifier is empty, the status is unknown, or
                        the status does not agree with the space value.
        """
        _validate_non_empty(self.view_id, "View ID")
        _validate_non_empty(self.view_name, "View name")
        _validate_optional_non_empty(self.space, "Space")
        if self.status not in _DEPENDENCY_STATUSES:
            raise ValueError(f"Invalid dependency status: {self.status!r}.")
        if (self.status is AnalyticalModelDependencyStatus.RESOLVED) != (
            self.space is not None
        ):
            raise ValueError(
                "Resolved dependencies require a space and unresolved "
                "dependencies must not have one."
            )


@dataclass(frozen=True, slots=True)
class GetAnalyticalModelViewDependenciesRequest:
    """
    Input for resolving one analytical model's view dependencies.
    """
    analytical_model_name: str
    space: str

    def __post_init__(self) -> None:
        """
        Validates the analytical model name and space.

        Raises:
            ValueError: If either identifier is empty.
        """
        _validate_non_empty(
            self.analytical_model_name, "Analytical model name"
        )
        _validate_non_empty(self.space, "Space")


@dataclass(frozen=True, slots=True)
class GetAnalyticalModelViewDependenciesResult:
    """
    Result of resolving one analytical models's view dependencies.
    """
    analytical_model_name: str
    space: str
    status: AnalyticalModelDependenciesStatus
    analytical_model_id: str | None = None
    dependencies: tuple[AnalyticalModelViewDependency, ...] = ()

    def __post_init__(self) -> None:
        """
        Validates dependency result types and status-dependent invariants.

        Raises:
            TypeError: If dependencies is not a tuple of dependency objects.
            ValueError: If identifiers, status, model ID, or dependency
                        outcomes are inconsistent.
        """
        _validate_non_empty(
            self.analytical_model_name, "Analytical model name"
        )
        _validate_non_empty(self.space, "Space")
        _validate_optional_non_empty(
            self.analytical_model_id, "Analytical model ID"
        )
        if self.status not in _DEPENDENCIES_STATUSES:
            raise ValueError(
                f"Invalid analytical model dependency status: {self.status!r}."
            )
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(item, AnalyticalModelViewDependency)
            for item in self.dependencies
        ):
            raise TypeError(
                "Dependencies must be a tuple of "
                "AnalyticalModelViewDependency objects."
            )
        if self.status is (
            AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND
        ):
            if self.analytical_model_id is not None or self.dependencies:
                raise ValueError(
                    "A missing analytical model cannot have an ID or "
                    "dependencies."
                )
            return
        if self.analytical_model_id is None:
            raise ValueError("A resolved analytical model requires an ID.")
        has_missing = any(
            dependency.status is AnalyticalModelDependencyStatus.NOT_FOUND
            for dependency in self.dependencies
        )
        if (
            self.status
            is AnalyticalModelDependenciesStatus.DEPENDENCY_NOT_FOUND
        ) != has_missing:
            raise ValueError(
                "Dependency status does not match the dependency results."
            )


@dataclass(frozen=True, slots=True)
class GetAnalyticalModelViewDependenciesBatchRequest:
    """
    Input for resolving view dependencies of all analytical models or selected
    analytical models.
    """
    analytical_models: tuple[AnalyticalModelReference, ...] | None = None
    space: str | None = None
    deduplicate_views: bool = False
    max_concurrency: int = DEFAULT_ANALYTICAL_MODEL_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates selection, deduplication, and concurrency options.

        Raises:
            TypeError: If explicit models are not correctly typed or
                       deduplicate_views is not boolean.
            ValueError: If selection or concurrency settings are invalid.
        """
        _validate_model_selection(self.analytical_models, self.space)
        if not isinstance(self.deduplicate_views, bool):
            raise TypeError("Deduplicate views must be a boolean.")
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class GetAnalyticalModelViewDependenciesBatchResult:
    """
    Ordered results of resolving view dependencies of all analytical models or
    selected analytical models in a batch.
    """
    results: tuple[GetAnalyticalModelViewDependenciesResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates result types and the aggregate outcome counts.

        Raises:
            TypeError: If results is not a tuple of dependency results.
            ValueError: If the summary does not match the result statuses.
        """
        if not isinstance(self.results, tuple) or not all(
            isinstance(item, GetAnalyticalModelViewDependenciesResult)
            for item in self.results
        ):
            raise TypeError(
                "Batch results must contain dependency result objects."
            )
        expected = BatchSummary(
            total=len(self.results),
            succeeded=sum(
                result.status is AnalyticalModelDependenciesStatus.COMPLETED
                for result in self.results
            ),
            failed=sum(
                result.status
                is AnalyticalModelDependenciesStatus.DEPENDENCY_NOT_FOUND
                for result in self.results
            ),
            skipped=sum(
                result.status
                is AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND
                for result in self.results
            ),
            timed_out=0,
        )
        if self.summary != expected:
            raise ValueError("Batch summary does not match batch results.")


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
        Validates model identifiers, timeout, and concurrency.

        Raises:
            ValueError: If an identifier or timeout is invalid.
        """
        _validate_non_empty(
            self.analytical_model_name, "Analytical model name"
        )
        _validate_non_empty(self.space, "Space")
        _validate_timeout(self.timeout_seconds)
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
    persistence_sap_status: str | None = None
    persistence_operation_id: str | None = None
    cleanup_sap_status: str | None = None
    cleanup_operation_id: str | None = None
    persistence_removed: bool | None = None
    manual_intervention: bool = False

    def __post_init__(self) -> None:
        """
        Validates the persistence result and status-specific invariants.

        Raises:
            TypeError: If a boolean field has an invalid type.
            ValueError: If identifiers, status, runtime, or cleanup metadata
                        are inconsistent.
        """
        # Validate non-empty and optional strings
        _validate_non_empty(self.view_id, "View ID")
        _validate_non_empty(self.view_name, "View name")
        _validate_optional_non_empty(self.space, "Space")
        for value, field in (
            (self.persistence_sap_status, "Persistence SAP status"),
            (self.persistence_operation_id, "Persistence operation ID"),
            (self.cleanup_sap_status, "Cleanup SAP status"),
            (self.cleanup_operation_id, "Cleanup operation ID"),
        ):
            _validate_optional_non_empty(value, field)

        # Validate correct status
        if self.status not in _PERSISTENCE_ITEM_STATUSES:
            raise ValueError(
                f"Invalid persistence item status: {self.status!r}."
            )

        # Validate type of all (possibly) boolean values
        for field, value in (
            ("Previously persisted", self.previously_persisted),
            ("Persistence removed", self.persistence_removed),
            ("Manual intervention", self.manual_intervention),
        ):
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{field} must be a boolean or None.")

        # Validate runtime
        if self.runtime_seconds is not None and (
            isinstance(self.runtime_seconds, bool)
            or not isinstance(self.runtime_seconds, int)
            or self.runtime_seconds < 0
        ):
            raise ValueError(
                "Runtime seconds must be a non-negative integer or None."
            )

        # Validate special cases
        if self.status is (
            AnalyticalModelPersistenceItemStatus.DEPENDENCY_NOT_FOUND
        ):
            if self.space is not None or self.previously_persisted is not None:
                raise ValueError(
                    "An unresolved dependency cannot have persistence data."
                )
            return
        if self.space is None or self.previously_persisted is None:
            raise ValueError(
                "Measured dependencies require a space and prior state."
            )
        if (
            self.status is AnalyticalModelPersistenceItemStatus.COMPLETED
            and self.persistence_removed is not True
        ):
            raise ValueError(
                "Completed temporary persistence must have been removed."
            )
        if self.status is (
            AnalyticalModelPersistenceItemStatus.ALREADY_PERSISTED
        ) and (
            not self.previously_persisted
            or self.persistence_removed is not False
        ):
            raise ValueError(
                "Already-persisted results require prior persistence and "
                "must not report removal."
            )
        if self.status in {
            AnalyticalModelPersistenceItemStatus.CLEANUP_FAILED,
            AnalyticalModelPersistenceItemStatus.CLEANUP_TIMED_OUT,
        } and (
            self.persistence_removed is not False
            or not self.manual_intervention
        ):
            raise ValueError(
                "Cleanup failures require manual intervention and must "
                "report that persistence was not removed."
            )


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

    def __post_init__(self) -> None:
        """
        Validates result types and status-dependent persistence invariants.

        Raises:
            TypeError: If dependencies is not a tuple of persistence results.
            ValueError: If identifiers, status, model ID, or dependency
                        outcomes are inconsistent.
        """
        # Validate non-empty and optional strings
        _validate_non_empty(
            self.analytical_model_name, "Analytical model name"
        )
        _validate_non_empty(self.space, "Space")
        _validate_optional_non_empty(
            self.analytical_model_id, "Analytical model ID"
        )

        # Validate correct status
        if self.status not in _PERSISTENCE_STATUSES:
            raise ValueError(
                f"Invalid persistence measurement status: {self.status!r}."
            )

        # Validate type of dependencies
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(item, MeasureAnalyticalModelViewPersistenceItemResult)
            for item in self.dependencies
        ):
            raise TypeError(
                "Dependencies must be a tuple of persistence item results."
            )

        # Validate special cases
        if self.status is (
            AnalyticalModelPersistenceStatus.ANALYTICAL_MODEL_NOT_FOUND
        ):
            if self.analytical_model_id is not None or self.dependencies:
                raise ValueError(
                    "A missing analytical model cannot have measurement data."
                )
            return
        if self.analytical_model_id is None:
            raise ValueError("A measured analytical model requires an ID.")

        # Validate expected status
        if any(
            item.status
            in {
                AnalyticalModelPersistenceItemStatus.PERSIST_TIMED_OUT,
                AnalyticalModelPersistenceItemStatus.CLEANUP_TIMED_OUT,
            }
            for item in self.dependencies
        ):
            expected = AnalyticalModelPersistenceStatus.TIMED_OUT
        elif any(
            item.status
            not in {
                AnalyticalModelPersistenceItemStatus.COMPLETED,
                AnalyticalModelPersistenceItemStatus.ALREADY_PERSISTED,
            }
            for item in self.dependencies
        ):
            expected = AnalyticalModelPersistenceStatus.FAILED
        else:
            expected = AnalyticalModelPersistenceStatus.COMPLETED

        if self.status != expected:
            raise ValueError(
                "Persistence status does not match dependency outcomes."
            )


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
        Validates selection, timeout, and concurrency options.

        Raises:
            ValueError: If selection, timeout, or concurrency settings are
                        invalid.
        """
        _validate_model_selection(self.analytical_models, self.space)
        _validate_timeout(self.timeout_seconds)
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class MeasureAnalyticalModelViewPersistenceBatchResult:
    """
    Ordered results of measuring the persistence runtime of all view
    dependencies of all or selected analytical models in a batch.
    """
    results: tuple[MeasureAnalyticalModelViewPersistenceResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates result types and the aggregate outcome counts.

        Raises:
            TypeError: If results is not a tuple of persistence results.
            ValueError: If the summary does not match the result statuses.
        """
        if not isinstance(self.results, tuple) or not all(
            isinstance(item, MeasureAnalyticalModelViewPersistenceResult)
            for item in self.results
        ):
            raise TypeError(
                "Batch results must contain persistence measurement results."
            )
        expected = BatchSummary(
            total=len(self.results),
            succeeded=sum(
                result.status is AnalyticalModelPersistenceStatus.COMPLETED
                for result in self.results
            ),
            failed=sum(
                result.status is AnalyticalModelPersistenceStatus.FAILED
                for result in self.results
            ),
            skipped=sum(
                result.status
                is AnalyticalModelPersistenceStatus.ANALYTICAL_MODEL_NOT_FOUND
                for result in self.results
            ),
            timed_out=sum(
                result.status is AnalyticalModelPersistenceStatus.TIMED_OUT
                for result in self.results
            ),
        )
        if self.summary != expected:
            raise ValueError("Batch summary does not match batch results.")
