from dataclasses import dataclass
from enum import StrEnum

from datasphere_core.models.common import (
    BatchSummary,
    validate_max_concurrency,
)

DEFAULT_REMOTE_TABLE_MAX_CONCURRENCY = 10


class StatisticsType(StrEnum):
    """
    Possible statistics types for remote tables.
    """
    RECORD_COUNT = "RECORD_COUNT"
    SIMPLE = "SIMPLE"
    HISTOGRAM = "HISTOGRAM"


class ConfigureRemoteTableStatisticsStatus(StrEnum):
    """
    Result status of configuring remote tables statistics.
    """
    CREATED = "created"
    UPDATED = "updated"
    ALREADY_CONFIGURED = "already_configured"
    UNSUPPORTED = "unsupported"
    UNSUPPORTED_TYPE = "unsupported_type"
    ALREADY_EXISTS = "already_exists"
    FAILED = "failed"


class RefreshRemoteTableStatisticsStatus(StrEnum):
    """
    Result status of refreshing remote table statistics.
    """
    REFRESHED = "refreshed"
    NO_STATISTICS = "no_statistics"
    UNSUPPORTED = "unsupported"
    TABLE_NOT_FOUND = "table_not_found"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConfigureRemoteTableStatisticsRequest:
    """
    Input for configuring one remote table's statistics.
    """
    table: str
    space: str
    statistics_type: StatisticsType


@dataclass(frozen=True, slots=True)
class ConfigureRemoteTableStatisticsResult:
    """
    Result of configuring one remote table's statistics.
    """
    table: str
    space: str
    statistics_type: StatisticsType
    status: ConfigureRemoteTableStatisticsStatus


@dataclass(frozen=True, slots=True)
class ConfigureRemoteTableStatisticsBatchRequest:
    """
    Input for configuring remote table statistics with concurrency.
    """
    tables: tuple[str, ...] | None
    space: str
    statistics_type: StatisticsType
    max_concurrency: int = DEFAULT_REMOTE_TABLE_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is invalid.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class ConfigureRemoteTableStatisticsBatchResult:
    """
    Ordered results of configuring remote table statistics in a batch.
    """
    results: tuple[ConfigureRemoteTableStatisticsResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates result types and the exact remote table outcome categories.

        Raises:
            TypeError: If results is not a tuple of
                       ConfigureRemoteTableStatisticsResult.
            ValueError: If the summary does not match the result statuses.
        """
        if not isinstance(self.results, tuple) or not all(
            isinstance(result, ConfigureRemoteTableStatisticsResult)
            for result in self.results
        ):
            raise TypeError(
                "Batch results must contain "
                "ConfigureRemoteTableStatisticsResult objects."
            )
        expected = BatchSummary(
            total=len(self.results),
            succeeded=sum(
                result.status
                in (
                    ConfigureRemoteTableStatisticsStatus.CREATED,
                    ConfigureRemoteTableStatisticsStatus.UPDATED,
                    ConfigureRemoteTableStatisticsStatus.ALREADY_CONFIGURED,
                    ConfigureRemoteTableStatisticsStatus.ALREADY_EXISTS,
                )
                for result in self.results
            ),
            failed=sum(
                result.status is ConfigureRemoteTableStatisticsStatus.FAILED
                for result in self.results
            ),
            skipped=sum(
                result.status
                in (
                    ConfigureRemoteTableStatisticsStatus.UNSUPPORTED,
                    ConfigureRemoteTableStatisticsStatus.UNSUPPORTED_TYPE,
                )
                for result in self.results
            ),
            timed_out=0,
        )
        if self.summary != expected:
            raise ValueError("Batch summary does not match batch results.")


@dataclass(frozen=True, slots=True)
class RefreshRemoteTableStatisticsRequest:
    """
    Input for refreshing statistics for one remote table.
    """
    table: str
    space: str


@dataclass(frozen=True, slots=True)
class RefreshRemoteTableStatisticsResult:
    """
    Result of refreshing statistics for one remote table.
    """
    table: str
    space: str
    status: RefreshRemoteTableStatisticsStatus


@dataclass(frozen=True, slots=True)
class RefreshRemoteTableStatisticsBatchRequest:
    """
    Input for refreshing statistics with concurrency.
    """
    tables: tuple[str, ...] | None
    space: str
    max_concurrency: int = DEFAULT_REMOTE_TABLE_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is invalid.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class RefreshRemoteTableStatisticsBatchResult:
    """
    Ordered results of refreshing remote tables in a batch.
    """
    results: tuple[RefreshRemoteTableStatisticsResult, ...]
    summary: BatchSummary

    def __post_init__(self) -> None:
        """
        Validates result types and the exact remote table outcome categories.

        Raises:
            TypeError: If results is not a tuple of refresh results.
            ValueError: If the summary does not match the result statuses.
        """
        if not isinstance(self.results, tuple) or not all(
            isinstance(result, RefreshRemoteTableStatisticsResult)
            for result in self.results
        ):
            raise TypeError(
                "Batch results must contain "
                "RefreshRemoteTableStatisticsResult objects."
            )
        expected = BatchSummary(
            total=len(self.results),
            succeeded=sum(
                result.status is RefreshRemoteTableStatisticsStatus.REFRESHED
                for result in self.results
            ),
            failed=sum(
                result.status
                in (
                    RefreshRemoteTableStatisticsStatus.TABLE_NOT_FOUND,
                    RefreshRemoteTableStatisticsStatus.FAILED,
                )
                for result in self.results
            ),
            skipped=sum(
                result.status
                in (
                    RefreshRemoteTableStatisticsStatus.NO_STATISTICS,
                    RefreshRemoteTableStatisticsStatus.UNSUPPORTED,
                )
                for result in self.results
            ),
            timed_out=0,
        )
        if self.summary != expected:
            raise ValueError("Batch summary does not match batch results.")
