import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from datasphere_api import DatasphereClient
from datasphere_core import CommandContext
from datasphere_core.commands.analytical_models import (
    get_analytical_model_view_dependencies_batch,
    measure_analytical_model_view_persistence,
    measure_analytical_model_view_persistence_batch,
)
from datasphere_core.models.analytical_models import (
    AnalyticalModelDependenciesStatus,
    AnalyticalModelDependencyStatus,
    AnalyticalModelPersistenceItemStatus,
    AnalyticalModelPersistenceStatus,
    AnalyticalModelReference,
    GetAnalyticalModelViewDependenciesBatchRequest,
    MeasureAnalyticalModelViewPersistenceBatchRequest,
    MeasureAnalyticalModelViewPersistenceBatchResult,
    MeasureAnalyticalModelViewPersistenceRequest,
)
from datasphere_core.models.common import BatchItemResult, BatchSummary

type DependencyMap = dict[str, dict[str, str]]


def _model(model_id: str, name: str, space: str) -> dict[str, Any]:
    """
    Builds the repository entry of one analytical model.
    """
    return {"id": model_id, "name": name, "space_name": space}


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


# Task log IDs the default fakes report for the two runs of a measurement
PERSIST_LOG_ID = 11
CLEANUP_LOG_ID = 12


def _client(
    models: list[dict[str, Any]],
    views: list[dict[str, Any]],
    dependencies: Any,
    *,
    is_persisted: bool = False,
    **view_calls: Any,
) -> DatasphereClient:
    """
    Builds a client covering the analytical model and view calls of the
    dependency and measurement workflows. Every view call can be replaced
    through a keyword argument.
    """
    async def get_all_analytical_models() -> list[dict[str, Any]]:
        return models

    async def get_all_views() -> list[dict[str, Any]]:
        return views

    async def check_persisted(view: str, space: str) -> bool:
        return is_persisted

    async def start_persistence(view: str, space: str) -> int | None:
        return PERSIST_LOG_ID

    async def start_persistence_removal(view: str, space: str) -> int | None:
        return CLEANUP_LOG_ID

    async def get_monitor_details(view: str, space: str) -> dict[str, Any]:
        return {"dataPersistency": "Persisted"}

    async def get_extended_log(log_id: int, space: str) -> dict[str, Any]:
        if log_id == PERSIST_LOG_ID:
            return {"status": "COMPLETED", "runTime": 4000}
        return {"status": "COMPLETED"}

    return cast(
        DatasphereClient,
        SimpleNamespace(
            analytical_models=SimpleNamespace(
                get_all_analytical_models=get_all_analytical_models,
                get_views_for_analytical_model=dependencies,
            ),
            views=SimpleNamespace(
                **{
                    "get_all_views": get_all_views,
                    "is_persisted": check_persisted,
                    "start_persistence": start_persistence,
                    "start_persistence_removal": start_persistence_removal,
                    "get_monitor_details": get_monitor_details,
                    "get_extended_log": get_extended_log,
                    **view_calls,
                }
            ),
        ),
    )


async def test_dependency_batch_resolves_views_to_their_spaces() -> None:
    """
    Checks that a resolved view carries its space and an unknown one does not.
    """
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Sales", "VIEW_X": "Unknown"}}

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
                dependencies=dependencies,
            )
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(),
    )

    resolved, missing = result.results[0].dependencies
    assert resolved.space == "VIEW_SPACE"
    assert resolved.status is AnalyticalModelDependencyStatus.RESOLVED
    assert missing.space is None
    assert missing.status is AnalyticalModelDependencyStatus.NOT_FOUND

    # An unresolvable dependency makes the whole model result a failure
    assert result.results[0].status is (
        AnalyticalModelDependenciesStatus.DEPENDENCY_NOT_FOUND
    )
    assert result.summary == BatchSummary(
        total=1,
        succeeded=0,
        failed=1,
        skipped=0,
        timed_out=0,
    )


async def test_dependency_batch_reports_a_missing_model_as_skipped() -> None:
    """
    Checks that a model the tenant does not know is skipped, not failed.
    """
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {}}

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[],
                dependencies=dependencies,
            )
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(
            analytical_models=(AnalyticalModelReference("Missing", "SPACE_A"),)
        ),
    )

    assert result.results[0].status is (
        AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND
    )
    assert result.summary.skipped == 1


async def test_dependency_batch_deduplicates_shared_views() -> None:
    """
    Checks that a shared view stays with the first model claiming it.
    """
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Sales"}}

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                models=[
                    _model("MODEL_1", "One", "SPACE_A"),
                    _model("MODEL_2", "Two", "SPACE_A"),
                ],
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
                dependencies=dependencies,
            )
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(
            deduplicate_views=True
        ),
    )

    # The shared view stays with the first model only
    assert len(result.results[0].dependencies) == 1
    assert result.results[1].dependencies == ()


