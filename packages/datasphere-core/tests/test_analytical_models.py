import asyncio
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
import respx
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

SEARCH_PATH = "/deepsea/repository/search/$all"
DEPENDENCIES_PATH = "/deepsea/repository/dependencies/"

# Task log IDs the default fakes report for the two runs of a measurement
PERSIST_LOG_ID = 11
CLEANUP_LOG_ID = 12


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


def _models_route(models: list[dict[str, Any]]) -> respx.Route:
    """
    Mocks the repository search that discovers the analytical models.
    """
    return respx.get(path=SEARCH_PATH).mock(
        return_value=httpx.Response(200, json={"value": models})
    )


def _dependency_tree(views: dict[str, str]) -> dict[str, Any]:
    """
    Builds the dependency tree of one analytical model, where every view is
    built on the view listed before it. The first view is therefore the
    deepest one and the mapping comes back in the order given here.
    """
    # The tenant leaves the flag out for entities that are not views
    node: dict[str, Any] = {
        "id": "LEAF",
        "name": "Leaf",
        "properties": {},
        "dependencies": [],
    }
    for view_id, view_name in views.items():
        node = {
            "id": view_id,
            "name": view_name,
            "properties": {"#isViewEntity": "true"},
            "dependencies": [node],
        }
    return {
        "id": "MODEL",
        "name": "Model",
        "properties": {"#isViewEntity": "false"},
        "dependencies": [node],
    }


def _dependencies_route(
    views_by_model: dict[str, dict[str, str]],
) -> respx.Route:
    """
    Mocks the dependency endpoint with the views of every analytical model.
    """
    def respond(request: httpx.Request) -> httpx.Response:
        model_id = request.url.params["ids"]
        return httpx.Response(
            200,
            json=[_dependency_tree(views_by_model[model_id])],
        )

    return respx.get(path=DEPENDENCIES_PATH).mock(side_effect=respond)


def _client(
    session: httpx.AsyncClient,
    views: list[dict[str, Any]],
    *,
    is_persisted: bool = False,
    **view_calls: Any,
) -> DatasphereClient:
    """
    Builds a client that sends the analytical model requests through the
    mocked session and fakes the view calls of the measurement workflow.
    Every view call can be replaced through a keyword argument.
    """
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
            session=session,
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


@respx.mock
async def test_dependency_batch_resolves_views_to_their_spaces(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that a resolved view carries its space and an unknown one does not.
    """
    search = _models_route([_model("MODEL_1", "One", "SPACE_A")])
    dependencies = _dependencies_route(
        {"MODEL_1": {"VIEW_1": "Sales", "VIEW_X": "Unknown"}}
    )

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                session,
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
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

    # The search filter is written in German, so the tenant has to answer in
    # the same language
    assert search.calls.last.request.headers["Accept-Language"] == "de"

    # Every request carries its own identifier for the tenant logs
    assert dependencies.calls.last.request.headers["x-request-id"]


@respx.mock
async def test_dependency_batch_sends_the_search_syntax_unescaped(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that the search filter reaches the tenant with its syntax intact.
    """
    search = _models_route([])

    await get_analytical_model_view_dependencies_batch(
        CommandContext(client=_client(session, views=[])),
        GetAnalyticalModelViewDependenciesBatchRequest(),
    )

    # Read the raw query: parsing it back would undo the escaping under test
    query = search.calls.last.request.url.query.decode()

    # Left to httpx, the parentheses and asterisks of the search syntax would
    # be escaped and the filter would stop matching
    assert "filter(Search.search(" in query
    assert query.endswith("%20*%27))")

    # Without a page size the search returns nothing at all
    assert "%24top=1000" in query


@respx.mock
async def test_dependency_batch_maps_nested_views_bottom_up(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that the deepest view of a dependency tree is mapped first.
    """
    _models_route([_model("MODEL_1", "One", "SPACE_A")])
    respx.get(path=DEPENDENCIES_PATH).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "MODEL_1",
                    "name": "One",
                    "properties": {"#isViewEntity": "false"},
                    "dependencies": [
                        {
                            "id": "OUTER",
                            "name": "Outer",
                            "properties": {"#isViewEntity": "true"},
                            "dependencies": [
                                {
                                    "id": "INNER",
                                    "name": "Inner",
                                    "properties": {"#isViewEntity": "true"},
                                    "dependencies": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        )
    )

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                session,
                views=[
                    _view("OUTER", "Outer", "VIEW_SPACE"),
                    _view("INNER", "Inner", "VIEW_SPACE"),
                ],
            )
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(),
    )

    # Persisting a view only pays off once the views below it are persisted
    assert [
        dependency.view_id for dependency in result.results[0].dependencies
    ] == ["INNER", "OUTER"]


@respx.mock
async def test_dependency_batch_selects_the_models_of_one_space(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that a space filter keeps only the models of that space.
    """
    _models_route(
        [
            _model("MODEL_1", "One", "SPACE_A"),
            _model("MODEL_2", "Two", "OTHER_SPACE"),
        ]
    )
    _dependencies_route({"MODEL_1": {"VIEW_1": "Sales"}})

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                session,
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
            )
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(space="SPACE_A"),
    )

    assert [item.analytical_model_name for item in result.results] == ["One"]


