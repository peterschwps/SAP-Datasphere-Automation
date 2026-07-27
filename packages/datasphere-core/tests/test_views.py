import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from datasphere_api import (
    DatasphereClient,
    ViewAnalysisCancelled,
    ViewAnalysisTimeout,
    ViewPersistenceCancelled,
    ViewPersistenceTimeout,
)
from datasphere_core.commands.views import (
    VIEWS_COMMAND_DEFINITIONS,
    create_view_partitioning,
    create_view_partitioning_batch,
    delete_view_partitioning,
    delete_view_partitioning_batch,
    find_view_attribute_matches,
    find_view_attribute_matches_batch,
    find_view_persistence_candidates,
    find_view_persistence_candidates_batch,
    lock_view_partitions,
    lock_view_partitions_batch,
    persist_view,
    persist_view_batch,
    unlock_view_partitions,
    unlock_view_partitions_batch,
    unpersist_view,
    unpersist_view_batch,
)
from datasphere_core.context import CommandContext
from datasphere_core.errors import CommandCancelledError
from datasphere_core.models.common import (
    MAXIMUM_BATCH_CONCURRENCY,
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
)
from datasphere_core.models.views import (
    CreateViewPartitioningBatchRequest,
    CreateViewPartitioningBatchResult,
    CreateViewPartitioningRequest,
    CreateViewPartitioningResult,
    CreateViewPartitioningStatus,
    DeleteViewPartitioningBatchRequest,
    DeleteViewPartitioningRequest,
    FindViewAttributeMatchesBatchRequest,
    FindViewAttributeMatchesRequest,
    FindViewPersistenceCandidatesBatchRequest,
    FindViewPersistenceCandidatesRequest,
    LockViewPartitionsBatchRequest,
    LockViewPartitionsRequest,
    PersistViewBatchRequest,
    PersistViewBatchResult,
    PersistViewRequest,
    PersistViewResult,
    PersistViewStatus,
    UnlockViewPartitionsBatchRequest,
    UnlockViewPartitionsRequest,
    UnpersistViewBatchRequest,
    UnpersistViewRequest,
    ViewPersistenceCandidate,
)


