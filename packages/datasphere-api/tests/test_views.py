import httpx
import pytest
import respx

from datasphere_api import DatasphereClient, UnexpectedResponse

SEARCH_PATH = "/deepsea/repository/search/$all"
EXECUTE_PATH = "/dwaas-core/tf/directexecute"
PARTITIONING_PATH = "/dwaas-core/partitioning/SP/persistedViews/VIEW1"


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
async def test_get_view_attributes(client: DatasphereClient) -> None:
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
    attributes = await client.views.get_view_attributes(
        view_id="v1", view_name="VIEW1", space="SP"
    )
    assert attributes == ["FISCYEAR", "OTHER"]


@respx.mock
async def test_get_view_attributes_broken_payload(
    client: DatasphereClient,
) -> None:
    respx.get(path="/deepsea/repository/SP/designObjects").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    attributes = await client.views.get_view_attributes(
        view_id="v1", view_name="VIEW1", space="SP"
    )
    assert attributes == []


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
async def test_is_persisted(client: DatasphereClient) -> None:
    respx.get(path="/dwaas-core/monitor/SP/persistedViews/VIEW1").mock(
        return_value=httpx.Response(
            200, json={"dataPersistency": "Persisted"}
        )
    )
    assert await client.views.is_persisted("VIEW1", "SP") is True


@respx.mock
async def test_is_persisted_raises_after_retries(
    client: DatasphereClient,
    monkeypatch,
) -> None:
    # Skip the retry delays
    async def no_sleep(_seconds: float) -> None:
        return

    monkeypatch.setattr("asyncio.sleep", no_sleep)
    respx.get(path="/dwaas-core/monitor/SP/persistedViews/VIEW1").mock(
        return_value=httpx.Response(500)
    )
    with pytest.raises(UnexpectedResponse):
        await client.views.is_persisted("VIEW1", "SP")


@respx.mock
async def test_analyze_view(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/advisor/SP/execute/VIEW1").mock(
        return_value=httpx.Response(202, text='{"status": "Running"}')
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json={"logs": [{"status": "COMPLETED", "logId": 5}]}
        )
    )
    respx.get(path="/dwaas-core/advisor/SP/result/5").mock(
        return_value=httpx.Response(
            200,
            json={
                "entityStats": [
                    {"entity": "VIEW1", "persistencyCandidateScore": 10}
                ]
            },
        )
    )
    entity_stats = await client.views.analyze_view("VIEW1", "SP")
    assert entity_stats == [
        {"entity": "VIEW1", "persistencyCandidateScore": 10}
    ]


@respx.mock
async def test_create_partitioning_outcomes(
    client: DatasphereClient,
) -> None:
    partitioning_route = respx.get(path=PARTITIONING_PATH)
    post_route = respx.post(path=PARTITIONING_PATH)

    # Non-string column is rejected without a POST
    partitioning_route.mock(
        return_value=httpx.Response(
            200,
            json={
                "ranges": [],
                "partitioningColumns": {"FISCYEAR": {"type": "cds.Integer"}},
            },
        )
    )
    outcome = await client.views.create_partitioning(
        view="VIEW1",
        space="SP",
        attribute="FISCYEAR",
        partitions=["0000", "2024", "2025"],
    )
    assert outcome == "invalid_column"
    assert not post_route.called

    # Existing partitions are skipped unless overwriting is requested
    partitioning_route.mock(
        return_value=httpx.Response(
            200,
            json={
                "ranges": [{"id": 1}],
                "partitioningColumns": {"FISCYEAR": {"type": "cds.String"}},
            },
        )
    )
    outcome = await client.views.create_partitioning(
        view="VIEW1",
        space="SP",
        attribute="FISCYEAR",
        partitions=["0000", "2024", "2025"],
    )
    assert outcome == "exists"

    # Overwriting posts the new partitioning
    post_route.mock(return_value=httpx.Response(201))
    outcome = await client.views.create_partitioning(
        view="VIEW1",
        space="SP",
        attribute="FISCYEAR",
        partitions=["0000", "2024", "2025"],
        overwrite_existing=True,
    )
    assert outcome == "created"

    # Check the posted ranges
    import json

    payload = json.loads(post_route.calls.last.request.content)
    assert payload["ranges"][0]["low"]["value"] == "0000"
    assert payload["ranges"][-1]["high"]["value"] == "2025"


@respx.mock
async def test_lock_partitions(client: DatasphereClient) -> None:
    respx.get(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "remoteSourceName": "",
                "objectName": "VIEW1",
                "numParallelPartitions": 1,
                "ranges": [
                    {"low": {"value": "2020"}, "locked": False},
                    {"low": {"value": "2025"}, "locked": False},
                ],
                "column": "FISCYEAR",
                "columnType": "cds.String",
                "runtimeDataCalculation": "designtime",
                "type": "range",
            },
        )
    )
    post_route = respx.post(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(201)
    )

    outcome = await client.views.lock_partitions(
        view="VIEW1", space="SP", until_year=2023
    )
    assert outcome == "locked"

    # Only the partition below the year limit is locked
    import json

    payload = json.loads(post_route.calls.last.request.content)
    assert payload["ranges"][0]["locked"] is True
    assert payload["ranges"][1]["locked"] is False


@respx.mock
async def test_lock_partitions_without_partitions(
    client: DatasphereClient,
) -> None:
    respx.get(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(
            200, json={"ranges": [], "partitioningColumns": {}}
        )
    )
    outcome = await client.views.lock_partitions(
        view="VIEW1", space="SP", until_year=2023
    )
    assert outcome == "no_partitions"


@respx.mock
async def test_delete_partitioning(client: DatasphereClient) -> None:
    respx.delete(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(200)
    )
    assert await client.views.delete_partitioning("VIEW1", "SP") is True

    respx.delete(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(404)
    )
    assert await client.views.delete_partitioning("VIEW1", "SP") is False
