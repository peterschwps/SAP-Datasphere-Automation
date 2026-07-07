import httpx
import respx

from datasphere_api import DatasphereClient
from datasphere_api.models import TaskChainRunResult


@respx.mock
async def test_run_single_success(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(202, json={"logId": 3})
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json=[{"status": "COMPLETED", "runTime": 65432}]
        )
    )
    success, log_details = await client.task_chains.run_single(
        task_chain_name="CHAIN",
        task_chain_space="SP",
    )
    assert success is True
    assert log_details["runTime"] == 65432


@respx.mock
async def test_run_single_start_failure(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(400)
    )
    success, log_details = await client.task_chains.run_single(
        task_chain_name="CHAIN",
        task_chain_space="SP",
    )
    assert success is False
    assert log_details == {}


@respx.mock
async def test_run_invokes_callback(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(202, json={"logId": 4})
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json=[{"status": "COMPLETED", "runTime": 65432}]
        )
    )
    received: list[TaskChainRunResult] = []

    results = await client.task_chains.run(
        chains=[{"entity": "CHAIN", "space": "SP"}],
        on_result=received.append,
    )
    expected: TaskChainRunResult = {
        "entity": "CHAIN",
        "space": "SP",
        "isCompleted": True,
        "runtime": 65,
    }
    assert results == [expected]
    assert received == [expected]


@respx.mock
async def test_run_reports_failures(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(400)
    )
    results = await client.task_chains.run(
        chains=[{"entity": "CHAIN", "space": "SP"}]
    )
    assert results == [
        {
            "entity": "CHAIN",
            "space": "SP",
            "isCompleted": False,
            "runtime": None,
        }
    ]
