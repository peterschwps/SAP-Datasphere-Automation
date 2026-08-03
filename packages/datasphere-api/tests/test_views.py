import asyncio

import httpx
import respx

from datasphere_api import (
    DatasphereClient,
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
async def test_delete_partitioning(client: DatasphereClient) -> None:
    respx.delete(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(200)
    )
    assert await client.views.delete_partitioning("VIEW1", "SP") is True

    respx.delete(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(404)
    )
    assert await client.views.delete_partitioning("VIEW1", "SP") is False
