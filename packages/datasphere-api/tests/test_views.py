import asyncio

import httpx
import pytest
import respx

from datasphere_api import (
    DatasphereClient,
    UnexpectedResponse,
    ViewAnalysisCancelled,
    ViewAnalysisTimeout,
    ViewPersistenceCancelled,
    ViewPersistenceTimeout,
)

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
async def test_request_headers_are_isolated_during_concurrent_requests(
    client: DatasphereClient,
) -> None:
    client.session.headers.update(
        {
            "Authorization": "Bearer access-token",
            "X-Client-Default": "preserved",
        }
    )
    view_route = respx.get(path=SEARCH_PATH).mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    table_route = respx.get(
        path="/dwaas-core/statistics/SP/remotetables"
    ).mock(return_value=httpx.Response(200, json={"tables": []}))

    await asyncio.gather(
        client.views.get_all_views(),
        client.remote_tables.get_all_tables("SP"),
    )

    view_headers = view_route.calls.last.request.headers
    table_headers = table_route.calls.last.request.headers
    assert view_headers["Authorization"] == "Bearer access-token"
    assert view_headers["X-Client-Default"] == "preserved"
    assert view_headers["Accept"] == "application/json"
    assert view_headers["Accept-Language"] == "de"
    assert view_headers["Cache-Control"] == "no-cache"
    assert table_headers["Authorization"] == "Bearer access-token"
    assert table_headers["X-Client-Default"] == "preserved"
    assert "Cache-Control" not in table_headers
    assert "Cache-Control" not in client.session.headers
    assert client.session.headers["Authorization"] == "Bearer access-token"