async def test_measure_persists_a_view_and_removes_it_again() -> None:
    """
    Checks that a measured view is persisted and cleaned up again.
    """
    persisted: list[tuple[str, str]] = []
    unpersisted: list[tuple[str, str]] = []

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Sales"}}

    async def start_persistence(view: str, space: str) -> int | None:
        persisted.append((view, space))
        return PERSIST_LOG_ID

    async def start_persistence_removal(view: str, space: str) -> int | None:
        unpersisted.append((view, space))
        return CLEANUP_LOG_ID

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
                dependencies=dependencies,
                start_persistence=start_persistence,
                start_persistence_removal=start_persistence_removal,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest(
            analytical_model_name="One",
            space="SPACE_A",
        ),
    )

    assert persisted == [("Sales", "VIEW_SPACE")]
    assert unpersisted == [("Sales", "VIEW_SPACE")]
    assert result.status is AnalyticalModelPersistenceStatus.COMPLETED

    measurement = result.dependencies[0]
    assert measurement.status is (
        AnalyticalModelPersistenceItemStatus.COMPLETED
    )
    assert measurement.runtime_seconds == 4
    assert measurement.persistence_removed is True
    assert measurement.manual_intervention is False


async def test_measure_keeps_a_view_that_was_persisted_before() -> None:
    """
    Checks that a view persisted before the run keeps its persistence.
    """
    unpersisted: list[str] = []

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Sales"}}

    async def start_persistence_removal(view: str, space: str) -> int | None:
        unpersisted.append(view)
        return CLEANUP_LOG_ID

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
                dependencies=dependencies,
                start_persistence_removal=start_persistence_removal,
                is_persisted=True,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest(
            analytical_model_name="One",
            space="SPACE_A",
        ),
    )

    # A previously persisted view must keep its persistence
    assert unpersisted == []
    assert result.dependencies[0].status is (
        AnalyticalModelPersistenceItemStatus.ALREADY_PERSISTED
    )
    assert result.status is AnalyticalModelPersistenceStatus.COMPLETED


async def test_measure_reports_a_timeout_as_needing_manual_action() -> None:
    """
    Checks that a timed-out persistence is flagged for manual intervention.
    """
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Sales"}}

    async def start_persistence(view: str, space: str) -> int | None:
        return 31

    # The run never leaves the running state, so the timeout decides
    async def get_extended_log(log_id: int, space: str) -> dict[str, Any]:
        return {"status": "RUNNING", "runTime": 1000}

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
                dependencies=dependencies,
                start_persistence=start_persistence,
                get_extended_log=get_extended_log,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest(
            analytical_model_name="One",
            space="SPACE_A",
            timeout_seconds=0.01,
        ),
    )

    # A timed-out persistence may still be running remotely
    assert result.dependencies[0].status is (
        AnalyticalModelPersistenceItemStatus.PERSIST_TIMED_OUT
    )
    assert result.dependencies[0].persistence_log_id == "31"
    assert result.dependencies[0].manual_intervention is True
    assert result.status is AnalyticalModelPersistenceStatus.TIMED_OUT


async def test_measure_batch_runs_a_shared_view_once_and_projects_it() -> None:
    """
    Checks that a view shared by two models is measured once and projected onto
    both of them.
    """
    persisted: list[tuple[str, str]] = []
    item_results: list[BatchItemResult] = []

    # Both models depend on the very same view
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"SHARED": "Shared"}}

    async def start_persistence(view: str, space: str) -> int | None:
        persisted.append((view, space))
        return PERSIST_LOG_ID

    async def report_item(update: BatchItemResult) -> None:
        item_results.append(update)

    result = await measure_analytical_model_view_persistence_batch(
        CommandContext(
            client=_client(
                models=[
                    _model("MODEL_1", "One", "SPACE_A"),
                    _model("MODEL_2", "Two", "SPACE_A"),
                ],
                views=[_view("SHARED", "Shared", "VIEW_SPACE")],
                dependencies=dependencies,
                start_persistence=start_persistence,
            ),
            batch_item_result_callback=report_item,
        ),
        MeasureAnalyticalModelViewPersistenceBatchRequest(
            analytical_models=(
                AnalyticalModelReference("One", "SPACE_A"),
                AnalyticalModelReference("Missing", "SPACE_A"),
                AnalyticalModelReference("Two", "SPACE_A"),
            ),
            max_concurrency=2,
        ),
    )

    # Both models point at the same physical view, so it runs only once
    assert persisted == [("Shared", "VIEW_SPACE")]
    assert [item.status for item in result.results] == [
        AnalyticalModelPersistenceStatus.COMPLETED,
        AnalyticalModelPersistenceStatus.ANALYTICAL_MODEL_NOT_FOUND,
        AnalyticalModelPersistenceStatus.COMPLETED,
    ]

    # The single measurement is projected onto both dependent models
    assert result.results[0].dependencies[0].view_id == "SHARED"
    assert result.results[2].dependencies[0].view_id == "SHARED"
    assert result.results[0].dependencies[0].runtime_seconds == 4
    assert result.results[2].dependencies[0].runtime_seconds == 4
    assert result.summary == BatchSummary(
        total=3,
        succeeded=2,
        failed=0,
        skipped=1,
        timed_out=0,
    )
    # Models are reported as they become final, so the order follows
    # completion. The index still refers to the batch input.
    assert sorted(update.item_index for update in item_results) == [0, 1, 2]


