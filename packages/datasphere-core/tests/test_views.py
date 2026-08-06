import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
from datasphere_core import (
    CommandCancelledError,
    CommandContext,
    UnexpectedResponseError,
)
from datasphere_core.commands import views as views_commands
from datasphere_core.commands.shared import persistence, task_logs
from datasphere_core.commands.shared.persistence import is_persisted
from datasphere_core.commands.views import (
    create_view_partitioning,
    delete_view_partitioning,
    find_view_attribute_matches_batch,
    find_view_persistence_candidates,
    lock_view_partitions,
    persist_view,
    persist_view_batch,
    unlock_view_partitions,
    unpersist_view,
)
from datasphere_core.models.common import (
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
)
from datasphere_core.models.views import (
    CreateViewPartitioningRequest,
    CreateViewPartitioningStatus,
    DeleteViewPartitioningRequest,
    DeleteViewPartitioningStatus,
    FindViewAttributeMatchesBatchRequest,
    FindViewPersistenceCandidatesRequest,
    FindViewPersistenceCandidatesStatus,
    LockViewPartitionsRequest,
    LockViewPartitionsStatus,
    PersistViewBatchRequest,
    PersistViewRequest,
    PersistViewStatus,
    UnlockViewPartitionsRequest,
    UnlockViewPartitionsStatus,
    UnpersistViewRequest,
    UnpersistViewStatus,
    ViewPersistenceCandidate,
)

SEARCH_PATH = "/deepsea/repository/search/$all"
DESIGN_OBJECTS_PATH = "/deepsea/repository/SPACE_A/designObjects"
EXECUTE_PATH = "/dwaas-core/tf/directexecute"
MONITOR_PATH = "/dwaas-core/monitor/SPACE_A/persistedViews/VIEW_A"
PARTITIONING_PATH = "/dwaas-core/partitioning/SPACE_A/persistedViews/VIEW_A"
TASK_LOGS_PATH = "/dwaas-core/tf/SPACE_A/logs"
ANALYZER_START_PATH = "/dwaas-core/advisor/SPACE_A/execute/VIEW_A"


def _view(view_id: str, name: str, space: str) -> dict[str, Any]:
    """
    Builds the repository entry of one view.
    """
    return {
        "id": view_id,
        "name": name,
        "space_name": space,
        "business_name": f"{name} Business",
    }


def _search_route(views: list[dict[str, Any]]) -> respx.Route:
    """
    Mocks the repository search that discovers the views.
    """
    return respx.get(path=SEARCH_PATH).mock(
        return_value=httpx.Response(200, json={"value": views})
    )


def _execute_route(log_id: int | None = 5) -> respx.Route:
    """
    Mocks the endpoint that starts an activity on a view. A run without a log
    ID is one the tenant refused.
    """
    if log_id is None:
        return respx.post(path=EXECUTE_PATH).mock(
            return_value=httpx.Response(400)
        )
    return respx.post(path=EXECUTE_PATH).mock(
        return_value=httpx.Response(202, json={"taskLogId": log_id})
    )


def _log_route(
    *statuses: str,
    log_id: int = 5,
    runtime: int | None = 2400,
) -> respx.Route:
    """
    Mocks the extended task log of one run, reporting the statuses in order and
    repeating the last one.
    """
    remaining = list(statuses)

    def respond(request: httpx.Request) -> httpx.Response:
        status = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        details: dict[str, Any] = {"status": status}
        if runtime is not None:
            details["runTime"] = runtime
        return httpx.Response(200, json={"logDetails": details})

    return respx.get(
        path=f"/dwaas-core/tf/SPACE_A/extendedlogs/{log_id}"
    ).mock(side_effect=respond)


def _monitor_route(persistency: str | None = "Persisted") -> respx.Route:
    """
    Mocks the monitor of one view. A view without a persistency answers with
    nothing the caller can use.
    """
    return respx.get(path=MONITOR_PATH).mock(
        return_value=httpx.Response(
            200,
            json={} if persistency is None else {
                "dataPersistency": persistency
            },
        )
    )


def _analyzer_start_route(
    log_id: int | None = 88,
    *,
    already_running: bool = False,
) -> respx.Route:
    """
    Mocks the endpoint that starts the view analyzer.
    """
    # A run that was already going is refused with its own status code
    if already_running:
        return respx.post(path=ANALYZER_START_PATH).mock(
            return_value=httpx.Response(
                409, json={"error": "taskAlreadyRunning"}
            )
        )

    payload: dict[str, Any] = {"status": "Running"}
    if log_id is not None:
        payload["logId"] = log_id
    return respx.post(path=ANALYZER_START_PATH).mock(
        return_value=httpx.Response(202, json=payload)
    )


