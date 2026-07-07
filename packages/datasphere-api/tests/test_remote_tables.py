from datetime import UTC, datetime

import httpx
import respx

from datasphere_api import DatasphereClient

TABLES_PATH = "/dwaas-core/statistics/BWBRIDGESPACE/remotetables"


def mock_tables(tables: list[dict]) -> None:
    respx.get(path=TABLES_PATH).mock(
        return_value=httpx.Response(200, json={"tables": tables})
    )


@respx.mock
async def test_get_all_tables(client: DatasphereClient) -> None:
    mock_tables(
        [
            {
                "tableName": "TABLE_A",
                "statisticsSupported": True,
                "statisticsType": "SIMPLE",
                "businessName": "Table A",
                "statisticsLatestUpdate": (
                    "2026-01-02 03:04:05.678000000000"
                ),
            },
            {"tableName": "TABLE_B"},
        ]
    )
    tables = await client.remote_tables.get_all_tables()

    # Check field mapping and defaults
    assert tables["TABLE_A"]["statisticsType"] == "SIMPLE"
    assert tables["TABLE_B"]["statisticsSupported"] is True
    assert tables["TABLE_B"]["statisticsType"] is None

    # Check aware-UTC datetime conversion
    latest_update = tables["TABLE_A"]["statisticsLatestUpdate"]
    assert latest_update == datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
    assert tables["TABLE_B"]["statisticsLatestUpdate"] is None


@respx.mock
async def test_create_statistics_matrix(client: DatasphereClient) -> None:
    mock_tables(
        [
            # No statistics yet -> POST -> created
            {"tableName": "NEW", "statisticsType": None},
            # Different type -> PUT -> updated
            {"tableName": "OTHER_TYPE", "statisticsType": "SIMPLE"},
            # Same type -> skipped without request
            {"tableName": "SAME_TYPE", "statisticsType": "HISTOGRAM"},
            # Not supported -> skipped without request
            {"tableName": "UNSUPPORTED", "statisticsSupported": False},
            # Server reports existing statistics -> already_exists
            {"tableName": "EXISTS", "statisticsType": None},
        ]
    )
    respx.post(
        path="/dwaas-core/statistics/BWBRIDGESPACE/remoteTables/NEW"
    ).mock(return_value=httpx.Response(202))
    respx.put(
        path="/dwaas-core/statistics/BWBRIDGESPACE/remoteTables/OTHER_TYPE"
    ).mock(return_value=httpx.Response(202))
    respx.post(
        path="/dwaas-core/statistics/BWBRIDGESPACE/remoteTables/EXISTS"
    ).mock(
        return_value=httpx.Response(500, text="STATISTICS_ALREADY_EXISTS")
    )

    results = await client.remote_tables.create_statistics()
    by_table = {result["tableName"]: result["status"] for result in results}
    assert by_table == {
        "NEW": "created",
        "OTHER_TYPE": "updated",
        "SAME_TYPE": "skipped",
        "UNSUPPORTED": "skipped",
        "EXISTS": "already_exists",
    }


@respx.mock
async def test_refresh_statistics(client: DatasphereClient) -> None:
    mock_tables(
        [
            {"tableName": "WITH_STATS", "statisticsType": "HISTOGRAM"},
            {"tableName": "NO_STATS", "statisticsType": None},
            {"tableName": "BROKEN", "statisticsType": "SIMPLE"},
        ]
    )
    respx.post(
        path=(
            "/dwaas-core/statistics/BWBRIDGESPACE"
            "/remoteTables/WITH_STATS/refresh"
        )
    ).mock(return_value=httpx.Response(202))
    respx.post(
        path=(
            "/dwaas-core/statistics/BWBRIDGESPACE"
            "/remoteTables/BROKEN/refresh"
        )
    ).mock(return_value=httpx.Response(500))

    results = await client.remote_tables.refresh_statistics()
    by_table = {result["tableName"]: result["status"] for result in results}
    assert by_table == {
        "WITH_STATS": "refreshed",
        "NO_STATS": "skipped",
        "BROKEN": "failed",
    }
