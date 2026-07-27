import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from datasphere_api import (
    DatasphereClient,
    ViewPersistenceCancelled,
    ViewPersistenceTimeout,
)
from datasphere_api.models import (
    AnalyticalModelsDetailsDict,
    ViewDetailsDict,
)
from datasphere_core.commands.analytical_models import (
    ANALYTICAL_MODELS_COMMAND_DEFINITIONS,
    get_analytical_model_view_dependencies,
    get_analytical_model_view_dependencies_batch,
    measure_analytical_model_view_persistence,
    measure_analytical_model_view_persistence_batch,
)
from datasphere_core.context import CommandContext
from datasphere_core.models.analytical_models import (
    AnalyticalModelReference,
    GetAnalyticalModelViewDependenciesBatchRequest,
    GetAnalyticalModelViewDependenciesRequest,
    MeasureAnalyticalModelViewPersistenceBatchRequest,
    MeasureAnalyticalModelViewPersistenceRequest,
)
from datasphere_core.models.common import (
    MAXIMUM_BATCH_CONCURRENCY,
    BatchItemResult,
    BatchSummary,
    CommandProgress,
)

type DependencyMap = dict[str, dict[str, str]]
type Persist = Callable[
    [str, str, float], Awaitable[tuple[bool, dict[str, Any]]]
]


def _model(
    analytical_model_id: str,
    analytical_model_name: str,
    space: str,
) -> AnalyticalModelsDetailsDict:
    return cast(
        AnalyticalModelsDetailsDict,
        {
            "id": analytical_model_id,
            "name": analytical_model_name,
            "space_name": space,
        },
    )


def _view(view_id: str, view_name: str, space: str) -> ViewDetailsDict:
    return cast(
        ViewDetailsDict,
        {"id": view_id, "name": view_name, "space_name": space},
    )


def _client(
    *,
    models: list[AnalyticalModelsDetailsDict],
    views: list[ViewDetailsDict],
    dependencies: Callable[[str], Awaitable[DependencyMap]],
    is_persisted: Callable[[str, str], Awaitable[bool]] | None = None,
    persist: Persist | None = None,
    unpersist: Persist | None = None,
) -> DatasphereClient:
    async def get_all_models() -> list[AnalyticalModelsDetailsDict]:
        return models

    async def get_all_views() -> list[ViewDetailsDict]:
        return views

    async def default_is_persisted(view: str, space: str) -> bool:
        return False

    async def default_persist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        return True, {"status": "COMPLETED", "runTime": 1000}

    async def default_unpersist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        return True, {"status": "COMPLETED"}

    persist_operation = persist or default_persist
    unpersist_operation = unpersist or default_unpersist

    async def persist_view(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        assert timeout_seconds is not None
        return await persist_operation(view, space, timeout_seconds)

    async def unpersist_view(
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        assert timeout_seconds is not None
        return await unpersist_operation(view, space, timeout_seconds)

    return cast(
        DatasphereClient,
        SimpleNamespace(
            analytical_models=SimpleNamespace(
                get_all_analytical_models=get_all_models,
                get_views_for_analytical_model=dependencies,
            ),
            views=SimpleNamespace(
                get_all_views=get_all_views,
                is_persisted=is_persisted or default_is_persisted,
                persist_view=persist_view,
                unpersist_view=unpersist_view,
            ),
        ),
    )


async def test_get_dependencies_preserves_api_order_and_maps_spaces() -> None:
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        assert analytical_model_id == "MODEL_1"
        return {
            analytical_model_id: {
                "VIEW_2": "Second",
                "VIEW_1": "First",
            }
        }

    result = await get_analytical_model_view_dependencies(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "Sales", "SPACE_A")],
                views=[
                    _view("VIEW_1", "First", "SPACE_A"),
                    _view("VIEW_2", "Second", "SPACE_B"),
                ],
                dependencies=dependencies,
            )
        ),
        GetAnalyticalModelViewDependenciesRequest(
            analytical_model_name="Sales", space="SPACE_A"
        ),
    )

    assert result.status == "completed"
    assert result.analytical_model_id == "MODEL_1"
    assert [item.view_id for item in result.dependencies] == [
        "VIEW_2",
        "VIEW_1",
    ]
    assert [item.space for item in result.dependencies] == [
        "SPACE_B",
        "SPACE_A",
    ]


