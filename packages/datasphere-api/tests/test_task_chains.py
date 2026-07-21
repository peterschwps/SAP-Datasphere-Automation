import asyncio

import httpx
import pytest
import respx

from datasphere_api import (
    DatasphereClient,
    TaskChainCancelled,
    TaskChainTimeout,
)


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
    assert log_details["logId"] == 3


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
    assert log_details["logId"] == 4


@respx.mock
async def test_run_timeout_retains_log_id(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(202, json={"logId": 5})
    )
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json=[{"status": "RUNNING", "runTime": 1000}]
        )
    )

    with pytest.raises(TaskChainTimeout) as error:
        await client.task_chains.run(
            "CHAIN",
            "SP",
            timeout_seconds=0.001,
        )

    assert error.value.log_id == 5


@pytest.mark.parametrize(
    "timeout", [True, False, 0, -1, float("nan"), float("inf")]
)
@respx.mock
async def test_run_rejects_invalid_timeout_before_start(
    client: DatasphereClient,
    timeout: float,
) -> None:
    route = respx.post(
        path="/dwaas-core/tf/SP/taskchains/CHAIN/start"
    ).mock(return_value=httpx.Response(202, json={"logId": 6}))

    with pytest.raises(ValueError):
        await client.task_chains.run(
            "CHAIN",
            "SP",
            timeout_seconds=timeout,
        )

    assert route.called is False


@respx.mock
async def test_run_cancellation_retains_log_id(
    client: DatasphereClient,
) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(202, json={"logId": 7})
    )
    log_route = respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json=[{"status": "RUNNING", "runTime": 1000}]
        )
    )
    task = asyncio.create_task(client.task_chains.run("CHAIN", "SP"))
    while not log_route.called:
        await asyncio.sleep(0)

    task.cancel()

    with pytest.raises(TaskChainCancelled) as error:
        await task
    assert error.value.log_id == 7
