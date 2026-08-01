from types import SimpleNamespace
from typing import Any, cast

from datasphere_api import DatasphereClient
from datasphere_core import CommandContext
from datasphere_core.commands.remote_tables import (
    configure_remote_table_statistics,
    configure_remote_table_statistics_batch,
    refresh_remote_table_statistics_batch,
)
from datasphere_core.models.common import BatchSummary
from datasphere_core.models.remote_tables import (
    ConfigureRemoteTableStatisticsBatchRequest,
    ConfigureRemoteTableStatisticsRequest,
    ConfigureRemoteTableStatisticsStatus,
    RefreshRemoteTableStatisticsBatchRequest,
    RefreshRemoteTableStatisticsStatus,
    StatisticsType,
)


def _table(
    *,
    supported: bool = True,
    record_count_only: bool = False,
    statistics_type: str | None = None,
) -> dict[str, Any]:
    """
    Builds the statistics metadata of one remote table.
    """
    return {
        "statisticsSupported": supported,
        "statisticsLimitedToRecordCount": record_count_only,
        "statisticsType": statistics_type,
        "businessName": "Table",
        "statisticsLatestUpdate": None,
    }


def _client(tables: dict[str, Any], **operations: Any) -> DatasphereClient:
    """
    Builds a client whose remote table resource returns the supplied tables.
    """
    async def get_all_tables(space: str = "SPACE_A") -> dict[str, Any]:
        return tables

    return cast(
        DatasphereClient,
        SimpleNamespace(
            remote_tables=SimpleNamespace(
                get_all_tables=get_all_tables,
                **operations,
            )
        ),
    )


async def test_configure_creates_statistics_when_none_exist() -> None:
    """
    Checks that a table without statistics gets them created.
    """
    created: list[tuple[str, str, str]] = []

    async def create_statistics(
        table: str,
        statistics_type: str,
        space: str,
    ) -> str:
        created.append((table, statistics_type, space))
        return "created"

    result = await configure_remote_table_statistics(
        CommandContext(
            client=_client(
                {"TABLE_A": _table()},
                create_statistics=create_statistics,
            )
        ),
        ConfigureRemoteTableStatisticsRequest(
            table="TABLE_A",
            space="SPACE_A",
            statistics_type=StatisticsType.HISTOGRAM,
        ),
    )

    assert created == [("TABLE_A", "HISTOGRAM", "SPACE_A")]
    assert result.status is ConfigureRemoteTableStatisticsStatus.CREATED


async def test_configure_updates_statistics_of_a_different_type() -> None:
    """
    Checks that statistics of another type are updated, not created.
    """
    async def update_statistics(
        table: str,
        statistics_type: str,
        space: str,
    ) -> str:
        return "updated"

    result = await configure_remote_table_statistics(
        CommandContext(
            client=_client(
                {"TABLE_A": _table(statistics_type="SIMPLE")},
                update_statistics=update_statistics,
            )
        ),
        ConfigureRemoteTableStatisticsRequest(
            table="TABLE_A",
            space="SPACE_A",
            statistics_type=StatisticsType.HISTOGRAM,
        ),
    )

    assert result.status is ConfigureRemoteTableStatisticsStatus.UPDATED


async def test_configure_batch_discovers_and_classifies_every_table() -> None:
    """
    Checks that a discovery batch classifies every table it finds.
    """
    async def create_statistics(
        table: str,
        statistics_type: str,
        space: str,
    ) -> str:
        return "created"

    tables = {
        "TABLE_A": _table(),
        "TABLE_B": _table(supported=False),
        "TABLE_C": _table(record_count_only=True),
        "TABLE_D": _table(statistics_type="HISTOGRAM"),
    }

    result = await configure_remote_table_statistics_batch(
        CommandContext(
            client=_client(tables, create_statistics=create_statistics)
        ),
        ConfigureRemoteTableStatisticsBatchRequest(
            tables=None,
            space="SPACE_A",
            statistics_type=StatisticsType.HISTOGRAM,
        ),
    )

    # Discovered tables are processed in a stable, sorted order
    assert [item.table for item in result.results] == [
        "TABLE_A",
        "TABLE_B",
        "TABLE_C",
        "TABLE_D",
    ]
    assert [item.status for item in result.results] == [
        ConfigureRemoteTableStatisticsStatus.CREATED,
        ConfigureRemoteTableStatisticsStatus.UNSUPPORTED,
        ConfigureRemoteTableStatisticsStatus.UNSUPPORTED_TYPE,
        ConfigureRemoteTableStatisticsStatus.ALREADY_CONFIGURED,
    ]

    # Unsupported tables are skipped, not failed
    assert result.summary == BatchSummary(
        total=4,
        succeeded=2,
        failed=0,
        skipped=2,
        timed_out=0,
    )


async def test_refresh_batch_classifies_selected_tables() -> None:
    """
    Checks that a refresh batch classifies each selected table.
    """
    async def refresh_statistics(table: str, space: str) -> bool:
        return table == "TABLE_A"

    tables = {
        "TABLE_A": _table(statistics_type="HISTOGRAM"),
        "TABLE_B": _table(statistics_type="HISTOGRAM"),
        "TABLE_C": _table(),
    }

    result = await refresh_remote_table_statistics_batch(
        CommandContext(
            client=_client(tables, refresh_statistics=refresh_statistics)
        ),
        RefreshRemoteTableStatisticsBatchRequest(
            tables=("TABLE_A", "TABLE_B", "TABLE_C", "TABLE_MISSING"),
            space="SPACE_A",
        ),
    )

    assert [item.status for item in result.results] == [
        RefreshRemoteTableStatisticsStatus.REFRESHED,
        RefreshRemoteTableStatisticsStatus.FAILED,
        RefreshRemoteTableStatisticsStatus.NO_STATISTICS,
        RefreshRemoteTableStatisticsStatus.TABLE_NOT_FOUND,
    ]
    assert result.summary == BatchSummary(
        total=4,
        succeeded=1,
        failed=2,
        skipped=1,
        timed_out=0,
    )