async def test_get_dependencies_returns_typed_not_found_results() -> None:
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"MISSING_VIEW": "Missing"}}

    client = _client(
        models=[_model("MODEL_1", "Sales", "SPACE_A")],
        views=[],
        dependencies=dependencies,
    )
    missing_dependency = await get_analytical_model_view_dependencies(
        CommandContext(client=client),
        GetAnalyticalModelViewDependenciesRequest("Sales", "SPACE_A"),
    )
    missing_model = await get_analytical_model_view_dependencies(
        CommandContext(client=client),
        GetAnalyticalModelViewDependenciesRequest("Unknown", "SPACE_A"),
    )

    assert missing_dependency.status == "dependency_not_found"
    assert missing_dependency.dependencies[0].status == "not_found"
    assert missing_dependency.dependencies[0].space is None
    assert missing_model.status == "analytical_model_not_found"
    assert missing_model.analytical_model_id is None
    assert missing_model.dependencies == ()


async def test_dependency_batch_deduplicates_in_input_and_api_order() -> None:
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        mappings = {
            "MODEL_1": {"SHARED": "Shared", "VIEW_1": "One"},
            "MODEL_2": {"VIEW_2": "Two", "SHARED": "Shared"},
        }
        return {analytical_model_id: mappings[analytical_model_id]}

    progress: list[CommandProgress] = []
    item_results: list[BatchItemResult] = []

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def report_item_result(update: BatchItemResult) -> None:
        item_results.append(update)

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                models=[
                    _model("MODEL_1", "One", "SPACE_A"),
                    _model("MODEL_2", "Two", "SPACE_A"),
                ],
                views=[
                    _view("SHARED", "Shared", "SPACE_A"),
                    _view("VIEW_1", "One", "SPACE_A"),
                    _view("VIEW_2", "Two", "SPACE_A"),
                ],
                dependencies=dependencies,
            ),
            progress_callback=report,
            batch_item_result_callback=report_item_result,
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(
            analytical_models=(
                AnalyticalModelReference("Two", "SPACE_A"),
                AnalyticalModelReference("Missing", "SPACE_A"),
                AnalyticalModelReference("One", "SPACE_A"),
            ),
            deduplicate_views=True,
            max_concurrency=2,
        ),
    )

    assert [item.analytical_model_name for item in result.results] == [
        "Two",
        "Missing",
        "One",
    ]
    assert [
        tuple(item.view_id for item in model.dependencies)
        for model in result.results
    ] == [("VIEW_2", "SHARED"), (), ("VIEW_1",)]
    assert result.summary == BatchSummary(3, 2, 0, 1, 0)
    assert [update.phase for update in progress] == [
        "started",
        "advanced",
        "advanced",
        "advanced",
        "completed",
    ]
    assert progress[-1].completed_items == 3
    assert progress[-1].skipped_items == 1
    assert [update.item_index for update in item_results] == [0, 1, 2]
    assert tuple(update.result for update in item_results) == result.results


async def test_dependency_batch_reports_each_result_when_not_deduplicating(
) -> None:
    release_first = asyncio.Event()
    second_result_reported = asyncio.Event()
    item_results: list[BatchItemResult] = []
    progress: list[CommandProgress] = []

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        if analytical_model_id == "MODEL_A":
            await release_first.wait()
        return {analytical_model_id: {}}

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def report_item_result(update: BatchItemResult) -> None:
        item_results.append(update)
        if update.item_index == 1:
            second_result_reported.set()

    task = asyncio.create_task(
        get_analytical_model_view_dependencies_batch(
            CommandContext(
                client=_client(
                    models=[
                        _model("MODEL_A", "A", "SPACE_A"),
                        _model("MODEL_B", "B", "SPACE_A"),
                    ],
                    views=[],
                    dependencies=dependencies,
                ),
                progress_callback=report,
                batch_item_result_callback=report_item_result,
            ),
            GetAnalyticalModelViewDependenciesBatchRequest(
                analytical_models=(
                    AnalyticalModelReference("A", "SPACE_A"),
                    AnalyticalModelReference("B", "SPACE_A"),
                ),
                deduplicate_views=False,
                max_concurrency=2,
            ),
        )
    )

    await second_result_reported.wait()
    assert [update.item_index for update in item_results] == [1]
    assert task.done() is False

    release_first.set()
    result = await task

    assert [update.item_index for update in item_results] == [1, 0]
    assert [item.analytical_model_name for item in result.results] == [
        "A",
        "B",
    ]
    assert result.summary == BatchSummary(2, 2, 0, 0, 0)
    assert [update.phase for update in progress] == [
        "started",
        "advanced",
        "advanced",
        "completed",
    ]


