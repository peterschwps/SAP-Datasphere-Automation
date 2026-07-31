from types import SimpleNamespace
from typing import Any, cast

import pytest
from datasphere_api import DatasphereClient, ViewPersistenceTimeout
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


def _client(
    models: list[dict[str, Any]],
    views: list[dict[str, Any]],
    dependencies: Any,
    *,
    persist: Any = None,
    unpersist: Any = None,
    is_persisted: bool = False,
) -> DatasphereClient:
    """
    Builds a client covering the analytical model and view calls of the
    dependency and measurement workflows.
    """
    async def get_all_analytical_models() -> list[dict[str, Any]]:
        return models

    async def get_all_views() -> list[dict[str, Any]]:
        return views

    async def check_persisted(view: str, space: str) -> bool:
        return is_persisted

    async def default_unpersist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        return True, {"status": "COMPLETED"}

    return cast(
        DatasphereClient,
        SimpleNamespace(
            analytical_models=SimpleNamespace(
                get_all_analytical_models=get_all_analytical_models,
                get_views_for_analytical_model=dependencies,
            ),
            views=SimpleNamespace(
                get_all_views=get_all_views,
                is_persisted=check_persisted,
                persist_view=persist,
                unpersist_view=unpersist or default_unpersist,
            ),
        ),
    )


async def test_dependency_batch_resolves_views_to_their_spaces() -> None:
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
    persisted: list[tuple[str, str]] = []
    unpersisted: list[tuple[str, str]] = []

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Sales"}}

    async def persist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        persisted.append((view, space))
        return True, {"status": "COMPLETED", "runTime": 4000, "logId": 11}

    async def unpersist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        unpersisted.append((view, space))
        return True, {"status": "COMPLETED", "logId": 12}

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
                dependencies=dependencies,
                persist=persist,
                unpersist=unpersist,
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
    unpersisted: list[str] = []

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Sales"}}

    async def persist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        return True, {"status": "COMPLETED", "runTime": 1000}

    async def unpersist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        unpersisted.append(view)
        return True, {}

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
                dependencies=dependencies,
                persist=persist,
                unpersist=unpersist,
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
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Sales"}}

    async def persist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        raise ViewPersistenceTimeout("persist", view, space, log_id=31)

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
                dependencies=dependencies,
                persist=persist,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest(
            analytical_model_name="One",
            space="SPACE_A",
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
    persisted: list[tuple[str, str]] = []
    item_results: list[BatchItemResult] = []

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        view_id = (
            "SHARED_1" if analytical_model_id == "MODEL_1" else "SHARED_2"
        )
        return {analytical_model_id: {view_id: "Shared"}}

    async def persist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        persisted.append((view, space))
        return True, {"status": "COMPLETED", "runTime": 2000}

    async def report_item(update: BatchItemResult) -> None:
        item_results.append(update)

    result = await measure_analytical_model_view_persistence_batch(
        CommandContext(
            client=_client(
                models=[
                    _model("MODEL_1", "One", "SPACE_A"),
                    _model("MODEL_2", "Two", "SPACE_A"),
                ],
                views=[
                    _view("SHARED_1", "Shared", "VIEW_SPACE"),
                    _view("SHARED_2", "Shared", "VIEW_SPACE"),
                ],
                dependencies=dependencies,
                persist=persist,
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

    # Each model keeps its own view ID for the shared measurement
    assert result.results[0].dependencies[0].view_id == "SHARED_1"
    assert result.results[2].dependencies[0].view_id == "SHARED_2"
    assert result.summary == BatchSummary(
        total=3,
        succeeded=2,
        failed=0,
        skipped=1,
        timed_out=0,
    )
    assert [update.item_index for update in item_results] == [0, 1, 2]


async def test_measure_skips_a_dependency_without_a_resolved_space() -> None:
    persistence_called = False

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"UNKNOWN": "Unknown"}}

    async def persist(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        nonlocal persistence_called
        persistence_called = True
        return True, {}

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "One", "SPACE_A")],
                views=[],
                dependencies=dependencies,
                persist=persist,
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


def test_batch_request_rejects_an_ambiguous_model_selection() -> None:
    with pytest.raises(ValueError, match="Space cannot be combined"):
        GetAnalyticalModelViewDependenciesBatchRequest(
            analytical_models=(AnalyticalModelReference("One", "SPACE_A"),),
            space="SPACE_A",
        )