async def test_measure_skips_a_dependency_without_a_resolved_space() -> None:
    """
    Checks that an unresolved dependency is never persisted.
    """
    persistence_called = False

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"UNKNOWN": "Unknown"}}

    async def start_persistence(view: str, space: str) -> int | None:
        nonlocal persistence_called
        persistence_called = True
        return PERSIST_LOG_ID

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[],
                dependencies=dependencies,
                start_persistence=start_persistence,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest(
            analytical_model_name="One",
            space="SPACE_A",
        ),
    )

    # An unresolved view must never be persisted
    assert persistence_called is False
    assert result.dependencies[0].status is (
        AnalyticalModelPersistenceItemStatus.DEPENDENCY_NOT_FOUND
    )
    assert result.status is AnalyticalModelPersistenceStatus.FAILED


async def test_measure_batch_reports_a_model_before_the_batch_finished(
) -> None:
    """
    Checks that a completed model is reported while others still run.
    """
    item_results: list[BatchItemResult] = []
    blocked = asyncio.Event()

    # Each model depends on a view of its own
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        view_id = (
            "VIEW_1" if analytical_model_id == "MODEL_1" else "VIEW_2"
        )
        return {analytical_model_id: {view_id: f"View{view_id[-1]}"}}

    # The view of the second model blocks until the test releases it
    async def start_persistence(view: str, space: str) -> int | None:
        if view == "View2":
            await blocked.wait()
        return PERSIST_LOG_ID

    async def report_item(update: BatchItemResult) -> None:
        item_results.append(update)

    context = CommandContext(
        client=_client(
            models=[
                _model("MODEL_1", "One", "SPACE_A"),
                _model("MODEL_2", "Two", "SPACE_A"),
            ],
            views=[
                _view("VIEW_1", "View1", "VIEW_SPACE"),
                _view("VIEW_2", "View2", "VIEW_SPACE"),
            ],
            dependencies=dependencies,
            start_persistence=start_persistence,
        ),
        batch_item_result_callback=report_item,
    )

    async def run_measurement() -> (
        MeasureAnalyticalModelViewPersistenceBatchResult
    ):
        return await measure_analytical_model_view_persistence_batch(
            context,
            MeasureAnalyticalModelViewPersistenceBatchRequest(
                analytical_models=(
                    AnalyticalModelReference("One", "SPACE_A"),
                    AnalyticalModelReference("Two", "SPACE_A"),
                ),
                max_concurrency=2,
            ),
        )

    batch = asyncio.create_task(run_measurement())

    # Let the batch run as far as the blocked view. Bounded, so reporting only
    # at the end fails the test instead of hanging it.
    try:
        for _ in range(100):
            if item_results:
                break
            await asyncio.sleep(0)

        # The first model is final while the second one is still measuring
        assert [update.item_index for update in item_results] == [0]
        assert not batch.done()
    finally:
        blocked.set()

    result = await batch
    assert [update.item_index for update in item_results] == [0, 1]
    assert len(result.results) == 2


async def test_dependency_batch_reports_deduplicated_models_in_order(
) -> None:
    """
    Checks that the deduplication path reports in input order.
    """
    item_results: list[BatchItemResult] = []

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Sales"}}

    async def report_item(update: BatchItemResult) -> None:
        item_results.append(update)

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                models=[
                    _model("MODEL_1", "One", "SPACE_A"),
                    _model("MODEL_2", "Two", "SPACE_A"),
                ],
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
                dependencies=dependencies,
            ),
            batch_item_result_callback=report_item,
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(
            deduplicate_views=True
        ),
    )

    # Deduplication depends on the input order, so reporting follows it too
    assert [update.item_index for update in item_results] == [0, 1]
    assert len(result.results[0].dependencies) == 1
    assert result.results[1].dependencies == ()

    # Every reported item already carries its deduplicated result
    assert tuple(update.result for update in item_results) == result.results


def test_batch_request_rejects_an_ambiguous_model_selection() -> None:
    """
    Checks that a space cannot be combined with explicit models.
    """
    with pytest.raises(ValueError, match="Space cannot be combined"):
        GetAnalyticalModelViewDependenciesBatchRequest(
            analytical_models=(AnalyticalModelReference("One", "SPACE_A"),),
            space="SPACE_A",
        )