async def test_dependency_batch_filters_all_models_by_space_and_is_bounded(
) -> None:
    active = 0
    maximum_active = 0
    release = asyncio.Event()

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            if active == 2:
                release.set()
            await release.wait()
            await asyncio.sleep(0)
            return {analytical_model_id: {}}
        finally:
            active -= 1

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                models=[
                    _model("A", "A", "SPACE_A"),
                    _model("B", "B", "SPACE_A"),
                    _model("C", "C", "SPACE_B"),
                ],
                views=[],
                dependencies=dependencies,
            )
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(
            space="SPACE_A", max_concurrency=2
        ),
    )

    assert [item.analytical_model_name for item in result.results] == [
        "A",
        "B",
    ]
    assert maximum_active == 2


async def test_dependency_dedup_keeps_unresolved_source_statuses() -> None:
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"MISSING": "Missing"}}

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                models=[
                    _model("MODEL_1", "One", "SPACE_A"),
                    _model("MODEL_2", "Two", "SPACE_A"),
                ],
                views=[],
                dependencies=dependencies,
            )
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(
            analytical_models=(
                AnalyticalModelReference("One", "SPACE_A"),
                AnalyticalModelReference("Two", "SPACE_A"),
            ),
            deduplicate_views=True,
        ),
    )

    assert [item.status for item in result.results] == [
        "dependency_not_found",
        "dependency_not_found",
    ]
    assert [
        tuple(item.view_id for item in model.dependencies)
        for model in result.results
    ] == [("MISSING",), ("MISSING",)]
    assert result.summary == BatchSummary(2, 0, 2, 0, 0)


async def test_measure_temporary_persistence_collects_and_cleans_up() -> None:
    calls: list[tuple[str, str, str, float]] = []

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Physical"}}

    async def persist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        calls.append(("persist", view, space, timeout))
        return True, {
            "status": "COMPLETED",
            "runTime": 65432,
            "logId": 101,
        }

    async def unpersist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        calls.append(("unpersist", view, space, timeout))
        return True, {"status": "COMPLETED", "logId": 102}

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "Sales", "MODEL_SPACE")],
                views=[_view("VIEW_1", "Physical", "VIEW_SPACE")],
                dependencies=dependencies,
                persist=persist,
                unpersist=unpersist,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest(
            "Sales", "MODEL_SPACE", timeout_seconds=12.0
        ),
    )

    assert result.status == "completed"
    item = result.dependencies[0]
    assert item.status == "completed"
    assert item.previously_persisted is False
    assert item.runtime_seconds == 65
    assert item.persistence_sap_status == "COMPLETED"
    assert item.persistence_log_id == "101"
    assert item.cleanup_sap_status == "COMPLETED"
    assert item.cleanup_log_id == "102"
    assert item.persistence_removed is True
    assert item.manual_intervention is False
    assert calls == [
        ("persist", "Physical", "VIEW_SPACE", 12.0),
        ("unpersist", "Physical", "VIEW_SPACE", 12.0),
    ]


