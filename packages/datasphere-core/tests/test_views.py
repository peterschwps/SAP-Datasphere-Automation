import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from datasphere_api import (
    DatasphereClient,
)
from datasphere_core import CommandCancelledError, CommandContext, runs
from datasphere_core.commands import views as views_commands
from datasphere_core.commands.views import (
    create_view_partitioning,
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


def _client(**views: Any) -> DatasphereClient:
    """
    Builds a client whose view resource exposes the supplied functions.
    """
    return cast(
        DatasphereClient,
        SimpleNamespace(views=SimpleNamespace(**views)),
    )


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


def _run(*statuses: str, log_id: int | None = 5) -> dict[str, Any]:
    """
    Builds a client whose persistence run reports the given statuses in order.
    """
    remaining = list(statuses)

    async def start_persistence(view: str, space: str) -> int | None:
        return log_id

    async def start_persistence_removal(view: str, space: str) -> int | None:
        return log_id

    async def get_extended_log(task_log: int, space: str) -> dict[str, Any]:
        status = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return {"status": status, "runTime": 2400}

    async def get_monitor_details(view: str, space: str) -> dict[str, Any]:
        return {"dataPersistency": "Persisted"}

    return {
        "start_persistence": start_persistence,
        "start_persistence_removal": start_persistence_removal,
        "get_extended_log": get_extended_log,
        "get_monitor_details": get_monitor_details,
    }


async def test_persist_view_maps_a_completed_run() -> None:
    """
    Checks that a completed persistence run is mapped to its fields.
    """
    result = await persist_view(
        CommandContext(client=_client(**_run("COMPLETED"))),
        PersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    # The millisecond runtime is rounded to whole seconds
    assert result.status is PersistViewStatus.COMPLETED
    assert result.log_status == "COMPLETED"
    assert result.log_id == "5"
    assert result.runtime_seconds == 2


async def test_persist_view_polls_until_the_run_leaves_running(
    monkeypatch,
) -> None:
    """
    Checks that a running job is polled until it reaches a final status.
    """
    monkeypatch.setattr(runs, "POLL_INTERVAL_SECONDS", 0)

    result = await persist_view(
        CommandContext(client=_client(**_run("RUNNING", "RUNNING", "FAILED"))),
        PersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert result.status is PersistViewStatus.FAILED
    assert result.log_status == "FAILED"


async def test_persist_view_maps_a_timeout_to_its_status() -> None:
    """
    Checks that a persistence timeout becomes a status, not an exception.
    """
    result = await persist_view(
        CommandContext(client=_client(**_run("RUNNING", log_id=17))),
        PersistViewRequest(
            view="VIEW_A",
            space="SPACE_A",
            timeout_seconds=0.01,
        ),
    )

    assert result.status is PersistViewStatus.TIMED_OUT
    assert result.log_id == "17"


async def test_persist_view_reports_a_run_that_never_started() -> None:
    """
    Checks that a persistence run without a log ID never started.
    """
    async def start_persistence(view: str, space: str) -> int | None:
        return None

    result = await persist_view(
        CommandContext(client=_client(start_persistence=start_persistence)),
        PersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert result.status is PersistViewStatus.START_FAILED


async def test_unpersist_view_reports_an_already_absent_persistence() -> None:
    """
    Checks that a view without persisted data is already absent.
    """
    async def get_monitor_details(view: str, space: str) -> dict[str, Any]:
        return {"dataPersistency": "NotPersisted"}

    result = await unpersist_view(
        CommandContext(
            client=_client(get_monitor_details=get_monitor_details)
        ),
        UnpersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    # Nothing had to be removed, so no run was started at all
    assert result.status is UnpersistViewStatus.ALREADY_ABSENT
    assert result.status.outcome == "skipped"


async def test_persist_view_batch_keeps_order_and_summarizes() -> None:
    """
    Checks that a persistence batch keeps the order and summarizes it.
    """
    progress: list[CommandProgress] = []

    # VIEW_B fails, every other view completes
    async def start_persistence(view: str, space: str) -> int | None:
        return 9 if view == "VIEW_B" else 1

    async def get_extended_log(task_log: int, space: str) -> dict[str, Any]:
        if task_log == 9:
            return {"status": "FAILED"}
        return {"status": "COMPLETED", "runTime": 1000}

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    result = await persist_view_batch(
        CommandContext(
            client=_client(
                start_persistence=start_persistence,
                get_extended_log=get_extended_log,
            ),
            progress_callback=report,
        ),
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


def _analyzer(
    entities: list[dict[str, Any]],
    *,
    log_id: int = 88,
    status: str = "COMPLETED",
) -> dict[str, Any]:
    """
    Builds a client whose view analyzer reports one run with the given status.
    """
    async def get_task_logs(view: str, space: str) -> list[dict[str, Any]]:
        return [{"logId": log_id, "status": status}]

    async def start_view_analyzer(
        view: str,
        space: str,
    ) -> tuple[bool, int | None, bool]:
        return True, log_id, False

    async def get_view_analyzer_result(
        task_log: int,
        space: str,
    ) -> dict[str, Any]:
        return {"entityStats": entities}

    return {
        "get_task_logs": get_task_logs,
        "start_view_analyzer": start_view_analyzer,
        "get_view_analyzer_result": get_view_analyzer_result,
    }


async def test_find_persistence_candidates_keeps_matching_scores() -> None:
    """
    Checks that only entities reaching the score become candidates.
    """
    entities: list[dict[str, Any]] = [
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
            ]

    result = await find_view_persistence_candidates(
        CommandContext(client=_client(**_analyzer(entities))),
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


async def test_find_persistence_candidates_keeps_higher_scores() -> None:
    """
    Checks that the candidate score is a threshold, not an exact match.
    """
    entities: list[dict[str, Any]] = [
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
            ]

    result = await find_view_persistence_candidates(
        CommandContext(client=_client(**_analyzer(entities))),
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


async def test_find_persistence_candidates_drops_entities_without_score(
) -> None:
    """
    Checks that an entity without a score is dropped, not compared.
    """
    entities: list[dict[str, Any]] = [
                {"entity": "VIEW_NO_SCORE", "space": "SPACE_B"},
                {
                    "entity": "VIEW_MATCH",
                    "space": "SPACE_B",
                    "persistencyCandidateScore": 10,
                },
            ]

    result = await find_view_persistence_candidates(
        CommandContext(client=_client(**_analyzer(entities))),
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


async def test_find_persistence_candidates_reraises_a_cancellation() -> None:
    """
    Checks that a cancelled analysis is re-raised with its log ID.
    """
    calls = 0

    # The first call snapshots the existing runs, the cancellation has to
    # happen after the analyzer started
    async def get_task_logs(view: str, space: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise asyncio.CancelledError
        return []

    async def start_view_analyzer(
        view: str,
        space: str,
    ) -> tuple[bool, int | None, bool]:
        return True, 7, False

    with pytest.raises(CommandCancelledError) as error:
        await find_view_persistence_candidates(
            CommandContext(
                client=_client(
                    get_task_logs=get_task_logs,
                    start_view_analyzer=start_view_analyzer,
                )
            ),
            FindViewPersistenceCandidatesRequest(
                view="VIEW_A",
                space="SPACE_A",
            ),
        )

    # The log ID lets the caller follow the analysis that still runs remotely
    assert error.value.log_id == "7"


def _analyzer_logs(
    *polls: list[dict[str, Any]],
    started_log_id: int | None,
    already_running: bool = False,
) -> dict[str, Any]:
    """
    Builds a client whose task log answers one snapshot and then the polls.
    """
    remaining = list(polls)

    async def get_task_logs(view: str, space: str) -> list[dict[str, Any]]:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    async def start_view_analyzer(
        view: str,
        space: str,
    ) -> tuple[bool, int | None, bool]:
        return True, started_log_id, already_running

    async def get_view_analyzer_result(
        task_log: int,
        space: str,
    ) -> dict[str, Any]:
        return {"entityStats": [{"entity": str(task_log)}]}

    return {
        "get_task_logs": get_task_logs,
        "start_view_analyzer": start_view_analyzer,
        "get_view_analyzer_result": get_view_analyzer_result,
    }


async def test_view_analyzer_follows_the_log_id_of_its_own_run() -> None:
    """
    Checks that a newer foreign run does not divert the analysis.
    """
    result = await find_view_persistence_candidates(
        CommandContext(
            client=_client(
                **_analyzer_logs(
                    [{"status": "RUNNING", "logId": 19}],
                    [
                        {"status": "COMPLETED", "logId": 21},
                        {"status": "COMPLETED", "logId": 20},
                    ],
                    started_log_id=20,
                )
            )
        ),
        FindViewPersistenceCandidatesRequest(view="VIEW_A", space="SPACE_A"),
    )

    # Log 21 is newer but belongs to someone else
    assert result.log_id == "20"
    assert result.status is FindViewPersistenceCandidatesStatus.COMPLETED


async def test_view_analyzer_waits_for_a_log_that_appears_late(
    monkeypatch,
) -> None:
    """
    Checks that an empty poll is retried instead of ending the analysis.
    """
    monkeypatch.setattr(views_commands, "ANALYZER_POLL_INTERVAL_SECONDS", 0)

    result = await find_view_persistence_candidates(
        CommandContext(
            client=_client(
                **_analyzer_logs(
                    [],
                    [],
                    [{"status": "COMPLETED", "logId": 41}],
                    started_log_id=41,
                )
            )
        ),
        FindViewPersistenceCandidatesRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert result.log_id == "41"


async def test_view_analyzer_reports_a_terminal_status_without_result(
    monkeypatch,
) -> None:
    """
    Checks that a cancelled run yields its log ID and no candidates.
    """
    monkeypatch.setattr(views_commands, "ANALYZER_POLL_INTERVAL_SECONDS", 0)

    result = await find_view_persistence_candidates(
        CommandContext(
            client=_client(
                **_analyzer_logs(
                    [],
                    [{"status": "CANCELLED", "logId": 32}],
                    started_log_id=32,
                )
            )
        ),
        FindViewPersistenceCandidatesRequest(view="VIEW_A", space="SPACE_A"),
    )

    # Without entities the analysis counts as failed, but the run is traceable
    assert result.log_id == "32"
    assert result.candidates == ()
    assert result.status is FindViewPersistenceCandidatesStatus.FAILED


async def test_view_analyzer_timeout_keeps_the_discovered_log_id(
    monkeypatch,
) -> None:
    """
    Checks that a timeout reports the log ID the analysis had found.
    """
    monkeypatch.setattr(views_commands, "ANALYZER_POLL_INTERVAL_SECONDS", 0)

    result = await find_view_persistence_candidates(
        CommandContext(
            client=_client(
                **_analyzer_logs(
                    [],
                    [{"status": "RUNNING", "logId": 55}],
                    started_log_id=None,
                    already_running=True,
                )
            )
        ),
        FindViewPersistenceCandidatesRequest(
            view="VIEW_A",
            space="SPACE_A",
            timeout_seconds=0.01,
        ),
    )

    # The start returned no ID, so only polling could discover it
    assert result.status is FindViewPersistenceCandidatesStatus.TIMED_OUT
    assert result.log_id == "55"


async def test_find_attribute_matches_batch_discovers_every_view() -> None:
    """
    Checks that a batch without explicit requests searches every view.
    """
    async def get_all_views() -> list[dict[str, Any]]:
        return [
            _view("ID_1", "VIEW_A", "SPACE_A"),
            _view("ID_2", "VIEW_B", "SPACE_A"),
        ]

    # Only the first view has attributes at all
    async def get_view_attributes(
        view_id: str,
        view_name: str,
        space: str,
    ) -> list[str]:
        return ["FISCYEAR", "COMPANY_CODE"] if view_id == "ID_1" else []

    result = await find_view_attribute_matches_batch(
        CommandContext(
            client=_client(
                get_all_views=get_all_views,
                get_view_attributes=get_view_attributes,
            )
        ),
        FindViewAttributeMatchesBatchRequest(substring="year"),
    )

    # The search is case insensitive by default
    assert result.results[0].attributes == ("FISCYEAR",)
    assert result.results[1].attributes == ()
    assert result.summary == BatchSummary(
        total=2,
        succeeded=1,
        failed=1,
        skipped=0,
        timed_out=0,
    )


async def test_create_partitioning_builds_the_requested_year_range() -> None:
    """
    Checks that the year range becomes one partition per year.
    """
    written: list[dict[str, Any]] = []

    async def get_partitioning(view: str, space: str) -> dict[str, Any]:
        return {
            "ranges": [],
            "partitioningColumns": {"FISCYEAR": {"type": "cds.String"}},
        }

    async def set_partitioning(
        view: str,
        space: str,
        data: dict[str, Any],
    ) -> bool:
        written.append(data)
        return True

    result = await create_view_partitioning(
        CommandContext(
            client=_client(
                get_partitioning=get_partitioning,
                set_partitioning=set_partitioning,
            )
        ),
        CreateViewPartitioningRequest(
            view="VIEW_A",
            space="SPACE_A",
            attribute="FISCYEAR",
            start_year=2020,
            end_year=2023,
        ),
    )

    # The last year is only the upper bound of the preceding range
    ranges = written[0]["ranges"]
    assert [partition["low"]["value"] for partition in ranges] == [
        "2020",
        "2021",
    ]
    assert [partition["high"]["value"] for partition in ranges] == [
        "2021",
        "2022",
    ]
    assert written[0]["column"] == "FISCYEAR"
    assert result.status is CreateViewPartitioningStatus.CREATED


async def test_create_partitioning_maps_an_existing_partitioning() -> None:
    """
    Checks that an existing partitioning is kept instead of replaced.
    """
    async def get_partitioning(view: str, space: str) -> dict[str, Any]:
        return {
            "ranges": [{"id": 1}],
            "partitioningColumns": {"FISCYEAR": {"type": "cds.String"}},
        }

    result = await create_view_partitioning(
        CommandContext(client=_client(get_partitioning=get_partitioning)),
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


async def test_create_partitioning_rejects_a_non_string_column() -> None:
    """
    Checks that a column of another type is refused before writing.
    """
    async def get_partitioning(view: str, space: str) -> dict[str, Any]:
        return {
            "ranges": [],
            "partitioningColumns": {"FISCYEAR": {"type": "cds.Integer"}},
        }

    result = await create_view_partitioning(
        CommandContext(client=_client(get_partitioning=get_partitioning)),
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


async def test_lock_and_unlock_partitions_map_their_outcomes() -> None:
    """
    Checks that lock and unlock outcomes are mapped to their statuses.
    """
    written: list[dict[str, Any]] = []

    def _partitioning(*years: int) -> dict[str, Any]:
        ranges = [
            {"low": {"value": str(year)}, "locked": False} for year in years
        ]
        return {
            "remoteSourceName": "SOURCE",
            "objectName": "OBJECT",
            "numParallelPartitions": 1,
            "ranges": ranges,
            "column": "YEAR",
            "columnType": "INTEGER",
            "runtimeDataCalculation": False,
            "type": "RANGE",
        }

    async def get_partitioning(view: str, space: str) -> dict[str, Any]:
        return _partitioning(2021, 2022, 2023)

    async def set_partitioning(
        view: str,
        space: str,
        data: dict[str, Any],
    ) -> bool:
        written.append(data)
        return True

    async def get_empty_partitioning(view: str, space: str) -> dict[str, Any]:
        return _partitioning()

    locked = await lock_view_partitions(
        CommandContext(
            client=_client(
                get_partitioning=get_partitioning,
                set_partitioning=set_partitioning,
            )
        ),
        LockViewPartitionsRequest(
            view="VIEW_A",
            space="SPACE_A",
            until_year=2022,
        ),
    )
    unlocked = await unlock_view_partitions(
        CommandContext(
            client=_client(get_partitioning=get_empty_partitioning)
        ),
        UnlockViewPartitionsRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert locked.status is LockViewPartitionsStatus.LOCKED
    assert unlocked.status is UnlockViewPartitionsStatus.NO_PARTITIONS
    assert unlocked.status.outcome == "skipped"

    # Only the years up to the requested one are locked
    assert [partition["locked"] for partition in written[0]["ranges"]] == [
        True,
        True,
        False,
    ]


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