@respx.mock
async def test_dependency_batch_reports_a_missing_model_as_skipped(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that a model the tenant does not know is skipped, not failed.
    """
    # No dependency route: a missing model must not be looked up at all
    _models_route([_model("MODEL_1", "One", "SPACE_A")])

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(session, views=[]),
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(
            analytical_models=(AnalyticalModelReference("Missing", "SPACE_A"),)
        ),
    )

    assert result.results[0].status is (
        AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND
    )
    assert result.summary.skipped == 1


@respx.mock
async def test_dependency_batch_deduplicates_shared_views(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that a shared view stays with the first model claiming it.
    """
    _models_route(
        [
            _model("MODEL_1", "One", "SPACE_A"),
            _model("MODEL_2", "Two", "SPACE_A"),
        ]
    )
    _dependencies_route(
        {
            "MODEL_1": {"VIEW_1": "Sales"},
            "MODEL_2": {"VIEW_1": "Sales"},
        }
    )

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                session,
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
            )
        ),
        GetAnalyticalModelViewDependenciesBatchRequest(
            deduplicate_views=True
        ),
    )

    # The shared view stays with the first model only
    assert len(result.results[0].dependencies) == 1
    assert result.results[1].dependencies == ()


@respx.mock
async def test_measure_persists_a_view_and_removes_it_again(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that a measured view is persisted and cleaned up again.
    """
    persisted: list[tuple[str, str]] = []
    unpersisted: list[tuple[str, str]] = []

    _models_route([_model("MODEL_1", "One", "SPACE_A")])
    _dependencies_route({"MODEL_1": {"VIEW_1": "Sales"}})

    async def start_persistence(view: str, space: str) -> int | None:
        persisted.append((view, space))
        return PERSIST_LOG_ID

    async def start_persistence_removal(view: str, space: str) -> int | None:
        unpersisted.append((view, space))
        return CLEANUP_LOG_ID

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                session,
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
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


@respx.mock
async def test_measure_keeps_a_view_that_was_persisted_before(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that a view persisted before the run keeps its persistence.
    """
    unpersisted: list[str] = []

    _models_route([_model("MODEL_1", "One", "SPACE_A")])
    _dependencies_route({"MODEL_1": {"VIEW_1": "Sales"}})

    async def start_persistence_removal(view: str, space: str) -> int | None:
        unpersisted.append(view)
        return CLEANUP_LOG_ID

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                session,
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
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


@respx.mock
async def test_measure_reports_a_timeout_as_needing_manual_action(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that a timed-out persistence is flagged for manual intervention.
    """
    _models_route([_model("MODEL_1", "One", "SPACE_A")])
    _dependencies_route({"MODEL_1": {"VIEW_1": "Sales"}})

    async def start_persistence(view: str, space: str) -> int | None:
        return 31

    # The run never leaves the running state, so the timeout decides
    async def get_extended_log(log_id: int, space: str) -> dict[str, Any]:
        return {"status": "RUNNING", "runTime": 1000}

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                session,
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
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


@respx.mock
async def test_measure_batch_runs_a_shared_view_once_and_projects_it(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that a view shared by two models is measured once and projected onto
    both of them.
    """
    persisted: list[tuple[str, str]] = []
    item_results: list[BatchItemResult] = []

    _models_route(
        [
            _model("MODEL_1", "One", "SPACE_A"),
            _model("MODEL_2", "Two", "SPACE_A"),
        ]
    )

    # Both models depend on the very same view
    _dependencies_route(
        {
            "MODEL_1": {"SHARED": "Shared"},
            "MODEL_2": {"SHARED": "Shared"},
        }
    )

    async def start_persistence(view: str, space: str) -> int | None:
        persisted.append((view, space))
        return PERSIST_LOG_ID

    async def report_item(update: BatchItemResult) -> None:
        item_results.append(update)

    result = await measure_analytical_model_view_persistence_batch(
        CommandContext(
            client=_client(
                session,
                views=[_view("SHARED", "Shared", "VIEW_SPACE")],
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


@respx.mock
async def test_measure_skips_a_dependency_without_a_resolved_space(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that an unresolved dependency is never persisted.
    """
    persistence_called = False

    _models_route([_model("MODEL_1", "One", "SPACE_A")])
    _dependencies_route({"MODEL_1": {"UNKNOWN": "Unknown"}})

    async def start_persistence(view: str, space: str) -> int | None:
        nonlocal persistence_called
        persistence_called = True
        return PERSIST_LOG_ID

    result = await measure_analytical_model_view_persistence(
        CommandContext(
            client=_client(
                session,
                views=[],
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


@respx.mock
async def test_measure_batch_reports_a_model_before_the_batch_finished(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that a completed model is reported while others still run.
    """
    item_results: list[BatchItemResult] = []
    blocked = asyncio.Event()

    _models_route(
        [
            _model("MODEL_1", "One", "SPACE_A"),
            _model("MODEL_2", "Two", "SPACE_A"),
        ]
    )

    # Each model depends on a view of its own
    _dependencies_route(
        {
            "MODEL_1": {"VIEW_1": "View1"},
            "MODEL_2": {"VIEW_2": "View2"},
        }
    )

    # The view of the second model blocks until the test releases it
    async def start_persistence(view: str, space: str) -> int | None:
        if view == "View2":
            await blocked.wait()
        return PERSIST_LOG_ID

    async def report_item(update: BatchItemResult) -> None:
        item_results.append(update)

    context = CommandContext(
        client=_client(
            session,
            views=[
                _view("VIEW_1", "View1", "VIEW_SPACE"),
                _view("VIEW_2", "View2", "VIEW_SPACE"),
            ],
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


@respx.mock
async def test_dependency_batch_reports_deduplicated_models_in_order(
    session: httpx.AsyncClient,
) -> None:
    """
    Checks that the deduplication path reports in input order.
    """
    item_results: list[BatchItemResult] = []

    _models_route(
        [
            _model("MODEL_1", "One", "SPACE_A"),
            _model("MODEL_2", "Two", "SPACE_A"),
        ]
    )
    _dependencies_route(
        {
            "MODEL_1": {"VIEW_1": "Sales"},
            "MODEL_2": {"VIEW_1": "Sales"},
        }
    )

    async def report_item(update: BatchItemResult) -> None:
        item_results.append(update)

    result = await get_analytical_model_view_dependencies_batch(
        CommandContext(
            client=_client(
                session,
                views=[_view("VIEW_1", "Sales", "VIEW_SPACE")],
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
