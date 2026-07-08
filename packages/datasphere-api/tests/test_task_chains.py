import httpx
import respx

from datasphere_api import DatasphereClient


@respx.mock
async def test_run_success(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(202, json={"logId": 3})
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json=[{"status": "COMPLETED", "runTime": 65432}]
        )
    )
    success, log_details = await client.task_chains.run("CHAIN", "SP")
    assert success is True
    assert log_details["runTime"] == 65432


@respx.mock
async def test_run_start_failure(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(400)
    )
    success, log_details = await client.task_chains.run("CHAIN", "SP")
    assert success is False
    assert log_details == {}


@respx.mock
async def test_run_reports_failed_chains(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(202, json={"logId": 4})
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json=[{"status": "FAILED", "runTime": 1000}]
        )
    )
    success, log_details = await client.task_chains.run("CHAIN", "SP")
    assert success is False
    assert log_details["status"] == "FAILED"
