import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from datasphere_core import (
    CommandContext,
    http_logging_hooks,
    is_http_logging,
    start_http_logging,
    stop_http_logging,
)
from datasphere_core.commands.task_chains import run_task_chain
from datasphere_core.http_logging import record
from datasphere_core.models.task_chains import RunTaskChainRequest

START_PATH = "/dwaas-core/tf/SPACE_A/taskchains/CHAIN_A/start"
LOGS_PATH = "/dwaas-core/tf/SPACE_A/logs"


def _events(path: Path) -> list[dict[str, Any]]:
    """
    Reads a log file back as one dictionary per event.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _first(events: list[dict[str, Any]], event: str) -> dict[str, Any]:
    """
    Returns the first event of one kind.
    """
    return next(item for item in events if item["event"] == event)


def test_logging_stays_off_until_it_is_started(tmp_path: Path) -> None:
    """
    Checks that an unstarted log records nothing and hooks nothing.
    """
    assert not is_http_logging()
    assert http_logging_hooks() == {}

    # Record without a log and expect silence instead of an error
    record("http_request", method="GET")
    assert list(tmp_path.iterdir()) == []


def test_every_event_is_one_json_line(tmp_path: Path) -> None:
    """
    Checks that the log is readable line by line and keeps its order.
    """
    path = start_http_logging(tmp_path / "http.jsonl")
    record("http_request", method="GET", url="https://tenant.example/a")
    record("http_response", status_code=200)
    stop_http_logging()

    events = _events(path)
    assert [event["event"] for event in events] == [
        "run_started",
        "http_request",
        "http_response",
        "run_finished",
    ]

    # Count along, because a reader needs the order and a clock that ties or
    # jumps must not decide it
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert len({event["run_id"] for event in events}) == 1
    assert events[-1]["event_count"] == 4


def test_every_event_is_written_right_away(tmp_path: Path) -> None:
    """
    Checks that the log survives a run that never finishes.
    """
    path = start_http_logging(tmp_path / "http.jsonl")
    record("http_request", method="GET")

    # Read while the log is still open, because that is what makes an
    # interrupted run readable
    events = _events(path)
    assert [event["event"] for event in events] == [
        "run_started",
        "http_request",
    ]


def test_a_started_log_replaces_the_previous_one(tmp_path: Path) -> None:
    """
    Checks that the file holds exactly the run that wrote it last.
    """
    path = start_http_logging(tmp_path / "http.jsonl")
    record("http_request", method="GET", url="https://tenant.example/first")
    first_run = _first(_events(path), "run_started")["run_id"]

    start_http_logging(path)
    stop_http_logging()

    events = _events(path)
    assert not any("first" in json.dumps(event) for event in events)
    assert _first(events, "run_started")["run_id"] != first_run


@respx.mock
async def test_the_log_records_a_request_and_its_response(
    session: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    """
    Checks that both sides of one call are recorded and tied together.
    """
    path = start_http_logging(tmp_path / "http.jsonl")
    session.event_hooks = http_logging_hooks()
    respx.post(path=START_PATH).mock(
        return_value=httpx.Response(202, json={"logId": 123})
    )

    await session.post(START_PATH, json={"objectId": "CHAIN_A"})
    stop_http_logging()

    events = _events(path)
    request = _first(events, "http_request")
    response = _first(events, "http_response")

    assert request["method"] == "POST"
    assert request["path"] == START_PATH
    assert request["body"] == {"objectId": "CHAIN_A"}
    assert response["status_code"] == 202
    assert response["body"] == {"logId": 123}
    assert response["request_id"] == request["request_id"]
    assert response["duration_ms"] >= 0


@respx.mock
async def test_the_log_records_a_call_verbatim(
    session: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    """
    Checks that nothing is masked. The log is written to debug against the
    tenant, and a masked token or payload is what makes that impossible.
    """
    path = start_http_logging(tmp_path / "http.jsonl")
    session.event_hooks = http_logging_hooks()
    session.headers["Authorization"] = "Bearer an-access-token"
    respx.post(path=START_PATH).mock(
        return_value=httpx.Response(
            200,
            json={"refresh_token": "a-refresh-token"},
            headers={"set-cookie": "session=a-session-cookie"},
        )
    )

    await session.post(START_PATH, json={"secret": "a-payload-secret"})
    stop_http_logging()

    events = _events(path)
    request = _first(events, "http_request")
    response = _first(events, "http_response")

    assert request["headers"]["authorization"] == "Bearer an-access-token"
    assert request["body"] == {"secret": "a-payload-secret"}
    assert response["headers"]["set-cookie"] == "session=a-session-cookie"
    assert response["body"] == {"refresh_token": "a-refresh-token"}


@respx.mock
async def test_a_command_reaches_the_log_through_its_client(
    context: Callable[..., CommandContext],
    session: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    """
    Checks that every request of one command is recorded.
    """
    path = start_http_logging(tmp_path / "http.jsonl")
    session.event_hooks = http_logging_hooks()
    respx.post(path=START_PATH).mock(
        return_value=httpx.Response(202, json={"logId": 123})
    )
    respx.get(path=LOGS_PATH).mock(
        return_value=httpx.Response(200, json=[{"status": "COMPLETED"}])
    )

    await run_task_chain(
        context(),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
    )
    stop_http_logging()

    events = _events(path)
    paths = [
        event["path"] for event in events if event["event"] == "http_request"
    ]
    assert START_PATH in paths
    assert LOGS_PATH in paths

    # Keep the tenant identifier where a command sends one, so the log can
    # be matched against the tenant logs
    start = _first(events, "http_request")
    assert start["tenant_request_id"]


@respx.mock
async def test_a_transport_error_leaves_a_request_unanswered(
    session: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    """
    Checks the known limit of the hooks: a request that never got an answer
    stands alone in the log.
    """
    path = start_http_logging(tmp_path / "http.jsonl")
    session.event_hooks = http_logging_hooks()
    respx.get(path=LOGS_PATH).mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(httpx.ConnectError):
        await session.get(LOGS_PATH)
    stop_http_logging()

    events = _events(path)
    assert len([e for e in events if e["event"] == "http_request"]) == 1
    assert not [e for e in events if e["event"] == "http_response"]


@respx.mock
async def test_a_body_that_is_no_text_does_not_break_the_log(
    session: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    """
    Checks that a binary answer is summarized instead of written down.
    """
    path = start_http_logging(tmp_path / "http.jsonl")
    session.event_hooks = http_logging_hooks()
    respx.get(path=LOGS_PATH).mock(
        return_value=httpx.Response(
            200,
            content=b"\xff\xfe\x00",
            headers={"content-type": "application/octet-stream"},
        )
    )

    await session.get(LOGS_PATH)
    stop_http_logging()

    response = _first(_events(path), "http_response")
    assert response["body"] == {"binary_bytes": 3}
    assert response["body_bytes"] == 3


@respx.mock
async def test_a_broken_log_does_not_break_the_request(
    session: httpx.AsyncClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that a log failing mid-run switches itself off quietly.
    """
    from datasphere_core import http_logging

    start_http_logging(tmp_path / "http.jsonl")
    session.event_hooks = http_logging_hooks()
    respx.get(path=LOGS_PATH).mock(
        return_value=httpx.Response(200, json=[{"status": "COMPLETED"}])
    )

    current = http_logging._current
    assert current is not None
    monkeypatch.setattr(current, "_file", _FailingFile())

    response = await session.get(LOGS_PATH)
    assert response.status_code == 200


class _FailingFile:
    """
    Stands in for a log file that cannot be written to.
    """

    def write(self, text: str) -> int:
        raise OSError("disk is full")

    def flush(self) -> None:
        raise OSError("disk is full")

    def close(self) -> None:
        raise OSError("disk is full")
