from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, TypedDict

from datasphere_core.models.common import (
    BatchSummary,
    CommandStatus,
    Outcome,
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


class ConfigureRemoteTableStatisticsStatus(CommandStatus):
    """
    Result status of configuring remote table statistics.
    """
    CREATED = "created", Outcome.SUCCEEDED
    UPDATED = "updated", Outcome.SUCCEEDED
    ALREADY_CONFIGURED = "already_configured", Outcome.SUCCEEDED
    ALREADY_EXISTS = "already_exists", Outcome.SUCCEEDED
    UNSUPPORTED = "unsupported", Outcome.SKIPPED
    UNSUPPORTED_TYPE = "unsupported_type", Outcome.SKIPPED
    TABLE_NOT_FOUND = "table_not_found", Outcome.FAILED
    FAILED = "failed", Outcome.FAILED


class RefreshRemoteTableStatisticsStatus(CommandStatus):
    """
    Result status of refreshing remote table statistics.
    """
    REFRESHED = "refreshed", Outcome.SUCCEEDED
    NO_STATISTICS = "no_statistics", Outcome.SKIPPED
    UNSUPPORTED = "unsupported", Outcome.SKIPPED
    TABLE_NOT_FOUND = "table_not_found", Outcome.FAILED
    FAILED = "failed", Outcome.FAILED


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
    Input for configuring remote table statistics with concurrency. Configures
    every remote table of the space if no explicit tables are supplied.
    """
    tables: tuple[str, ...] | None
    space: str
    statistics_type: StatisticsType
    max_concurrency: int = DEFAULT_REMOTE_TABLE_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is not within the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class ConfigureRemoteTableStatisticsBatchResult:
    """
    Ordered results of configuring remote table statistics in a batch.
    """
    results: tuple[ConfigureRemoteTableStatisticsResult, ...]
    summary: BatchSummary


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
    Input for refreshing statistics with concurrency. Refreshes every remote
    table of the space if no explicit tables are supplied.
    """
    tables: tuple[str, ...] | None
    space: str
    max_concurrency: int = DEFAULT_REMOTE_TABLE_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        """
        Validates the batch concurrency limit.

        Raises:
            ValueError: If the concurrency limit is not within the supported
                        range.
        """
        validate_max_concurrency(self.max_concurrency)


@dataclass(frozen=True, slots=True)
class RefreshRemoteTableStatisticsBatchResult:
    """
    Ordered results of refreshing remote table statistics in a batch.
    """
    results: tuple[RefreshRemoteTableStatisticsResult, ...]
    summary: BatchSummary


# What a write against the statistics endpoint achieved
StatisticsWriteOutcome = Literal["accepted", "already_exists", "failed"]


class StatisticsInformationDict(TypedDict):
    statisticsSupported: bool
    statisticsLimitedToRecordCount: bool
    statisticsType: StatisticsType | None
    businessName: str
    statisticsLatestUpdate: datetime | None


StatisticsDict = dict[str, StatisticsInformationDict]
