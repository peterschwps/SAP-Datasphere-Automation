import httpx
import pytest
import respx

from datasphere_api import DatasphereClient


@respx.mock
async def test_start_returns_the_task_log_id(
    client: DatasphereClient,
) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(202, json={"logId": 3})
    )

    assert await client.task_chains.start("CHAIN", "SP") == 3


@respx.mock
async def test_start_reports_a_refused_run(client: DatasphereClient) -> None:
    respx.post(path="/dwaas-core/tf/SP/taskchains/CHAIN/start").mock(
        return_value=httpx.Response(400)
    )

    # Without a log ID the caller knows the run never reached Datasphere
    assert await client.task_chains.start("CHAIN", "SP") is None


@pytest.mark.parametrize("status", ["COMPLETED", "FAILED"])
@respx.mock
async def test_get_log_returns_the_latest_entry(
    client: DatasphereClient,
    status: str,
) -> None:
    respx.get(path="/dwaas-core/tf/SP/logs").mock(
        return_value=httpx.Response(
            200, json=[{"status": status, "runTime": 65432}]
        )
    )

    log = await client.task_chains.get_log(3, "SP")

    assert log["status"] == status
    assert log["runTime"] == 65432