class FakeViews:
    def __init__(
        self,
        handlers: dict[str, Callable[..., Awaitable[Any]]],
    ) -> None:
        self.handlers = handlers

    async def get_all_views(self) -> list[dict[str, Any]]:
        return await self.handlers["get_all_views"]()

    async def analyze_view(
        self,
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await self.handlers["analyze_view"](
            view,
            space,
            timeout_seconds=timeout_seconds,
        )

    async def get_view_attributes(
        self,
        view_id: str,
        view_name: str,
        space: str,
    ) -> list[str]:
        return await self.handlers["get_view_attributes"](
            view_id=view_id,
            view_name=view_name,
            space=space,
        )

    async def create_partitioning(
        self,
        view: str,
        space: str,
        attribute: str,
        partitions: list[str],
        overwrite_existing: bool = False,
    ) -> str:
        return await self.handlers["create_partitioning"](
            view=view,
            space=space,
            attribute=attribute,
            partitions=partitions,
            overwrite_existing=overwrite_existing,
        )

    async def delete_partitioning(self, view: str, space: str) -> bool:
        return await self.handlers["delete_partitioning"](view, space)

    async def persist_view(
        self,
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        return await self.handlers["persist_view"](
            view,
            space,
            timeout_seconds=timeout_seconds,
        )

    async def unpersist_view(
        self,
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        return await self.handlers["unpersist_view"](
            view,
            space,
            timeout_seconds=timeout_seconds,
        )

    async def lock_partitions(
        self,
        view: str,
        space: str,
        until_year: int,
    ) -> str:
        return await self.handlers["lock_partitions"](
            view=view,
            space=space,
            until_year=until_year,
        )

    async def unlock_partitions(self, view: str, space: str) -> str:
        return await self.handlers["unlock_partitions"](view, space)


def _context(
    handlers: dict[str, Callable[..., Awaitable[Any]]],
    *,
    progress: Callable[[CommandProgress], Awaitable[None]] | None = None,
) -> CommandContext:
    client = cast(
        DatasphereClient,
        SimpleNamespace(views=FakeViews(handlers)),
    )
    return CommandContext(client=client, progress_callback=progress)


async def test_find_persistence_candidates_returns_every_match() -> None:
    async def analyze(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        assert (view, space, timeout_seconds) == ("SOURCE", "SP", 3600.0)
        return {
            "logId": 71,
            "entityStats": [
                {
                    "entity": "A",
                    "space": "ONE",
                    "businessName": "First",
                    "isPersisted": False,
                    "persistencyCandidateScore": 10,
                },
                {"entity": "B", "persistencyCandidateScore": 8},
                {"entity": "C", "persistencyCandidateScore": 10},
            ],
        }

    result = await find_view_persistence_candidates(
        _context({"analyze_view": analyze}),
        FindViewPersistenceCandidatesRequest(view="SOURCE", space="SP"),
    )

    assert result.status == "completed"
    assert result.log_id == "71"
    assert result.candidates == (
        ViewPersistenceCandidate(
            view="A",
            space="ONE",
            score=10,
            business_name="First",
            is_persisted=False,
        ),
        ViewPersistenceCandidate(view="C", space="SP", score=10),
    )


async def test_find_persistence_candidates_timeout_is_typed() -> None:
    progress: list[CommandProgress] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def analyze(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ViewAnalysisTimeout("VIEW", "SP", log_id=72)

    result = await find_view_persistence_candidates(
        _context({"analyze_view": analyze}, progress=report),
        FindViewPersistenceCandidatesRequest(view="VIEW", space="SP"),
    )

    assert result.status == "timed_out"
    assert result.log_id == "72"
    assert [update.phase for update in progress] == ["started", "timed_out"]


async def test_find_persistence_candidates_empty_analysis_is_failed() -> None:
    async def analyze(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"logId": None, "entityStats": []}

    result = await find_view_persistence_candidates(
        _context({"analyze_view": analyze}),
        FindViewPersistenceCandidatesRequest(view="VIEW", space="SP"),
    )

    assert result.status == "failed"
    assert result.log_id is None


async def test_find_persistence_candidates_cancellation_propagates() -> None:
    async def analyze(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ViewAnalysisCancelled("VIEW", "SP", log_id=73)

    with pytest.raises(CommandCancelledError) as error:
        await find_view_persistence_candidates(
            _context({"analyze_view": analyze}),
            FindViewPersistenceCandidatesRequest(view="VIEW", space="SP"),
        )

    assert error.value.log_id == "73"


async def test_find_persistence_candidates_batch_summarizes_timeouts() -> None:
    async def analyze(
        view: str,
        space: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if view == "TIMEOUT":
            raise ViewAnalysisTimeout(view, space, log_id=74)
        return {
            "logId": None,
            "entityStats": [{"entity": view, "persistencyCandidateScore": 10}],
        }

    result = await find_view_persistence_candidates_batch(
        _context({"analyze_view": analyze}),
        FindViewPersistenceCandidatesBatchRequest(
            requests=(
                FindViewPersistenceCandidatesRequest("OK", "SP"),
                FindViewPersistenceCandidatesRequest("TIMEOUT", "SP"),
            )
        ),
    )

    assert [item.view for item in result.results] == ["OK", "TIMEOUT"]
    assert result.results[1].log_id == "74"
    assert result.summary == BatchSummary(2, 1, 0, 0, 1)


async def test_persistence_candidate_batch_discovers_views_once_in_order() -> (
    None
):
    discovery_calls = 0
    analysis_calls: list[tuple[str, str, float | None]] = []

    async def get_all_views() -> list[dict[str, Any]]:
        nonlocal discovery_calls
        discovery_calls += 1
        return [
            {
                "id": "id-b",
                "name": "B",
                "space_name": "SP_B",
                "business_name": "Business B",
            },
            {
                "id": "id-a",
                "name": "A",
                "space_name": "SP_A",
                "business_name": "Business A",
            },
        ]

    async def analyze(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        analysis_calls.append((view, space, timeout_seconds))
        return {
            "logId": None,
            "entityStats": [
                {
                    "entity": view,
                    "space": space,
                    "persistencyCandidateScore": 7,
                }
            ],
        }

    result = await find_view_persistence_candidates_batch(
        _context(
            {
                "get_all_views": get_all_views,
                "analyze_view": analyze,
            }
        ),
        FindViewPersistenceCandidatesBatchRequest(
            candidate_score=7,
            timeout_seconds=12.0,
        ),
    )

    assert discovery_calls == 1
    assert analysis_calls == [
        ("B", "SP_B", 12.0),
        ("A", "SP_A", 12.0),
    ]
    assert [item.view for item in result.results] == ["B", "A"]
    assert [item.candidates[0].score for item in result.results] == [7, 7]


async def test_persistence_candidate_discovery_uses_one_lifecycle_stream() -> (
    None
):
    progress: list[CommandProgress] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def get_all_views() -> list[dict[str, Any]]:
        raise ConnectionError("discovery unavailable")

    with pytest.raises(ConnectionError, match="discovery unavailable"):
        await find_view_persistence_candidates_batch(
            _context(
                {"get_all_views": get_all_views},
                progress=report,
            ),
            FindViewPersistenceCandidatesBatchRequest(),
        )

    assert [update.phase for update in progress] == ["started", "failed"]
    assert progress[0].total_items is None


@pytest.mark.parametrize(
    ("case_sensitive", "expected"),
    [
        (False, ("FiscalYear", "FISCAL_PERIOD")),
        (True, ("FISCAL_PERIOD",)),
    ],
)
async def test_find_attribute_matches_returns_all_matches(
    case_sensitive: bool,
    expected: tuple[str, ...],
) -> None:
    async def attributes(**kwargs: Any) -> list[str]:
        assert kwargs == {
            "view_id": "ID",
            "view_name": "VIEW",
            "space": "SP",
        }
        return ["FiscalYear", "OTHER", "FISCAL_PERIOD"]

    result = await find_view_attribute_matches(
        _context({"get_view_attributes": attributes}),
        FindViewAttributeMatchesRequest(
            view_id="ID",
            view="VIEW",
            space="SP",
            business_name="Business View",
            substring="FISCAL",
            case_sensitive=case_sensitive,
        ),
    )

    assert result.attributes == expected
    assert result.business_name == "Business View"


async def test_attribute_match_batch_discovers_and_propagates_metadata() -> (
    None
):
    discovery_calls = 0
    attribute_calls: list[tuple[str, str, str]] = []

    async def get_all_views() -> list[dict[str, Any]]:
        nonlocal discovery_calls
        discovery_calls += 1
        return [
            {
                "id": "id-2",
                "name": "SECOND",
                "space_name": "SP_2",
                "business_name": "Second business name",
            },
            {
                "id": "id-1",
                "name": "FIRST",
                "space_name": "SP_1",
                "business_name": "First business name",
            },
        ]

    async def attributes(**kwargs: Any) -> list[str]:
        attribute_calls.append(
            (kwargs["view_id"], kwargs["view_name"], kwargs["space"])
        )
        return ["ExactMatch", "exactmatch"]

    result = await find_view_attribute_matches_batch(
        _context(
            {
                "get_all_views": get_all_views,
                "get_view_attributes": attributes,
            }
        ),
        FindViewAttributeMatchesBatchRequest(
            substring="Exact",
            case_sensitive=True,
        ),
    )

    assert discovery_calls == 1
    assert attribute_calls == [
        ("id-2", "SECOND", "SP_2"),
        ("id-1", "FIRST", "SP_1"),
    ]
    assert [item.view for item in result.results] == ["SECOND", "FIRST"]
    assert [item.business_name for item in result.results] == [
        "Second business name",
        "First business name",
    ]
    assert [item.attributes for item in result.results] == [
        ("ExactMatch",),
        ("ExactMatch",),
    ]


async def test_attribute_match_empty_response_is_failed() -> None:
    async def attributes(**kwargs: Any) -> list[str]:
        return []

    result = await find_view_attribute_matches(
        _context({"get_view_attributes": attributes}),
        FindViewAttributeMatchesRequest(
            view_id="ID",
            view="VIEW",
            space="SP",
            business_name="Business View",
            substring="MATCH",
        ),
    )

    assert result.status == "failed"
    assert result.attributes == ()


async def test_attribute_match_batch_counts_empty_response_as_failed() -> None:
    async def attributes(**kwargs: Any) -> list[str]:
        return [] if kwargs["view_name"] == "EMPTY" else ["MATCH"]

    result = await find_view_attribute_matches_batch(
        _context({"get_view_attributes": attributes}),
        FindViewAttributeMatchesBatchRequest(
            substring="MATCH",
            requests=(
                FindViewAttributeMatchesRequest(
                    "EMPTY", "EMPTY", "SP", "Empty", "MATCH"
                ),
                FindViewAttributeMatchesRequest(
                    "OK", "OK", "SP", "Okay", "MATCH"
                ),
            ),
        ),
    )

    assert [item.status for item in result.results] == ["failed", "completed"]
    assert result.summary == BatchSummary(2, 1, 1, 0, 0)


@pytest.mark.parametrize(
    ("api_outcome", "expected_status"),
    [
        ("created", "created"),
        ("exists", "already_exists"),
        ("invalid_column", "invalid_column"),
        ("failed", "failed"),
    ],
)
async def test_create_partitioning_builds_year_boundaries(
    api_outcome: str,
    expected_status: str,
) -> None:
    async def create(**kwargs: Any) -> str:
        assert kwargs == {
            "view": "VIEW",
            "space": "SP",
            "attribute": "YEAR",
            "partitions": ["2022", "2023"],
            "overwrite_existing": True,
        }
        return api_outcome

    result = await create_view_partitioning(
        _context({"create_partitioning": create}),
        CreateViewPartitioningRequest(
            view="VIEW",
            space="SP",
            attribute="YEAR",
            start_year=2022,
            end_year=2024,
            overwrite_existing=True,
        ),
    )

    assert result.status == expected_status


@pytest.mark.parametrize(
    ("deleted", "status"),
    [(True, "deleted"), (False, "failed")],
)
async def test_delete_partitioning_maps_api_result(
    deleted: bool,
    status: str,
) -> None:
    async def delete(view: str, space: str) -> bool:
        assert (view, space) == ("VIEW", "SP")
        return deleted

    result = await delete_view_partitioning(
        _context({"delete_partitioning": delete}),
        DeleteViewPartitioningRequest(view="VIEW", space="SP"),
    )

    assert result.status == status


@pytest.mark.parametrize(
    ("success", "details", "status"),
    [
        (
            True,
            {"status": "COMPLETED", "logId": 81, "runTime": 12500},
            "completed",
        ),
        (False, {}, "start_failed"),
        (False, {"status": "FAILED", "logId": "82"}, "failed"),
    ],
)
async def test_persist_preserves_sap_details(
    success: bool,
    details: dict[str, Any],
    status: str,
) -> None:
    async def api_persist_view(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        assert (view, space, timeout_seconds) == ("VIEW", "SP", 42.0)
        return success, details

    result = await persist_view(
        _context({"persist_view": api_persist_view}),
        PersistViewRequest(view="VIEW", space="SP", timeout_seconds=42.0),
    )

    assert result.status == status
    assert result.sap_status == details.get("status")
    expected_id = details.get("logId")
    assert result.log_id == (
        str(expected_id) if expected_id is not None else None
    )
    assert result.runtime_seconds == (12 if success else None)


async def test_persist_timeout_and_cancellation_retain_log_id() -> None:
    async def timed_out(*args: Any, **kwargs: Any) -> Any:
        raise ViewPersistenceTimeout("persist", "VIEW", "SP", log_id=83)

    result = await persist_view(
        _context({"persist_view": timed_out}),
        PersistViewRequest(view="VIEW", space="SP"),
    )
    assert (result.status, result.log_id) == ("timed_out", "83")

    async def cancelled(*args: Any, **kwargs: Any) -> Any:
        raise ViewPersistenceCancelled("persist", "VIEW", "SP", log_id=84)

    with pytest.raises(CommandCancelledError) as error:
        await persist_view(
            _context({"persist_view": cancelled}),
            PersistViewRequest(view="VIEW", space="SP"),
        )
    assert error.value.log_id == "84"


@pytest.mark.parametrize(
    ("success", "details", "status"),
    [
        (True, {}, "already_absent"),
        (
            True,
            {"status": "COMPLETED", "logId": 91, "runTime": 1000},
            "completed",
        ),
        (False, {}, "start_failed"),
        (False, {"status": "FAILED", "logId": 92}, "failed"),
    ],
)
async def test_unpersist_preserves_expected_outcomes(
    success: bool,
    details: dict[str, Any],
    status: str,
) -> None:
    async def api_unpersist_view(*args: Any, **kwargs: Any) -> Any:
        return success, details

    result = await unpersist_view(
        _context({"unpersist_view": api_unpersist_view}),
        UnpersistViewRequest(view="VIEW", space="SP"),
    )

    assert result.status == status


async def test_unpersist_timeout_is_typed() -> None:
    async def api_unpersist_view(*args: Any, **kwargs: Any) -> Any:
        raise ViewPersistenceTimeout("unpersist", "VIEW", "SP", log_id=93)

    result = await unpersist_view(
        _context({"unpersist_view": api_unpersist_view}),
        UnpersistViewRequest(view="VIEW", space="SP"),
    )

    assert (result.status, result.log_id) == ("timed_out", "93")


@pytest.mark.parametrize(
    ("operation", "api_outcome", "expected"),
    [
        ("lock", "locked", "locked"),
        ("lock", "no_partitions", "no_partitions"),
        ("lock", "failed", "failed"),
        ("unlock", "unlocked", "unlocked"),
        ("unlock", "no_partitions", "no_partitions"),
        ("unlock", "failed", "failed"),
    ],
)
async def test_lock_and_unlock_preserve_outcomes(
    operation: str,
    api_outcome: str,
    expected: str,
) -> None:
    async def lock(**kwargs: Any) -> str:
        assert kwargs["until_year"] == 2024
        return api_outcome

    async def unlock(view: str, space: str) -> str:
        return api_outcome

    if operation == "lock":
        result = await lock_view_partitions(
            _context({"lock_partitions": lock}),
            LockViewPartitionsRequest(
                view="VIEW", space="SP", until_year=2024
            ),
        )
    else:
        result = await unlock_view_partitions(
            _context({"unlock_partitions": unlock}),
            UnlockViewPartitionsRequest(view="VIEW", space="SP"),
        )
    assert result.status == expected


async def test_persist_batch_is_bounded_ordered_and_reports_exactly() -> None:
    active = 0
    maximum_active = 0
    release_first = asyncio.Event()
    progress: list[CommandProgress] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def api_persist_view(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            if view == "A":
                await release_first.wait()
            if view == "B":
                return False, {"status": "FAILED", "logId": 102}
            if view == "C":
                raise ViewPersistenceTimeout(
                    "persist", view, space, log_id=103
                )
            if view == "D":
                release_first.set()
                return False, {}
            return True, {
                "status": "COMPLETED",
                "logId": 101,
                "runTime": 1000,
            }
        finally:
            active -= 1

    result = await persist_view_batch(
        _context({"persist_view": api_persist_view}, progress=report),
        PersistViewBatchRequest(
            requests=tuple(
                PersistViewRequest(view=view, space="SP")
                for view in ("A", "B", "C", "D")
            ),
            max_concurrency=2,
        ),
    )

    assert result == PersistViewBatchResult(
        results=(
            PersistViewResult(
                view="A",
                space="SP",
                status=PersistViewStatus.COMPLETED,
                sap_status="COMPLETED",
                log_id="101",
                runtime_seconds=1,
            ),
            PersistViewResult(
                view="B",
                space="SP",
                status=PersistViewStatus.FAILED,
                sap_status="FAILED",
                log_id="102",
            ),
            PersistViewResult(
                view="C",
                space="SP",
                status=PersistViewStatus.TIMED_OUT,
                log_id="103",
            ),
            PersistViewResult(
                view="D",
                space="SP",
                status=PersistViewStatus.START_FAILED,
            ),
        ),
        summary=BatchSummary(4, 1, 2, 0, 1),
    )
    assert maximum_active == 2
    assert [update.item_index for update in progress[1:-1]] == [1, 2, 3, 0]
    assert progress == [
        CommandProgress(
            command="views.persist_batch",
            phase=CommandProgressPhase.STARTED,
            completed_items=0,
            total_items=4,
            succeeded_items=0,
            failed_items=0,
            skipped_items=0,
            timed_out_items=0,
        ),
        CommandProgress(
            command="views.persist_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=1,
            total_items=4,
            succeeded_items=0,
            failed_items=1,
            skipped_items=0,
            timed_out_items=0,
            item_index=1,
        ),
        CommandProgress(
            command="views.persist_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=2,
            total_items=4,
            succeeded_items=0,
            failed_items=1,
            skipped_items=0,
            timed_out_items=1,
            item_index=2,
        ),
        CommandProgress(
            command="views.persist_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=3,
            total_items=4,
            succeeded_items=0,
            failed_items=2,
            skipped_items=0,
            timed_out_items=1,
            item_index=3,
        ),
        CommandProgress(
            command="views.persist_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=4,
            total_items=4,
            succeeded_items=1,
            failed_items=2,
            skipped_items=0,
            timed_out_items=1,
            item_index=0,
        ),
        CommandProgress(
            command="views.persist_batch",
            phase=CommandProgressPhase.TIMED_OUT,
            completed_items=4,
            total_items=4,
            succeeded_items=1,
            failed_items=2,
            skipped_items=0,
            timed_out_items=1,
        ),
    ]


async def test_other_batches_map_order_and_summary_categories() -> None:
    async def attributes(**kwargs: Any) -> list[str]:
        return [kwargs["view_name"], "OTHER"]

    attribute_result = await find_view_attribute_matches_batch(
        _context({"get_view_attributes": attributes}),
        FindViewAttributeMatchesBatchRequest(
            substring="MATCH",
            requests=tuple(
                FindViewAttributeMatchesRequest(
                    view_id=view,
                    view=view,
                    space="SP",
                    business_name=f"Business {view}",
                    substring="MATCH",
                )
                for view in ("B", "A")
            ),
        ),
    )
    assert [result.view for result in attribute_result.results] == ["B", "A"]
    assert [result.business_name for result in attribute_result.results] == [
        "Business B",
        "Business A",
    ]
    assert attribute_result.summary == BatchSummary(2, 2, 0, 0, 0)

    async def create(**kwargs: Any) -> str:
        return {
            "A": "created",
            "B": "exists",
            "C": "invalid_column",
            "D": "failed",
        }[kwargs["view"]]

    create_result = await create_view_partitioning_batch(
        _context({"create_partitioning": create}),
        CreateViewPartitioningBatchRequest(
            requests=tuple(
                CreateViewPartitioningRequest(
                    view=view,
                    space="SP",
                    attribute="YEAR",
                    start_year=2020,
                    end_year=2021,
                )
                for view in ("A", "B", "C", "D")
            )
        ),
    )
    assert create_result == CreateViewPartitioningBatchResult(
        results=(
            CreateViewPartitioningResult(
                "A", "SP", CreateViewPartitioningStatus.CREATED
            ),
            CreateViewPartitioningResult(
                "B", "SP", CreateViewPartitioningStatus.ALREADY_EXISTS
            ),
            CreateViewPartitioningResult(
                "C", "SP", CreateViewPartitioningStatus.INVALID_COLUMN
            ),
            CreateViewPartitioningResult(
                "D", "SP", CreateViewPartitioningStatus.FAILED
            ),
        ),
        summary=BatchSummary(4, 1, 2, 1, 0),
    )

    async def api_unpersist_view(
        view: str,
        space: str,
        **kwargs: Any,
    ) -> tuple[bool, dict[str, Any]]:
        return (True, {}) if view == "A" else (True, {"status": "COMPLETED"})

    unpersist_result = await unpersist_view_batch(
        _context({"unpersist_view": api_unpersist_view}),
        UnpersistViewBatchRequest(
            requests=(
                UnpersistViewRequest("A", "SP"),
                UnpersistViewRequest("B", "SP"),
            )
        ),
    )
    assert unpersist_result.summary == BatchSummary(2, 1, 0, 1, 0)


async def test_partition_batches_preserve_skip_and_failure() -> None:
    async def lock(**kwargs: Any) -> str:
        return "no_partitions" if kwargs["view"] == "EMPTY" else "locked"

    lock_result = await lock_view_partitions_batch(
        _context({"lock_partitions": lock}),
        LockViewPartitionsBatchRequest(
            requests=(
                LockViewPartitionsRequest("EMPTY", "SP", 2024),
                LockViewPartitionsRequest("VIEW", "SP", 2024),
            )
        ),
    )
    assert lock_result.summary == BatchSummary(2, 1, 0, 1, 0)

    async def unlock(view: str, space: str) -> str:
        return "no_partitions" if view == "EMPTY" else "unlocked"

    unlock_result = await unlock_view_partitions_batch(
        _context({"unlock_partitions": unlock}),
        UnlockViewPartitionsBatchRequest(
            requests=(
                UnlockViewPartitionsRequest("EMPTY", "SP"),
                UnlockViewPartitionsRequest("VIEW", "SP"),
            )
        ),
    )
    assert unlock_result.summary == BatchSummary(2, 1, 0, 1, 0)

    async def delete(view: str, space: str) -> bool:
        return view == "A"

    delete_result = await delete_view_partitioning_batch(
        _context({"delete_partitioning": delete}),
        DeleteViewPartitioningBatchRequest(
            requests=(
                DeleteViewPartitioningRequest("A", "SP"),
                DeleteViewPartitioningRequest("B", "SP"),
            )
        ),
    )
    assert delete_result.summary == BatchSummary(2, 1, 1, 0, 0)


async def test_unexpected_batch_error_aborts() -> None:
    async def delete(view: str, space: str) -> bool:
        raise ConnectionError("network unavailable")

    with pytest.raises(ConnectionError, match="network unavailable"):
        await delete_view_partitioning_batch(
            _context({"delete_partitioning": delete}),
            DeleteViewPartitioningBatchRequest(
                requests=(DeleteViewPartitioningRequest("A", "SP"),)
            ),
        )


@pytest.mark.parametrize(
    "request_factory",
    [
        lambda: PersistViewRequest("VIEW", "SP", timeout_seconds=0),
        lambda: PersistViewRequest("VIEW", "SP", timeout_seconds=float("inf")),
        lambda: FindViewPersistenceCandidatesRequest(
            "VIEW", "SP", timeout_seconds=86401
        ),
        lambda: CreateViewPartitioningRequest(
            "VIEW", "SP", "YEAR", 2024, 2024
        ),
        lambda: CreateViewPartitioningRequest(
            "VIEW", "SP", "YEAR", 2025, 2024
        ),
        lambda: LockViewPartitionsRequest("VIEW", "SP", True),
    ],
)
def test_requests_validate_timeout_and_years(
    request_factory: Callable[[], object],
) -> None:
    with pytest.raises(ValueError):
        request_factory()


@pytest.mark.parametrize(
    "request_factory",
    [
        lambda: FindViewPersistenceCandidatesBatchRequest(
            requests=(
                FindViewPersistenceCandidatesRequest(
                    "VIEW", "SP", candidate_score=5
                ),
            ),
        ),
        lambda: FindViewPersistenceCandidatesBatchRequest(
            requests=(
                FindViewPersistenceCandidatesRequest(
                    "VIEW", "SP", timeout_seconds=5.0
                ),
            ),
        ),
        lambda: FindViewAttributeMatchesBatchRequest(substring=""),
        lambda: FindViewAttributeMatchesBatchRequest(
            substring="COMMON",
            requests=(
                FindViewAttributeMatchesRequest(
                    "ID",
                    "VIEW",
                    "SP",
                    "Business View",
                    "DIFFERENT",
                ),
            ),
        ),
        lambda: FindViewAttributeMatchesBatchRequest(
            substring="COMMON",
            requests=(
                FindViewAttributeMatchesRequest(
                    "ID",
                    "VIEW",
                    "SP",
                    "Business View",
                    "COMMON",
                    case_sensitive=True,
                ),
            ),
        ),
        lambda: FindViewAttributeMatchesRequest(
            "ID", "VIEW", "SP", "", "COMMON"
        ),
    ],
)
def test_discovery_batch_requests_reject_ambiguous_parameters(
    request_factory: Callable[[], object],
) -> None:
    with pytest.raises(ValueError):
        request_factory()


@pytest.mark.parametrize(
    "max_concurrency",
    [0, True, 1.5, MAXIMUM_BATCH_CONCURRENCY + 1],
)
def test_batch_requests_validate_concurrency(max_concurrency: Any) -> None:
    with pytest.raises(ValueError):
        PersistViewBatchRequest((), max_concurrency=max_concurrency)


def test_views_definitions_are_explicit_and_not_mcp_exposed() -> None:
    assert [definition.name for definition in VIEWS_COMMAND_DEFINITIONS] == [
        "views.find_persistence_candidates",
        "views.find_persistence_candidates_batch",
        "views.find_attribute_matches",
        "views.find_attribute_matches_batch",
        "views.create_partitioning",
        "views.create_partitioning_batch",
        "views.delete_partitioning",
        "views.delete_partitioning_batch",
        "views.persist",
        "views.persist_batch",
        "views.unpersist",
        "views.unpersist_batch",
        "views.lock_partitions",
        "views.lock_partitions_batch",
        "views.unlock_partitions",
        "views.unlock_partitions_batch",
    ]
    assert not any(
        definition.expose_to_mcp for definition in VIEWS_COMMAND_DEFINITIONS
    )
