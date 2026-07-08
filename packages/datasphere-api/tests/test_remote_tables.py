from datetime import UTC, datetime

import httpx
import respx

from datasphere_api import DatasphereClient

TABLES_PATH = "/dwaas-core/statistics/BWBRIDGESPACE/remotetables"
TABLE_PATH = "/dwaas-core/statistics/BWBRIDGESPACE/remoteTables/TABLE_A"


@respx.mock
async def test_get_all_tables(client: DatasphereClient) -> None:
    respx.get(path=TABLES_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "tables": [
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
            },
        )
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
async def test_create_statistics_outcomes(client: DatasphereClient) -> None:
    route = respx.post(path=TABLE_PATH)

    route.mock(return_value=httpx.Response(202))
    assert await client.remote_tables.create_statistics("TABLE_A") == (
        "created"
    )

    route.mock(
        return_value=httpx.Response(500, text="STATISTICS_ALREADY_EXISTS")
    )
    assert await client.remote_tables.create_statistics("TABLE_A") == (
        "already_exists"
    )

    route.mock(return_value=httpx.Response(400))
    assert await client.remote_tables.create_statistics("TABLE_A") == (
        "failed"
    )


@respx.mock
async def test_update_statistics_outcomes(client: DatasphereClient) -> None:
    route = respx.put(path=TABLE_PATH)

    route.mock(return_value=httpx.Response(202))
    assert await client.remote_tables.update_statistics(
        "TABLE_A", statistics_type="SIMPLE"
    ) == ("updated")

    route.mock(return_value=httpx.Response(400))
    assert await client.remote_tables.update_statistics("TABLE_A") == (
        "failed"
    )


@respx.mock
async def test_refresh_statistics(client: DatasphereClient) -> None:
    route = respx.post(path=f"{TABLE_PATH}/refresh")

    route.mock(return_value=httpx.Response(202))
    assert await client.remote_tables.refresh_statistics("TABLE_A") is True

    route.mock(return_value=httpx.Response(500))
    assert await client.remote_tables.refresh_statistics("TABLE_A") is False
