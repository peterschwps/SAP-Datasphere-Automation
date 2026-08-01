from types import SimpleNamespace
from typing import Any, cast

import pytest
from datasphere_api import (
    DatasphereClient,
    ViewAnalysisCancelled,
    ViewPersistenceTimeout,
)
from datasphere_core import CommandCancelledError, CommandContext
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


async def test_persist_view_maps_a_completed_run() -> None:
    """
    Checks that a completed persistence run is mapped to its fields.
    """
    async def persist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        assert (view, space) == ("VIEW_A", "SPACE_A")
        return True, {"status": "COMPLETED", "logId": 5, "runTime": 2400}

    result = await persist_view(
        CommandContext(client=_client(persist_view=persist)),
        PersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    # The millisecond runtime is rounded to whole seconds
    assert result.status is PersistViewStatus.COMPLETED
    assert result.log_status == "COMPLETED"
    assert result.log_id == "5"
    assert result.runtime_seconds == 2


async def test_persist_view_maps_a_timeout_to_its_status() -> None:
    """
    Checks that a persistence timeout becomes a status, not an exception.
    """
    async def persist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        raise ViewPersistenceTimeout("persist", view, space, log_id=17)

    result = await persist_view(
        CommandContext(client=_client(persist_view=persist)),
        PersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert result.status is PersistViewStatus.TIMED_OUT
    assert result.log_id == "17"


async def test_unpersist_view_reports_an_already_absent_persistence() -> None:
    """
    Checks that a view without persisted data is already absent.
    """
    async def unpersist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        return True, {}

    result = await unpersist_view(
        CommandContext(client=_client(unpersist_view=unpersist)),
        UnpersistViewRequest(view="VIEW_A", space="SPACE_A"),
    )

    # A success without details means there was nothing to remove
    assert result.status is UnpersistViewStatus.ALREADY_ABSENT
    assert result.status.outcome == "skipped"


async def test_persist_view_batch_keeps_order_and_summarizes() -> None:
    """
    Checks that a persistence batch keeps the order and summarizes it.
    """
    progress: list[CommandProgress] = []

    # VIEW_B fails, every other view completes
    async def persist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        if view == "VIEW_B":
            return False, {"status": "FAILED", "logId": 9}
        return True, {"status": "COMPLETED", "logId": 1, "runTime": 1000}

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    result = await persist_view_batch(
        CommandContext(
            client=_client(persist_view=persist),
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


async def test_find_persistence_candidates_keeps_matching_scores() -> None:
    """
    Checks that only entities reaching the score become candidates.
    """
    async def analyze(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        return {
            "logId": 88,
            "entityStats": [
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
        }

    result = await find_view_persistence_candidates(
        CommandContext(client=_client(analyze_view=analyze)),
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
    async def analyze(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        return {
            "logId": 88,
            "entityStats": [
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
        }

    result = await find_view_persistence_candidates(
        CommandContext(client=_client(analyze_view=analyze)),
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
    async def analyze(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        return {
            "logId": 88,
            "entityStats": [
                {"entity": "VIEW_NO_SCORE", "space": "SPACE_B"},
                {
                    "entity": "VIEW_MATCH",
                    "space": "SPACE_B",
                    "persistencyCandidateScore": 10,
                },
            ],
        }

    result = await find_view_persistence_candidates(
        CommandContext(client=_client(analyze_view=analyze)),
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
    async def analyze(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        raise ViewAnalysisCancelled(view, space, log_id=7)

    with pytest.raises(CommandCancelledError) as error:
        await find_view_persistence_candidates(
            CommandContext(client=_client(analyze_view=analyze)),
            FindViewPersistenceCandidatesRequest(
                view="VIEW_A",
                space="SPACE_A",
            ),
        )

    # The log ID lets the caller follow the analysis that still runs remotely
    assert error.value.log_id == "7"


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
    received: dict[str, Any] = {}

    async def create_partitioning(
        view: str,
        space: str,
        attribute: str,
        partitions: list[str],
        overwrite_existing: bool = False,
    ) -> str:
        received.update(partitions=partitions, attribute=attribute)
        return "created"

    result = await create_view_partitioning(
        CommandContext(
            client=_client(create_partitioning=create_partitioning)
        ),
        CreateViewPartitioningRequest(
            view="VIEW_A",
            space="SPACE_A",
            attribute="FISCYEAR",
            start_year=2020,
            end_year=2023,
        ),
    )

    assert received["partitions"] == ["2020", "2021", "2022"]
    assert result.status is CreateViewPartitioningStatus.CREATED


async def test_create_partitioning_maps_an_existing_partitioning() -> None:
    """
    Checks that an existing partitioning is reported as skipped.
    """
    async def create_partitioning(
        view: str,
        space: str,
        attribute: str,
        partitions: list[str],
        overwrite_existing: bool = False,
    ) -> str:
        return "exists"

    result = await create_view_partitioning(
        CommandContext(
            client=_client(create_partitioning=create_partitioning)
        ),
        CreateViewPartitioningRequest(
            view="VIEW_A",
            space="SPACE_A",
            attribute="FISCYEAR",
            start_year=2020,
            end_year=2023,
        ),
    )

    # The API name 'exists' becomes the explicit already-exists status
    assert result.status is CreateViewPartitioningStatus.ALREADY_EXISTS
    assert result.status.outcome == "skipped"


async def test_lock_and_unlock_partitions_map_their_outcomes() -> None:
    """
    Checks that lock and unlock outcomes are mapped to their statuses.
    """
    async def lock_partitions(view: str, space: str, until_year: int) -> str:
        return "locked"

    async def unlock_partitions(view: str, space: str) -> str:
        return "no_partitions"

    locked = await lock_view_partitions(
        CommandContext(client=_client(lock_partitions=lock_partitions)),
        LockViewPartitionsRequest(
            view="VIEW_A",
            space="SPACE_A",
            until_year=2022,
        ),
    )
    unlocked = await unlock_view_partitions(
        CommandContext(client=_client(unlock_partitions=unlock_partitions)),
        UnlockViewPartitionsRequest(view="VIEW_A", space="SPACE_A"),
    )

    assert locked.status is LockViewPartitionsStatus.LOCKED
    assert unlocked.status is UnlockViewPartitionsStatus.NO_PARTITIONS
    assert unlocked.status.outcome == "skipped"


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
