import httpx
import respx

from datasphere_api import DatasphereClient
from datasphere_api.models import PersistResult

SEARCH_PATH = "/deepsea/repository/search/$all"
EXECUTE_PATH = "/dwaas-core/tf/directexecute"


@respx.mock
async def test_get_all_views(client: DatasphereClient) -> None:
    respx.get(path=SEARCH_PATH).mock(
        return_value=httpx.Response(
            200,
            json={"value": [{"id": "v1", "name": "VIEW1"}]},
        )
    )
    views = await client.views.get_all_views()
    assert views == [{"id": "v1", "name": "VIEW1"}]


@respx.mock
async def test_get_all_views_where_attribute_contains(
    client: DatasphereClient,
) -> None:
    respx.get(path=SEARCH_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "v1",
                        "name": "VIEW1",
                        "space_name": "SP",
                        "business_name": "View One",
                    }
                ]
            },
        )
    )
    respx.get(path="/deepsea/repository/SP/designObjects").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "#repairedCsn": {
                            "definitions": {
                                "VIEW1": {
                                    "elements": {
                                        "FISCYEAR": {},
                                        "OTHER": {},
                                    }
                                }
                            }
                        }
                    }
                ]
            },
        )
    )

    matches = await client.views.get_all_views_where_attribute_contains(
        word="fisc"
    )
    assert matches == [
        {
            "entity": "VIEW1",
            "space": "SP",
            "businessName": "View One",
            "attribute": "FISCYEAR",
        }
    ]


@respx.mock
async def test_persist_view_success(client: DatasphereClient) -> None:
    respx.post(path=EXECUTE_PATH).mock(
        return_value=httpx.Response(202, json={"taskLogId": 7})
    )
    respx.get(path="/dwaas-core/tf/SP/extendedlogs/7").mock(
        return_value=httpx.Response(
            200,
            json={"logDetails": {"status": "COMPLETED", "runTime": 65000}},
        )
    )
    success, log_details = await client.views.persist_view("VIEW1", "SP")
    assert success is True
    assert log_details["runTime"] == 65000


@respx.mock
async def test_persist_view_failure(client: DatasphereClient) -> None:
    respx.post(path=EXECUTE_PATH).mock(
        return_value=httpx.Response(202, json={"taskLogId": 8})
    )
    respx.get(path="/dwaas-core/tf/SP/extendedlogs/8").mock(
        return_value=httpx.Response(
            200,
            json={"logDetails": {"status": "FAILED", "runTime": 1000}},
        )
    )
    success, _ = await client.views.persist_view("VIEW1", "SP")
    assert success is False


@respx.mock
async def test_persist_views_invokes_callback(
    client: DatasphereClient,
) -> None:
    respx.post(path=EXECUTE_PATH).mock(
        return_value=httpx.Response(202, json={"taskLogId": 9})
    )
    respx.get(path="/dwaas-core/tf/SP/extendedlogs/9").mock(
        return_value=httpx.Response(
            200,
            json={"logDetails": {"status": "COMPLETED", "runTime": 5000}},
        )
    )
    received: list[PersistResult] = []

    results = await client.views.persist_views(
        views=[{"entity": "VIEW1", "space": "SP"}],
        timer=True,
        on_result=received.append,
    )
    expected: PersistResult = {
        "entity": "VIEW1",
        "space": "SP",
        "isPersisted": True,
        "runtime": 5,
    }
    assert results == [expected]
    assert received == [expected]


@respx.mock
async def test_unpersist_view_skips_unpersisted(
    client: DatasphereClient,
) -> None:
    respx.get(path="/dwaas-core/monitor/SP/persistedViews/VIEW1").mock(
        return_value=httpx.Response(
            200, json={"dataPersistency": "Not Persisted"}
        )
    )
    success, log_details = await client.views.unpersist_view("VIEW1", "SP")
    assert success is True
    assert log_details == {}


@respx.mock
async def test_create_partitioning_matrix(client: DatasphereClient) -> None:
    partitioning_path = "/dwaas-core/partitioning/SP/persistedViews"
    respx.get(path=f"{partitioning_path}/STRING_COL").mock(
        return_value=httpx.Response(
            200,
            json={
                "ranges": [],
                "partitioningColumns": {"FISCYEAR": {"type": "cds.String"}},
            },
        )
    )
    respx.post(path=f"{partitioning_path}/STRING_COL").mock(
        return_value=httpx.Response(201)
    )
    respx.get(path=f"{partitioning_path}/INT_COL").mock(
        return_value=httpx.Response(
            200,
            json={
                "ranges": [],
                "partitioningColumns": {"FISCYEAR": {"type": "cds.Integer"}},
            },
        )
    )
    respx.get(path=f"{partitioning_path}/EXISTING").mock(
        return_value=httpx.Response(
            200,
            json={
                "ranges": [{"id": 1}],
                "partitioningColumns": {"FISCYEAR": {"type": "cds.String"}},
            },
        )
    )

    results = await client.views.create_partitioning_for_views(
        views=[
            {"entity": "STRING_COL", "space": "SP", "attribute": "FISCYEAR"},
            {"entity": "INT_COL", "space": "SP", "attribute": "FISCYEAR"},
            {"entity": "EXISTING", "space": "SP", "attribute": "FISCYEAR"},
        ],
        partitions=["0000", "2024", "2025"],
    )
    by_entity = {
        result["entity"]: result["createdPartition"] for result in results
    }
    assert by_entity == {
        "STRING_COL": True,
        "INT_COL": False,  # non-string column is skipped
        "EXISTING": True,  # existing partition counts as created
    }


@respx.mock
async def test_remove_partitioning_reports_failures(
    client: DatasphereClient,
) -> None:
    partitioning_path = "/dwaas-core/partitioning/SP/persistedViews"
    respx.delete(path=f"{partitioning_path}/GOOD").mock(
        return_value=httpx.Response(200)
    )
    respx.delete(path=f"{partitioning_path}/BAD").mock(
        return_value=httpx.Response(404)
    )

    results = await client.views.remove_partitioning_for_views(
        views=[
            {"entity": "GOOD", "space": "SP"},
            {"entity": "BAD", "space": "SP"},
        ]
    )
    by_entity = {
        result["entity"]: result["removedPartition"] for result in results
    }
    assert by_entity == {"GOOD": True, "BAD": False}