def _task_logs_route(*polls: list[dict[str, Any]]) -> respx.Route:
    """
    Mocks the task logs of one view, answering the polls in order and
    repeating the last one.
    """
    remaining = list(polls)

    def respond(request: httpx.Request) -> httpx.Response:
        logs = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return httpx.Response(200, json={"logs": logs})

    return respx.get(path=TASK_LOGS_PATH).mock(side_effect=respond)


def _entity(view: str, score: int = 5) -> dict[str, Any]:
    """
    Builds one analyzer entity that reaches the given candidate score.
    """
    return {
        "entity": view,
        "space": "SPACE_B",
        "persistencyCandidateScore": score,
    }


def _analyzer_result_route(
    log_id: int,
    entities: list[dict[str, Any]],
) -> respx.Route:
    """
    Mocks the result of one completed analyzer run.
    """
    return respx.get(
        path=f"/dwaas-core/advisor/SPACE_A/result/{log_id}"
    ).mock(
        return_value=httpx.Response(200, json={"entityStats": entities})
    )


@respx.mock
async def test_persist_view_maps_a_completed_run(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a completed persistence run is mapped to its fields.
    """
    start = _execute_route()
    _log_route("COMPLETED")

    result = await persist_view(
        context(),
        PersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    # The millisecond runtime is rounded to whole seconds
    assert result.status is PersistViewStatus.COMPLETED
    assert result.log_status == "COMPLETED"
    assert result.log_id == "5"
    assert result.runtime_seconds == 2

    # Persisting is one activity of the shared execute endpoint
    assert json.loads(start.calls.last.request.content)["activity"] == (
        "PERSIST"
    )


@respx.mock
async def test_persist_view_polls_until_the_run_leaves_running(
    context: Callable[..., CommandContext],
    monkeypatch,
) -> None:
    """
    Checks that a running job is polled until it reaches a final status.
    """
    monkeypatch.setattr(task_logs, "POLL_INTERVAL_SECONDS", 0)
    _execute_route()
    _log_route("RUNNING", "RUNNING", "FAILED")

    result = await persist_view(
        context(),
        PersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert result.status is PersistViewStatus.FAILED
    assert result.log_status == "FAILED"


@respx.mock
async def test_persist_view_maps_a_timeout_to_its_status(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a persistence timeout becomes a status, not an exception.
    """
    _execute_route(log_id=17)
    _log_route("RUNNING", log_id=17)

    result = await persist_view(
        context(),
        PersistViewRequest(
            view="VIEW_A",
            space="SPACE_A",
            timeout_seconds=0.01,
        ),
    )

    assert result.status is PersistViewStatus.TIMED_OUT
    assert result.log_id == "17"


@respx.mock
async def test_persist_view_reports_a_run_that_never_started(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a persistence run without a log ID never started.
    """
    _execute_route(log_id=None)

    result = await persist_view(
        context(),
        PersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert result.status is PersistViewStatus.START_FAILED


@respx.mock
async def test_unpersist_view_reports_an_already_absent_persistence(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a view without persisted data is already absent.
    """
    _monitor_route("NotPersisted")
    start = _execute_route()

    result = await unpersist_view(
        context(),
        UnpersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    # Nothing had to be removed, so no run was started at all
    assert result.status is UnpersistViewStatus.ALREADY_ABSENT
    assert result.status.outcome == "skipped"
    assert not start.called


@respx.mock
async def test_unpersist_view_removes_persisted_data(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a persisted view is unpersisted through the execute endpoint.
    """
    _monitor_route()
    start = _execute_route()
    _log_route("COMPLETED")

    result = await unpersist_view(
        context(),
        UnpersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert result.status is UnpersistViewStatus.COMPLETED
    assert json.loads(start.calls.last.request.content)["activity"] == (
        "REMOVE_PERSISTED_DATA"
    )


@respx.mock
async def test_persist_view_batch_keeps_order_and_summarizes(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a persistence batch keeps the order and summarizes it.
    """
    progress: list[CommandProgress] = []

    # VIEW_B fails, every other view completes
    def start(request: httpx.Request) -> httpx.Response:
        view = json.loads(request.content)["objectId"]
        return httpx.Response(
            202, json={"taskLogId": 9 if view == "VIEW_B" else 1}
        )

    respx.post(path=EXECUTE_PATH).mock(side_effect=start)
    _log_route("FAILED", log_id=9, runtime=None)
    _log_route("COMPLETED", log_id=1, runtime=1000)

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    result = await persist_view_batch(
        context(progress_callback=report),
        PersistViewBatchRequest(
            requests=tuple(
                PersistViewRequest(view=view, space="SPACE_A")
                for view in ("VIEW_A", "VIEW_B", "VIEW_C")
            ),
            max_concurrency=2,
        ),
    )

    assert [item.view for item in result.results] == [
        "VIEW_A",
        "VIEW_B",
        "VIEW_C",
    ]
    assert result.summary == BatchSummary(
        total=3,
        succeeded=2,
        failed=1,
        skipped=0,
        timed_out=0,
    )

    # One failed view makes the whole batch end in the failed phase
    assert progress[-1].phase is CommandProgressPhase.FAILED


@respx.mock
async def test_find_persistence_candidates_keeps_matching_scores(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that only entities reaching the score become candidates.
    """
    _task_logs_route([{"logId": 88, "status": "COMPLETED"}])
    _analyzer_start_route()
    _analyzer_result_route(
        88,
        [
            {
                "entity": "VIEW_MATCH",
                "space": "SPACE_B",
                "businessName": "Match",
                "isPersisted": False,
                "persistencyCandidateScore": 10,
            },
            {
                "entity": "VIEW_OTHER",
                "space": "SPACE_B",
                "persistencyCandidateScore": 3,
            },
        ],
    )

    result = await find_view_persistence_candidates(
        context(),
        FindViewPersistenceCandidatesRequest(
            view="VIEW_A",
            space="SPACE_A",
            minimum_candidate_score=10,
        ),
    )

    assert result.status is FindViewPersistenceCandidatesStatus.COMPLETED
    assert result.log_id == "88"
    assert result.candidates == (
        ViewPersistenceCandidate(
            view="VIEW_MATCH",
            space="SPACE_B",
            score=10,
            business_name="Match",
            is_persisted=False,
        ),
    )


@respx.mock
async def test_find_persistence_candidates_keeps_higher_scores(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that the candidate score is a threshold, not an exact match.
    """
    _task_logs_route([{"logId": 88, "status": "COMPLETED"}])
    _analyzer_start_route()
    _analyzer_result_route(
        88,
        [
            {
                "entity": "VIEW_ABOVE",
                "space": "SPACE_B",
                "persistencyCandidateScore": 9,
            },
            {
                "entity": "VIEW_AT",
                "space": "SPACE_B",
                "persistencyCandidateScore": 7,
            },
            {
                "entity": "VIEW_BELOW",
                "space": "SPACE_B",
                "persistencyCandidateScore": 6,
            },
        ],
    )

    result = await find_view_persistence_candidates(
        context(),
        FindViewPersistenceCandidatesRequest(
            view="VIEW_A",
            space="SPACE_A",
            minimum_candidate_score=7,
        ),
    )

    # The score is a threshold, so anything at or above it is a candidate
    assert [candidate.view for candidate in result.candidates] == [
        "VIEW_ABOVE",
        "VIEW_AT",
    ]

    # Every candidate carries the score it actually reached, not the threshold
    assert [candidate.score for candidate in result.candidates] == [9, 7]


@respx.mock
async def test_find_persistence_candidates_drops_entities_without_score(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that an entity without a score is dropped, not compared.
    """
    _task_logs_route([{"logId": 88, "status": "COMPLETED"}])
    _analyzer_start_route()
    _analyzer_result_route(
        88,
        [
            {"entity": "VIEW_NO_SCORE", "space": "SPACE_B"},
            {
                "entity": "VIEW_MATCH",
                "space": "SPACE_B",
                "persistencyCandidateScore": 10,
            },
        ],
    )

    result = await find_view_persistence_candidates(
        context(),
        FindViewPersistenceCandidatesRequest(
            view="VIEW_A",
            space="SPACE_A",
        ),
    )

    # A missing score drops the entity instead of raising on the comparison
    assert [candidate.view for candidate in result.candidates] == [
        "VIEW_MATCH"
    ]
    assert result.status is FindViewPersistenceCandidatesStatus.COMPLETED


@respx.mock
async def test_find_persistence_candidates_reraises_a_cancellation(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a cancelled analysis is re-raised with its log ID.
    """
    calls = 0

    # The first call snapshots the existing runs, the cancellation has to
    # happen after the analyzer started
    def poll(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise asyncio.CancelledError
        return httpx.Response(200, json={"logs": []})

    respx.get(path=TASK_LOGS_PATH).mock(side_effect=poll)
    _analyzer_start_route(log_id=7)

    with pytest.raises(CommandCancelledError) as error:
        await find_view_persistence_candidates(
            context(),
            FindViewPersistenceCandidatesRequest(
                view="VIEW_A",
                space="SPACE_A",
            ),
        )

    # The log ID lets the caller follow the analysis that still runs remotely
    assert error.value.log_id == "7"


@respx.mock
async def test_view_analyzer_follows_the_log_id_of_its_own_run(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a newer foreign run does not divert the analysis.
    """
    _task_logs_route(
        [{"status": "RUNNING", "logId": 19}],
        [
            {"status": "COMPLETED", "logId": 21},
            {"status": "COMPLETED", "logId": 20},
        ],
    )
    _analyzer_start_route(log_id=20)

    # Both runs have a result, only one of them belongs to this analysis
    _analyzer_result_route(20, [_entity("OWN")])
    _analyzer_result_route(21, [_entity("FOREIGN")])

    result = await find_view_persistence_candidates(
        context(),
        FindViewPersistenceCandidatesRequest(
            view="VIEW_A",
            space="SPACE_A",
            minimum_candidate_score=5,
        ),
    )

    # Log 21 is newer but belongs to someone else
    assert result.log_id == "20"
    assert [candidate.view for candidate in result.candidates] == ["OWN"]
    assert result.status is FindViewPersistenceCandidatesStatus.COMPLETED


@respx.mock
async def test_view_analyzer_waits_for_a_log_that_appears_late(
    context: Callable[..., CommandContext],
    monkeypatch,
) -> None:
    """
    Checks that an empty poll is retried instead of ending the analysis.
    """
    monkeypatch.setattr(views_commands, "ANALYZER_POLL_INTERVAL_SECONDS", 0)
    _task_logs_route([], [], [{"status": "COMPLETED", "logId": 41}])
    _analyzer_start_route(log_id=41)
    _analyzer_result_route(41, [_entity("VIEW_B")])

    result = await find_view_persistence_candidates(
        context(),
        FindViewPersistenceCandidatesRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert result.log_id == "41"


@respx.mock
async def test_a_running_analysis_reports_its_runtime(
    context: Callable[..., CommandContext],
    monkeypatch,
    caplog,
) -> None:
    """
    Checks that an analysis that keeps running says so while it is waited
    for.
    """
    monkeypatch.setattr(views_commands, "ANALYZER_POLL_INTERVAL_SECONDS", 0)

    # An interval of zero reports on every poll, so the message appears
    # without waiting for it
    monkeypatch.setattr(task_logs, "ANNOUNCE_INTERVAL_SECONDS", 0)
    _task_logs_route(
        [],
        [{"status": "RUNNING", "logId": 41}],
        [{"status": "COMPLETED", "logId": 41}],
    )
    _analyzer_start_route(log_id=41)
    _analyzer_result_route(41, [_entity("VIEW_B")])

    with caplog.at_level(logging.DEBUG, logger="datasphere_core"):
        await find_view_persistence_candidates(
            context(),
            FindViewPersistenceCandidatesRequest(
                view="VIEW_A",
                space="SPACE_A",
            ),
        )

    messages = [record.getMessage() for record in caplog.records]
    assert (
        "Waiting for view 'VIEW_A' to finish. Current runtime 00:00:00."
        in messages
    )


@respx.mock
async def test_view_analyzer_reports_a_terminal_status_without_result(
    context: Callable[..., CommandContext],
    monkeypatch,
) -> None:
    """
    Checks that a cancelled run yields its log ID and no candidates.
    """
    monkeypatch.setattr(views_commands, "ANALYZER_POLL_INTERVAL_SECONDS", 0)
    _task_logs_route([], [{"status": "CANCELLED", "logId": 32}])
    _analyzer_start_route(log_id=32)

    result = await find_view_persistence_candidates(
        context(),
        FindViewPersistenceCandidatesRequest(view="VIEW_A", space="SPACE_A"),
    )

    # Without entities the analysis counts as failed, but the run is traceable
    assert result.log_id == "32"
    assert result.candidates == ()
    assert result.status is FindViewPersistenceCandidatesStatus.FAILED


@respx.mock
async def test_view_analyzer_timeout_keeps_the_discovered_log_id(
    context: Callable[..., CommandContext],
    monkeypatch,
) -> None:
    """
    Checks that a timeout reports the log ID the analysis had found.
    """
    monkeypatch.setattr(views_commands, "ANALYZER_POLL_INTERVAL_SECONDS", 0)
    _task_logs_route([], [{"status": "RUNNING", "logId": 55}])
    _analyzer_start_route(already_running=True)

    result = await find_view_persistence_candidates(
        context(),
        FindViewPersistenceCandidatesRequest(
            view="VIEW_A",
            space="SPACE_A",
            timeout_seconds=0.01,
        ),
    )

    # The start returned no ID, so only polling could discover it
    assert result.status is FindViewPersistenceCandidatesStatus.TIMED_OUT
    assert result.log_id == "55"


@respx.mock
async def test_find_attribute_matches_batch_discovers_every_view(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a batch without explicit requests searches every view.
    """
    _search_route(
        [
            _view("ID_1", "VIEW_A", "SPACE_A"),
            _view("ID_2", "VIEW_B", "SPACE_A"),
        ]
    )

    # Only the first view carries a readable CSN at all
    def attributes(request: httpx.Request) -> httpx.Response:
        if request.url.params["ids"] != "ID_1":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "#repairedCsn": {
                            "definitions": {
                                "VIEW_A": {
                                    "elements": {
                                        "FISCYEAR": {},
                                        "COMPANY_CODE": {},
                                    }
                                }
                            }
                        }
                    }
                ]
            },
        )

    respx.get(path=DESIGN_OBJECTS_PATH).mock(side_effect=attributes)

    result = await find_view_attribute_matches_batch(
        context(),
        FindViewAttributeMatchesBatchRequest(substring="year"),
    )

    # The search is case insensitive by default
    assert result.results[0].attributes == ("FISCYEAR",)

    # An unreadable CSN yields no attributes instead of raising
    assert result.results[1].attributes == ()
    assert result.summary == BatchSummary(
        total=2,
        succeeded=1,
        failed=1,
        skipped=0,
        timed_out=0,
    )


@respx.mock
async def test_every_partitioning_request_carries_its_own_identifier(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that two requests of one command never share a request ID.
    """
    read = respx.get(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "ranges": [],
                "partitioningColumns": {"FISCYEAR": {"type": "cds.String"}},
            },
        )
    )
    write = respx.post(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(201)
    )

    await create_view_partitioning(
        context(),
        CreateViewPartitioningRequest(
            view="VIEW_A",
            space="SPACE_A",
            attribute="FISCYEAR",
            start_year=2020,
            end_year=2023,
        ),
    )

    # The tenant matches its own logs by this ID, so a reused one is useless
    identifiers = {
        route.calls.last.request.headers["x-request-id"]
        for route in (read, write)
    }
    assert len(identifiers) == 2


@respx.mock
async def test_create_partitioning_builds_the_requested_year_range(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that the year range becomes one partition per year.
    """
    respx.get(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "ranges": [],
                "partitioningColumns": {"FISCYEAR": {"type": "cds.String"}},
            },
        )
    )
    write = respx.post(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(201)
    )

    result = await create_view_partitioning(
        context(),
        CreateViewPartitioningRequest(
            view="VIEW_A",
            space="SPACE_A",
            attribute="FISCYEAR",
            start_year=2020,
            end_year=2023,
        ),
    )

    # The last year is only the upper bound of the preceding range
    written = json.loads(write.calls.last.request.content)
    ranges = written["ranges"]
    assert [partition["low"]["value"] for partition in ranges] == [
        "2020",
        "2021",
    ]
    assert [partition["high"]["value"] for partition in ranges] == [
        "2021",
        "2022",
    ]
    assert written["column"] == "FISCYEAR"
    assert result.status is CreateViewPartitioningStatus.CREATED


@respx.mock
async def test_create_partitioning_maps_an_existing_partitioning(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that an existing partitioning is kept instead of replaced.
    """
    respx.get(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "ranges": [{"id": 1}],
                "partitioningColumns": {"FISCYEAR": {"type": "cds.String"}},
            },
        )
    )
    write = respx.post(path=PARTITIONING_PATH)

    result = await create_view_partitioning(
        context(),
        CreateViewPartitioningRequest(
            view="VIEW_A",
            space="SPACE_A",
            attribute="FISCYEAR",
            start_year=2020,
            end_year=2023,
        ),
    )

    assert result.status is CreateViewPartitioningStatus.ALREADY_EXISTS
    assert result.status.outcome == "skipped"
    assert not write.called


@respx.mock
async def test_create_partitioning_rejects_a_non_string_column(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that a column of another type is refused before writing.
    """
    respx.get(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "ranges": [],
                "partitioningColumns": {"FISCYEAR": {"type": "cds.Integer"}},
            },
        )
    )
    write = respx.post(path=PARTITIONING_PATH)

    result = await create_view_partitioning(
        context(),
        CreateViewPartitioningRequest(
            view="VIEW_A",
            space="SPACE_A",
            attribute="FISCYEAR",
            start_year=2020,
            end_year=2023,
        ),
    )

    # Only a string column can carry a range partitioning
    assert result.status is CreateViewPartitioningStatus.INVALID_COLUMN
    assert not write.called


@respx.mock
async def test_delete_partitioning_maps_a_refusal_to_a_failure(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that only a removal the tenant confirmed counts as deleted.
    """
    respx.delete(path=PARTITIONING_PATH).mock(
        side_effect=[httpx.Response(200), httpx.Response(404)]
    )
    request = DeleteViewPartitioningRequest(view="VIEW_A", space="SPACE_A")

    deleted = await delete_view_partitioning(context(), request)
    refused = await delete_view_partitioning(context(), request)

    assert deleted.status is DeleteViewPartitioningStatus.DELETED
    assert refused.status is DeleteViewPartitioningStatus.FAILED


@respx.mock
async def test_lock_and_unlock_partitions_map_their_outcomes(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that lock and unlock outcomes are mapped to their statuses.
    """
    def _partitioning(*years: int) -> dict[str, Any]:
        """
        Builds a partitioning with one unlocked partition per year.
        """
        return {
            "remoteSourceName": "SOURCE",
            "objectName": "OBJECT",
            "numParallelPartitions": 1,
            "ranges": [
                {"low": {"value": str(year)}, "locked": False}
                for year in years
            ],
            "column": "YEAR",
            "columnType": "INTEGER",
            "runtimeDataCalculation": False,
            "type": "RANGE",
        }

    # The lock reads a partitioned view, the unlock one without partitions
    respx.get(path=PARTITIONING_PATH).mock(
        side_effect=[
            httpx.Response(200, json=_partitioning(2021, 2022, 2023)),
            httpx.Response(200, json=_partitioning()),
        ]
    )
    write = respx.post(path=PARTITIONING_PATH).mock(
        return_value=httpx.Response(201)
    )

    locked = await lock_view_partitions(
        context(),
        LockViewPartitionsRequest(
            view="VIEW_A",
            space="SPACE_A",
            until_year=2022,
        ),
    )
    unlocked = await unlock_view_partitions(
        context(),
        UnlockViewPartitionsRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert locked.status is LockViewPartitionsStatus.LOCKED
    assert unlocked.status is UnlockViewPartitionsStatus.NO_PARTITIONS
    assert unlocked.status.outcome == "skipped"

    # Only the years up to the requested one are locked
    written = json.loads(write.calls.last.request.content)
    assert [partition["locked"] for partition in written["ranges"]] == [
        True,
        True,
        False,
    ]


@respx.mock
async def test_is_persisted_gives_up_after_three_silent_answers(
    context: Callable[..., CommandContext],
    monkeypatch,
) -> None:
    """
    Checks that a monitor that never answers becomes an error.
    """
    monkeypatch.setattr(persistence, "MONITOR_RETRY_INTERVAL_SECONDS", 0)
    monitor = _monitor_route(None)

    with pytest.raises(UnexpectedResponseError, match="VIEW_A"):
        await is_persisted(context(), "VIEW_A", "SPACE_A")

    # A silent monitor is retried, never taken as 'not persisted'
    assert len(monitor.calls) == 3


def test_requests_reject_unusable_values() -> None:
    """
    Checks that an invalid timeout and an inverted year range fail.
    """
    with pytest.raises(ValueError, match="Timeout"):
        PersistViewRequest(view="A", space="S", timeout_seconds=0)
    with pytest.raises(ValueError, match="Start year"):
        CreateViewPartitioningRequest(
            view="A",
            space="S",
            attribute="FISCYEAR",
            start_year=2023,
            end_year=2020,
        )