@respx.mock
async def test_operation_headers_are_complete_and_fresh(
    client: DatasphereClient,
) -> None:
    client.session.headers.update(
        {
            "Authorization": "Bearer access-token",
            "X-Client-Default": "preserved",
            "Accept": "text/plain",
        }
    )

    async def execute(request: httpx.Request) -> httpx.Response:
        payload = request.content.decode()
        task_log_id = 1 if '"PERSIST"' in payload else 2
        return httpx.Response(202, json={"taskLogId": task_log_id})

    async def logs(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("taskLogId"):
            return httpx.Response(200, json=[{"status": "RUNNING"}])
        return httpx.Response(200, json={"logs": []})

    task_start = respx.post(
        path="/dwaas-core/tf/SP/taskchains/CHAIN/start"
    ).mock(return_value=httpx.Response(202, json={"logId": 3}))
    task_logs = respx.get(path="/dwaas-core/tf/SP/logs").mock(
        side_effect=logs
    )
    analyzer_start = respx.post(
        path="/dwaas-core/advisor/SP/execute/VIEW1"
    ).mock(return_value=httpx.Response(202, text='{"status": "Running"}'))
    analyzer_result = respx.get(
        path="/dwaas-core/advisor/SP/result/4"
    ).mock(return_value=httpx.Response(200, json={}))
    partition_get = respx.get(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(200, json={})
    )
    partition_set = respx.post(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(201)
    )
    partition_delete = respx.delete(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(200)
    )
    execute_route = respx.post(EXECUTE_PATH).mock(side_effect=execute)

    await asyncio.gather(
        client.task_chains.start("CHAIN", "SP"),
        client.task_chains.get_log(3, "SP"),
        client.views.start_view_analyzer("VIEW1", "SP"),
        client.views.get_task_logs("VIEW1", "SP"),
        client.views.get_view_analyzer_result(4, "SP"),
        client.views.get_partitioning("VIEW1", "SP"),
        client.views.set_partitioning("VIEW1", "SP", {}),
        client.views.delete_partitioning("VIEW1", "SP"),
        client.views.start_persistence("VIEW1", "SP"),
        client.views.start_persistence_removal("VIEW1", "SP"),
    )

    routes = [
        task_start,
        task_logs,
        analyzer_start,
        analyzer_result,
        partition_get,
        partition_set,
        partition_delete,
        execute_route,
    ]
    requests = [call.request for route in routes for call in route.calls]
    request_ids = [request.headers["x-request-id"] for request in requests]
    assert len(request_ids) == len(set(request_ids))
    for request in requests:
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.headers["X-Client-Default"] == "preserved"

    for request in [
        task_start.calls.last.request,
        partition_get.calls.last.request,
        partition_set.calls.last.request,
        partition_delete.calls.last.request,
        execute_route.calls[0].request,
        execute_route.calls[1].request,
    ]:
        assert request.headers["Accept"] == "*/*"

    task_log_request = next(
        call.request
        for call in task_logs.calls
        if call.request.url.params.get("taskLogId")
    )
    analyzer_log_request = next(
        call.request
        for call in task_logs.calls
        if not call.request.url.params.get("taskLogId")
    )
    assert task_log_request.headers["Accept"] == "*/*"
    for request in [
        analyzer_start.calls.last.request,
        analyzer_log_request,
        analyzer_result.calls.last.request,
    ]:
        assert request.headers["Accept"] == "*/*"
        assert request.headers["X-Requested-With"] == "XMLHttpRequest"


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
    assert log_details["logId"] == 7


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
    success, log_details = await client.views.persist_view("VIEW1", "SP")
    assert success is False
    assert log_details["logId"] == 8


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


@pytest.mark.parametrize(
    ("status", "expected_success"),
    [("COMPLETED", True), ("FAILED", False)],
)
@respx.mock
async def test_unpersist_view_log_details_include_log_id(
    client: DatasphereClient,
    status: str,
    expected_success: bool,
) -> None:
    respx.get(path="/dwaas-core/monitor/SP/persistedViews/VIEW1").mock(
        return_value=httpx.Response(200, json={"dataPersistency": "Persisted"})
    )
    respx.post(path=EXECUTE_PATH).mock(
        return_value=httpx.Response(202, json={"taskLogId": 9})
    )
    respx.get(path="/dwaas-core/tf/SP/extendedlogs/9").mock(
        return_value=httpx.Response(
            200,
            json={"logDetails": {"status": status, "runTime": 1000}},
        )
    )

    success, log_details = await client.views.unpersist_view("VIEW1", "SP")

    assert success is expected_success
    assert log_details["logId"] == 9


@pytest.mark.parametrize(
    "timeout", [True, False, 0, -1, float("nan"), float("inf")]
)
@pytest.mark.parametrize(
    "workflow",
    ["persist_view", "unpersist_view", "analyze_view"],
)
@respx.mock
async def test_view_workflows_reject_invalid_timeout_before_remote_operation(
    client: DatasphereClient,
    workflow: str,
    timeout: float,
) -> None:
    execute_route = respx.post(path=EXECUTE_PATH).mock(
        return_value=httpx.Response(202, json={"taskLogId": 10})
    )
    monitor_route = respx.get(
        path="/dwaas-core/monitor/SP/persistedViews/VIEW1"
    ).mock(
        return_value=httpx.Response(
            200, json={"dataPersistency": "Persisted"}
        )
    )
    analyzer_route = respx.post(
        path="/dwaas-core/advisor/SP/execute/VIEW1"
    ).mock(return_value=httpx.Response(202, text='{"status": "Running"}'))

    with pytest.raises(ValueError, match="Timeout must be a positive number"):
        await getattr(client.views, workflow)(
            "VIEW1",
            "SP",
            timeout_seconds=timeout,
        )

    assert execute_route.called is False
    assert monitor_route.called is False
    assert analyzer_route.called is False


@pytest.mark.parametrize("operation", ["persist", "unpersist"])
@respx.mock
async def test_persistence_timeout_retains_operation_identity(
    client: DatasphereClient,
    operation: str,
) -> None:
    if operation == "unpersist":
        respx.get(path="/dwaas-core/monitor/SP/persistedViews/VIEW1").mock(
            return_value=httpx.Response(
                200, json={"dataPersistency": "Persisted"}
            )
        )
    respx.post(path=EXECUTE_PATH).mock(
        return_value=httpx.Response(202, json={"taskLogId": 11})
    )
    respx.get(path="/dwaas-core/tf/SP/extendedlogs/11").mock(
        return_value=httpx.Response(
            200,
            json={"logDetails": {"status": "RUNNING", "runTime": 1}},
        )
    )
    workflow = (
        client.views.persist_view
        if operation == "persist"
        else client.views.unpersist_view
    )

    with pytest.raises(ViewPersistenceTimeout) as error:
        await workflow("VIEW1", "SP", timeout_seconds=0.001)

    assert error.value.operation == operation
    assert error.value.view == "VIEW1"
    assert error.value.space == "SP"
    assert error.value.log_id == 11
    assert "remote operation may continue" in str(error.value)


@pytest.mark.parametrize("operation", ["persist", "unpersist"])
@respx.mock
async def test_persistence_cancellation_retains_operation_identity(
    client: DatasphereClient,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    if operation == "unpersist":
        respx.get(path="/dwaas-core/monitor/SP/persistedViews/VIEW1").mock(
            return_value=httpx.Response(
                200, json={"dataPersistency": "Persisted"}
            )
        )
    respx.post(path=EXECUTE_PATH).mock(
        return_value=httpx.Response(202, json={"taskLogId": 12})
    )
    respx.get(path="/dwaas-core/tf/SP/extendedlogs/12").mock(
        return_value=httpx.Response(
            200,
            json={"logDetails": {"status": "RUNNING", "runTime": 1}},
        )
    )
    polling = asyncio.Event()

    async def wait_for_cancellation(_seconds: float) -> None:
        polling.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "datasphere_api.resources.views.asyncio.sleep",
        wait_for_cancellation,
    )
    workflow = (
        client.views.persist_view
        if operation == "persist"
        else client.views.unpersist_view
    )
    task = asyncio.create_task(workflow("VIEW1", "SP"))
    await polling.wait()
    task.cancel()

    with pytest.raises(ViewPersistenceCancelled) as error:
        await task

    assert error.value.operation == operation
    assert error.value.view == "VIEW1"
    assert error.value.space == "SP"
    assert error.value.log_id == 12
    assert "remote operation may continue" in str(error.value)


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
        return_value=httpx.Response(
            202, text='{"status": "Running", "logId": 5}'
        )
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
    result = await client.views.analyze_view("VIEW1", "SP")
    assert result == {
        "logId": 5,
        "entityStats": [
            {"entity": "VIEW1", "persistencyCandidateScore": 10}
        ],
    }


@respx.mock
async def test_analyze_view_uses_start_id_without_latest_log_race(
    client: DatasphereClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.post(path="/dwaas-core/advisor/SP/execute/VIEW1").mock(
        return_value=httpx.Response(
            202,
            json={"status": "Running", "logId": 20},
        )
    )
    logs_route = respx.get(path="/dwaas-core/tf/SP/logs").mock(
        side_effect=[
            httpx.Response(
                200, json={"logs": [{"status": "RUNNING", "logId": 19}]}
            ),
            httpx.Response(
                200,
                json={
                    "logs": [
                        {"status": "COMPLETED", "logId": 21},
                        {"status": "COMPLETED", "logId": 20},
                    ]
                },
            ),
        ]
    )
    result_route = respx.get(
        path="/dwaas-core/advisor/SP/result/20"
    ).mock(return_value=httpx.Response(200, json={"entityStats": []}))

    async def fail_sleep(_seconds: float) -> None:
        raise AssertionError("completed analysis must not sleep")

    monkeypatch.setattr(
        "datasphere_api.resources.views.asyncio.sleep", fail_sleep
    )

    result = await client.views.analyze_view("VIEW1", "SP")

    assert result == {"logId": 20, "entityStats": []}
    assert logs_route.call_count == 2
    assert result_route.call_count == 1


@respx.mock
async def test_analyze_view_finds_new_log_after_empty_poll(
    client: DatasphereClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.post(path="/dwaas-core/advisor/SP/execute/VIEW1").mock(
        return_value=httpx.Response(202, text='{"status": "Running"}')
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        side_effect=[
            httpx.Response(
                200, json={"logs": [{"status": "RUNNING", "logId": 30}]}
            ),
            httpx.Response(200, json={"logs": []}),
            httpx.Response(
                200, json={"logs": [{"status": "PENDING", "logId": 31}]}
            ),
            httpx.Response(
                200,
                json={"logs": [{"status": "COMPLETED", "logId": 31}]},
            ),
        ]
    )
    respx.get(path="/dwaas-core/advisor/SP/result/31").mock(
        return_value=httpx.Response(
            200,
            json={"entityStats": [{"entity": "VIEW1"}]},
        )
    )

    async def no_sleep(_seconds: float) -> None:
        return

    monkeypatch.setattr(
        "datasphere_api.resources.views.asyncio.sleep", no_sleep
    )

    result = await client.views.analyze_view("VIEW1", "SP")

    assert result == {
        "logId": 31,
        "entityStats": [{"entity": "VIEW1"}],
    }


@respx.mock
async def test_analyze_view_returns_id_for_terminal_status(
    client: DatasphereClient,
) -> None:
    respx.post(path="/dwaas-core/advisor/SP/execute/VIEW1").mock(
        return_value=httpx.Response(
            202, json={"status": "Running", "logId": 32}
        )
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        side_effect=[
            httpx.Response(200, json={"logs": []}),
            httpx.Response(
                200,
                json={"logs": [{"status": "CANCELLED", "logId": 32}]},
            ),
        ]
    )

    result = await client.views.analyze_view("VIEW1", "SP")

    assert result == {"logId": 32, "entityStats": []}


@respx.mock
async def test_analyze_view_result_retrieval_is_not_polling_timeout(
    client: DatasphereClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.post(path="/dwaas-core/advisor/SP/execute/VIEW1").mock(
        return_value=httpx.Response(
            202, json={"status": "Running", "logId": 33}
        )
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        side_effect=[
            httpx.Response(200, json={"logs": []}),
            httpx.Response(
                200,
                json={"logs": [{"status": "COMPLETED", "logId": 33}]},
            ),
        ]
    )

    async def result_retrieval(_log_id: int, _space: str) -> dict:
        raise TimeoutError("result retrieval timed out")

    monkeypatch.setattr(
        client.views,
        "get_view_analyzer_result",
        result_retrieval,
    )

    with pytest.raises(TimeoutError, match="result retrieval timed out"):
        await client.views.analyze_view("VIEW1", "SP")


@respx.mock
async def test_analyze_view_timeout_retains_discovered_log_id(
    client: DatasphereClient,
) -> None:
    respx.post(path="/dwaas-core/advisor/SP/execute/VIEW1").mock(
        return_value=httpx.Response(
            202, text='{"status": "Running", "logId": 13}'
        )
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json={"logs": [{"status": "RUNNING", "logId": 13}]}
        )
    )

    with pytest.raises(ViewAnalysisTimeout) as error:
        await client.views.analyze_view(
            "VIEW1",
            "SP",
            timeout_seconds=0.001,
        )

    assert error.value.view == "VIEW1"
    assert error.value.space == "SP"
    assert error.value.log_id == 13
    assert "remote operation may continue" in str(error.value)


@respx.mock
async def test_analyze_view_timeout_uses_none_before_log_is_discovered(
    client: DatasphereClient,
) -> None:
    respx.post(path="/dwaas-core/advisor/SP/execute/VIEW1").mock(
        return_value=httpx.Response(202, text='{"status": "Running"}')
    )

    async def delayed_logs(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(
            200, json={"logs": [{"status": "RUNNING", "logId": 14}]}
        )

    respx.get(path="/dwaas-core/tf/SP/logs").mock(side_effect=delayed_logs)

    with pytest.raises(ViewAnalysisTimeout) as error:
        await client.views.analyze_view(
            "VIEW1",
            "SP",
            timeout_seconds=0.001,
        )

    assert error.value.log_id is None


@respx.mock
async def test_analyze_view_cancellation_retains_discovered_log_id(
    client: DatasphereClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.post(path="/dwaas-core/advisor/SP/execute/VIEW1").mock(
        return_value=httpx.Response(
            202, text='{"status": "Running", "logId": 15}'
        )
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json={"logs": [{"status": "RUNNING", "logId": 15}]}
        )
    )
    polling = asyncio.Event()

    async def wait_for_cancellation(_seconds: float) -> None:
        polling.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "datasphere_api.resources.views.asyncio.sleep",
        wait_for_cancellation,
    )
    task = asyncio.create_task(client.views.analyze_view("VIEW1", "SP"))
    await polling.wait()
    task.cancel()

    with pytest.raises(ViewAnalysisCancelled) as error:
        await task

    assert error.value.view == "VIEW1"
    assert error.value.space == "SP"
    assert error.value.log_id == 15
    assert "remote operation may continue" in str(error.value)


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
