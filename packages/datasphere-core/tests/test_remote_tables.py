from collections.abc import Callable
from typing import Any

import httpx
import respx
from datasphere_core import CommandContext
from datasphere_core.commands.remote_tables import (
    _write_status,
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


TABLES_PATH = "/dwaas-core/statistics/SPACE_A/remotetables"


def _tables_route(tables: dict[str, Any]) -> None:
    """
    Answers the discovery endpoint with the supplied tables.
    """
    respx.get(path=TABLES_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "tables": [
                    {"tableName": name, **metadata}
                    for name, metadata in tables.items()
                ]
            },
        )
    )


def _write_route(table: str, method: str = "POST") -> respx.Route:
    """
    Answers the statistics endpoint of one table with an accepted write.
    """
    return respx.request(
        method,
        path=f"/dwaas-core/statistics/SPACE_A/remoteTables/{table}",
    ).mock(return_value=httpx.Response(202))


@respx.mock
async def test_configure_creates_statistics_when_none_exist(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a table without statistics gets them created.
    """
    _tables_route({"TABLE_A": _table()})
    created = _write_route("TABLE_A")

    result = await configure_remote_table_statistics(
        context(),
        ConfigureRemoteTableStatisticsRequest(
            table="TABLE_A",
            space="SPACE_A",
            statistics_type=StatisticsType.HISTOGRAM,
        ),
    )

    # A table without statistics is written with POST, not PUT
    assert created.calls.last.request.url.params["type"] == "HISTOGRAM"
    assert result.status is ConfigureRemoteTableStatisticsStatus.CREATED


async def test_configure_maps_the_same_answer_per_endpoint() -> None:
    """
    Checks that an accepted write means created or updated by endpoint.
    """
    assert _write_status("accepted", creating=True) is (
        ConfigureRemoteTableStatisticsStatus.CREATED
    )
    assert _write_status("accepted", creating=False) is (
        ConfigureRemoteTableStatisticsStatus.UPDATED
    )

    # A conflict and a refusal read the same on both endpoints
    assert _write_status("already_exists", creating=True) is (
        ConfigureRemoteTableStatisticsStatus.ALREADY_EXISTS
    )
    assert _write_status("failed", creating=False) is (
        ConfigureRemoteTableStatisticsStatus.FAILED
    )


@respx.mock
async def test_configure_updates_statistics_of_a_different_type(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that statistics of another type are updated, not created.
    """
    _tables_route({"TABLE_A": _table(statistics_type="SIMPLE")})
    updated = _write_route("TABLE_A", "PUT")

    result = await configure_remote_table_statistics(
        context(),
        ConfigureRemoteTableStatisticsRequest(
            table="TABLE_A",
            space="SPACE_A",
            statistics_type=StatisticsType.HISTOGRAM,
        ),
    )

    # Replacing an existing type goes to PUT
    assert updated.called
    assert result.status is ConfigureRemoteTableStatisticsStatus.UPDATED


@respx.mock
async def test_configure_batch_discovers_and_classifies_every_table(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a discovery batch classifies every table it finds.
    """
    _tables_route(
        {
            "TABLE_A": _table(),
            "TABLE_B": _table(supported=False),
            "TABLE_C": _table(record_count_only=True),
            "TABLE_D": _table(statistics_type="HISTOGRAM"),
        }
    )
    _write_route("TABLE_A")

    result = await configure_remote_table_statistics_batch(
        context(),
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


@respx.mock
async def test_configure_batch_reports_an_unknown_table_as_not_found(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a table the space does not hold is reported as not found.
    """
    _tables_route({"TABLE_A": _table()})
    _write_route("TABLE_A")

    result = await configure_remote_table_statistics_batch(
        context(),
        ConfigureRemoteTableStatisticsBatchRequest(
            tables=("TABLE_A", "TABLE_MISSING"),
            space="SPACE_A",
            statistics_type=StatisticsType.HISTOGRAM,
        ),
    )

    # Both commands name the same cause the same way, even though only the
    # explicit table selection can reach it
    assert [item.status for item in result.results] == [
        ConfigureRemoteTableStatisticsStatus.CREATED,
        ConfigureRemoteTableStatisticsStatus.TABLE_NOT_FOUND,
    ]
    assert result.summary.failed == 1


@respx.mock
async def test_refresh_batch_classifies_selected_tables(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a refresh batch classifies each selected table.
    """
    _tables_route(
        {
            "TABLE_A": _table(statistics_type="HISTOGRAM"),
            "TABLE_B": _table(statistics_type="HISTOGRAM"),
            "TABLE_C": _table(),
        }
    )
    for table, accepted in (("TABLE_A", 202), ("TABLE_B", 500)):
        respx.post(
            path=f"/dwaas-core/statistics/SPACE_A/remoteTables/{table}/refresh"
        ).mock(return_value=httpx.Response(accepted))

    result = await refresh_remote_table_statistics_batch(
        context(),
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