async def test_measure_does_not_clean_up_previously_persisted_view() -> None:
    cleanup_called = False

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Physical"}}

    async def is_persisted(view: str, space: str) -> bool:
        return True

    async def unpersist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        nonlocal cleanup_called
        cleanup_called = True
        return True, {}

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "Sales", "SPACE_A")],
                views=[_view("VIEW_1", "Physical", "SPACE_A")],
                dependencies=dependencies,
                is_persisted=is_persisted,
                unpersist=unpersist,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest("Sales", "SPACE_A"),
    )

    assert result.dependencies[0].status == "already_persisted"
    assert result.dependencies[0].persistence_removed is False
    assert cleanup_called is False


@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_measure_represents_persist_and_cleanup_failures(
    cleanup_failure: bool,
) -> None:
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Physical"}}

    async def persist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        return cleanup_failure, {"status": "FAILED", "logId": 201}

    async def unpersist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        return False, {"status": "FAILED", "logId": 202}

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "Sales", "SPACE_A")],
                views=[_view("VIEW_1", "Physical", "SPACE_A")],
                dependencies=dependencies,
                persist=persist,
                unpersist=unpersist,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest("Sales", "SPACE_A"),
    )

    item = result.dependencies[0]
    assert result.status == "failed"
    assert item.status == (
        "cleanup_failed" if cleanup_failure else "persist_failed"
    )
    assert item.manual_intervention is True
    assert item.persistence_removed is False


async def test_measure_maps_cleanup_exception_to_manual_intervention() -> None:
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Physical"}}

    async def persist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        return True, {"status": "COMPLETED", "logId": 201}

    async def unpersist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        raise ConnectionError("cleanup unavailable")

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "Sales", "SPACE_A")],
                views=[_view("VIEW_1", "Physical", "SPACE_A")],
                dependencies=dependencies,
                persist=persist,
                unpersist=unpersist,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest("Sales", "SPACE_A"),
    )

    item = result.dependencies[0]
    assert result.status == "failed"
    assert item.status == "cleanup_failed"
    assert item.persistence_log_id == "201"
    assert item.persistence_removed is False
    assert item.manual_intervention is True


async def test_measure_maps_cleanup_cancellation_to_manual_intervention() -> (
    None
):
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Physical"}}

    async def unpersist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        raise ViewPersistenceCancelled("unpersist", view, space, 202)

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "Sales", "SPACE_A")],
                views=[_view("VIEW_1", "Physical", "SPACE_A")],
                dependencies=dependencies,
                unpersist=unpersist,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest("Sales", "SPACE_A"),
    )

    item = result.dependencies[0]
    assert result.status == "failed"
    assert item.status == "cleanup_failed"
    assert item.cleanup_log_id == "202"
    assert item.manual_intervention is True


async def test_measure_represents_timeout_with_log_id() -> None:
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Physical"}}

    async def persist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        raise ViewPersistenceTimeout("persist", view, space, 301)

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "Sales", "SPACE_A")],
                views=[_view("VIEW_1", "Physical", "SPACE_A")],
                dependencies=dependencies,
                persist=persist,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest("Sales", "SPACE_A"),
    )

    assert result.status == "timed_out"
    assert result.dependencies[0].status == "persist_timed_out"
    assert result.dependencies[0].persistence_log_id == "301"
    assert result.dependencies[0].manual_intervention is True


async def test_measure_represents_cleanup_timeout_with_log_id() -> None:
    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Physical"}}

    async def unpersist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        raise ViewPersistenceTimeout("unpersist", view, space, 302)

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "Sales", "SPACE_A")],
                views=[_view("VIEW_1", "Physical", "SPACE_A")],
                dependencies=dependencies,
                unpersist=unpersist,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest("Sales", "SPACE_A"),
    )

    item = result.dependencies[0]
    assert result.status == "timed_out"
    assert item.status == "cleanup_timed_out"
    assert item.cleanup_log_id == "302"
    assert item.persistence_removed is False
    assert item.manual_intervention is True


async def test_measure_batch_executes_shared_physical_view_once_and_projects(
) -> None:
    persisted: list[tuple[str, str]] = []
    progress: list[CommandProgress] = []
    item_results: list[BatchItemResult] = []

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        view_id = (
            "SHARED_1" if analytical_model_id == "MODEL_1" else "SHARED_2"
        )
        return {analytical_model_id: {view_id: "Shared"}}

    async def persist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        persisted.append((view, space))
        return True, {"status": "COMPLETED", "runTime": 2000}

    async def report(update: CommandProgress) -> None:
        progress.append(update)

    async def report_item_result(update: BatchItemResult) -> None:
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
            progress_callback=report,
            batch_item_result_callback=report_item_result,
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

    assert persisted == [("Shared", "VIEW_SPACE")]
    assert [item.status for item in result.results] == [
        "completed",
        "analytical_model_not_found",
        "completed",
    ]
    assert result.results[0].dependencies[0].view_id == "SHARED_1"
    assert result.results[2].dependencies[0].view_id == "SHARED_2"
    assert result.summary == BatchSummary(3, 2, 0, 1, 0)
    assert [update.phase for update in progress] == [
        "started",
        "advanced",
        "advanced",
        "advanced",
        "completed",
    ]
    assert [update.item_index for update in item_results] == [0, 1, 2]
    assert tuple(update.result for update in item_results) == result.results


async def test_measure_reports_unresolved_dependency_without_execution() -> (
    None
):
    persistence_called = False

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"UNKNOWN": "Unknown"}}

    async def persist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        nonlocal persistence_called
        persistence_called = True
        return True, {}

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                models=[_model("MODEL_1", "Sales", "SPACE_A")],
                views=[],
                dependencies=dependencies,
                persist=persist,
            )
        ),
        MeasureAnalyticalModelViewPersistenceRequest("Sales", "SPACE_A"),
    )

    assert result.status == "failed"
    assert result.dependencies[0].status == "dependency_not_found"
    assert result.dependencies[0].manual_intervention is True
    assert persistence_called is False


async def test_measure_cancellation_waits_for_temporary_cleanup() -> None:
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_completed = False

    async def dependencies(analytical_model_id: str) -> DependencyMap:
        return {analytical_model_id: {"VIEW_1": "Physical"}}

    async def unpersist(
        view: str, space: str, timeout: float
    ) -> tuple[bool, dict[str, Any]]:
        nonlocal cleanup_completed
        cleanup_started.set()
        await release_cleanup.wait()
        cleanup_completed = True
        return True, {}

    task = asyncio.create_task(
        measure_analytical_model_view_persistence(
            CommandContext(
                client=_client(
                    models=[_model("MODEL_1", "Sales", "SPACE_A")],
                    views=[_view("VIEW_1", "Physical", "SPACE_A")],
                    dependencies=dependencies,
                    unpersist=unpersist,
                )
            ),
            MeasureAnalyticalModelViewPersistenceRequest("Sales", "SPACE_A"),
        )
    )
    await cleanup_started.wait()
    task.cancel()
    release_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleanup_completed is True


@pytest.mark.parametrize(
    "max_concurrency",
    [0, -1, True, 1.5, MAXIMUM_BATCH_CONCURRENCY + 1],
)
def test_analytical_model_requests_validate_concurrency(
    max_concurrency: Any,
) -> None:
    with pytest.raises(ValueError):
        GetAnalyticalModelViewDependenciesBatchRequest(
            max_concurrency=max_concurrency
        )
    with pytest.raises(ValueError):
        MeasureAnalyticalModelViewPersistenceRequest(
            "Sales", "SPACE_A", max_concurrency=max_concurrency
        )


def test_batch_selection_rejects_space_with_explicit_models() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        GetAnalyticalModelViewDependenciesBatchRequest(
            analytical_models=(AnalyticalModelReference("Sales", "SPACE_A"),),
            space="SPACE_A",
        )


def test_command_definitions_are_canonical_and_not_exposed_to_mcp() -> None:
    names = [
        definition.name for definition in ANALYTICAL_MODELS_COMMAND_DEFINITIONS
    ]
    assert names == [
        "analytical_models.get_view_dependencies",
        "analytical_models.get_view_dependencies_batch",
        "analytical_models.measure_view_persistence",
        "analytical_models.measure_view_persistence_batch",
    ]
    assert all(
        definition.expose_to_mcp is False
        for definition in ANALYTICAL_MODELS_COMMAND_DEFINITIONS
    )
