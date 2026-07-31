import asyncio
from contextlib import suppress
from dataclasses import replace
from typing import Any

from datasphere_api import ViewPersistenceCancelled, ViewPersistenceTimeout
from datasphere_api.models import AnalyticalModelsDetailsDict

from datasphere_core.context import CommandContext
from datasphere_core.conversion import runtime_to_seconds, to_text
from datasphere_core.definitions import CommandDefinition
from datasphere_core.execution import (
    batch_command,
    command,
    execute_with_concurrency_limit,
    report_batch_results,
    run_batch,
)
from datasphere_core.models.analytical_models import (
    DEFAULT_ANALYTICAL_MODEL_MAX_CONCURRENCY,
    DEFAULT_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS,
    DEFAULT_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS,
    MAXIMUM_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS,
    MAXIMUM_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS,
    AnalyticalModelDependenciesStatus,
    AnalyticalModelDependencyStatus,
    AnalyticalModelPersistenceItemStatus,
    AnalyticalModelPersistenceStatus,
    AnalyticalModelReference,
    AnalyticalModelViewDependency,
    GetAnalyticalModelViewDependenciesBatchRequest,
    GetAnalyticalModelViewDependenciesBatchResult,
    GetAnalyticalModelViewDependenciesRequest,
    GetAnalyticalModelViewDependenciesResult,
    MeasureAnalyticalModelViewPersistenceBatchRequest,
    MeasureAnalyticalModelViewPersistenceBatchResult,
    MeasureAnalyticalModelViewPersistenceItemResult,
    MeasureAnalyticalModelViewPersistenceRequest,
    MeasureAnalyticalModelViewPersistenceResult,
)

GET_VIEW_DEPENDENCIES_COMMAND_NAME = "analytical_models.get_view_dependencies"
GET_VIEW_DEPENDENCIES_BATCH_COMMAND_NAME = (
    "analytical_models.get_view_dependencies_batch"
)
MEASURE_VIEW_PERSISTENCE_COMMAND_NAME = (
    "analytical_models.measure_view_persistence"
)
MEASURE_VIEW_PERSISTENCE_BATCH_COMMAND_NAME = (
    "analytical_models.measure_view_persistence_batch"
)

# Every model is processed together with its metadata and the mapping of view
# IDs to spaces, so a batch loads both once instead of once per model.
type ResolvedModel = tuple[
    AnalyticalModelReference,
    AnalyticalModelsDetailsDict | None,
]
type DependencyItem = tuple[ResolvedModel, dict[str, str]]
type ViewKey = tuple[str, str]


def _select_models(
    all_models: list[AnalyticalModelsDetailsDict],
    analytical_models: tuple[AnalyticalModelReference, ...] | None,
    space: str | None,
) -> tuple[ResolvedModel, ...]:
    """
    Links the selected analytical models to their metadata from the API. Offers
    three options: all models, all models of one space, or a specific set of
    models.

    Args:
        all_models (list[AnalyticalModelsDetailsDict]): Details of all models
                                                        as returned by the API.
        analytical_models (tuple[AnalyticalModelReference, ...] | None):
            Explicit references to link to their metadata. None to select all
            discovered models or only those of a specific space.
        space (str | None): Optional space filter for discovered models.

    Returns:
        tuple[ResolvedModel, ...]: Selected references and their matching model
                                   details, preserving explicit input order.
    """
    # Select all models or all models of a given space
    if analytical_models is None:
        return tuple(
            (
                AnalyticalModelReference(
                    name=model["name"],
                    space=model["space_name"],
                ),
                model,
            )
            for model in all_models
            if space is None or model["space_name"] == space
        )

    # Select a specific set of models
    by_name_and_space = {
        (model["name"], model["space_name"]): model for model in all_models
    }
    return tuple(
        (reference, by_name_and_space.get((reference.name, reference.space)))
        for reference in analytical_models
    )


async def _load_model_context(
    context: CommandContext,
    analytical_models: tuple[AnalyticalModelReference, ...] | None,
    space: str | None,
) -> tuple[tuple[ResolvedModel, ...], dict[str, str]]:
    """
    Loads all analytical models and all views concurrently, links the selected
    models to their metadata, and maps every view ID to its space.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        analytical_models (tuple[AnalyticalModelReference, ...] | None):
            Explicit references to resolve. None to select all analytical
            models or only those of a specific space.
        space (str | None): Optional space filter for discovered models.

    Returns:
        tuple[tuple[ResolvedModel, ...], dict[str, str]]: Selected models with
                                                          their metadata and a
                                                          mapping of view IDs
                                                          to their spaces.
    """
    # Load all models and views
    tasks = (
        asyncio.create_task(
            context.client.analytical_models.get_all_analytical_models()
        ),
        asyncio.create_task(context.client.views.get_all_views()),
    )
    try:
        all_models, all_views = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    # Map models to their metadata
    selected = _select_models(all_models, analytical_models, space)

    # Map view IDs to their spaces
    spaces_by_view_id = {view["id"]: view["space_name"] for view in all_views}
    return selected, spaces_by_view_id


async def _resolve_dependencies(
    context: CommandContext,
    item: DependencyItem,
) -> GetAnalyticalModelViewDependenciesResult:
    """
    Resolves all view dependencies of one analytical model.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        item (DependencyItem): Tuple of the analytical model linked to its
                               metadata (which itself is a tuple) and the
                               mapping of view IDs to their spaces.

    Returns:
        GetAnalyticalModelViewDependenciesResult: Resolved view dependencies.
    """
    (reference, metadata), spaces_by_view_id = item
    if metadata is None:
        return GetAnalyticalModelViewDependenciesResult(
            analytical_model_name=reference.name,
            space=reference.space,
            status=(
                AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND
            ),
        )

    # Fetch all views used by the analytical model
    model_id = metadata["id"]
    dependencies_by_model = await (
        context.client.analytical_models.get_views_for_analytical_model(
            analytical_model_id=model_id
        )
    )

    # Fetch view dependencies of the analytical model
    # If a view doesn't have a space, it means that it could not be resolved
    dependencies = tuple(
        AnalyticalModelViewDependency(
            view_id=view_id,
            view_name=view_name,
            space=spaces_by_view_id.get(view_id),
            status=(
                AnalyticalModelDependencyStatus.RESOLVED
                if view_id in spaces_by_view_id
                else AnalyticalModelDependencyStatus.NOT_FOUND
            ),
        )
        for view_id, view_name in dependencies_by_model[model_id].items()
    )

    return GetAnalyticalModelViewDependenciesResult(
        analytical_model_name=reference.name,
        space=reference.space,
        analytical_model_id=model_id,
        status=(
            AnalyticalModelDependenciesStatus.DEPENDENCY_NOT_FOUND
            if any(
                dependency.status
                is AnalyticalModelDependencyStatus.NOT_FOUND
                for dependency in dependencies
            )
            else AnalyticalModelDependenciesStatus.COMPLETED
        ),
        dependencies=dependencies,
    )


async def _resolve_selected_models(
    context: CommandContext,
    analytical_models: tuple[AnalyticalModelReference, ...] | None,
    space: str | None,
    max_concurrency: int,
) -> tuple[GetAnalyticalModelViewDependenciesResult, ...]:
    """
    Loads the model context and resolves the view dependencies of every
    selected analytical model with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        analytical_models (tuple[AnalyticalModelReference, ...] | None):
            Explicit references to resolve. None to select all analytical
            models or only those of a specific space (if ``space`` is set).
        space (str | None): Optional space filter for discovered models.
        max_concurrency (int): Maximum amount of concurrent tasks.

    Returns:
        tuple[GetAnalyticalModelViewDependenciesResult, ...]: Results in model
                                                              selection order.
    """
    selected, spaces_by_view_id = await _load_model_context(
        context,
        analytical_models,
        space,
    )
    return await execute_with_concurrency_limit(
        items=tuple((model, spaces_by_view_id) for model in selected),
        operation=lambda item: _resolve_dependencies(context, item),
        max_concurrency=max_concurrency,
    )


def _deduplicate_dependencies(
    results: tuple[GetAnalyticalModelViewDependenciesResult, ...],
) -> tuple[GetAnalyticalModelViewDependenciesResult, ...]:
    """
    Removes repeated resolved views while preserving the result order. This
    ensures that views shared by several analytical models are only processed
    once.

    Args:
        results (tuple[GetAnalyticalModelViewDependenciesResult, ...]):
            Dependency results to deduplicate.

    Returns:
        tuple[GetAnalyticalModelViewDependenciesResult, ...]: Results with
                                                              duplicate
                                                              dependencies
                                                              removed.
    """
    seen: set[tuple[str | None, str]] = set()
    deduplicated: list[GetAnalyticalModelViewDependenciesResult] = []

    # Iterate over each analytical model
    for result in results:
        dependencies: list[AnalyticalModelViewDependency] = []

        # Iterate over each dependency of the analytical model
        for dependency in result.dependencies:

            # Keep every view that could not be mapped
            if dependency.status is AnalyticalModelDependencyStatus.NOT_FOUND:
                dependencies.append(dependency)
                continue

            # Skip previously seen views and remember new ones
            key = (dependency.space, dependency.view_id)
            if key in seen:
                continue

            seen.add(key)
            dependencies.append(dependency)

        # Add new result without duplicates to deduplicated
        deduplicated.append(
            replace(result, dependencies=tuple(dependencies))
        )

    return tuple(deduplicated)


@command(GET_VIEW_DEPENDENCIES_COMMAND_NAME)
async def get_analytical_model_view_dependencies(
    context: CommandContext,
    request: GetAnalyticalModelViewDependenciesRequest,
) -> GetAnalyticalModelViewDependenciesResult:
    """
    Resolves the view dependencies of one analytical model.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (GetAnalyticalModelViewDependenciesRequest): Input to resolve
                                                             the dependencies.

    Returns:
        GetAnalyticalModelViewDependenciesResult: Result of resolving the
                                                  dependencies.
    """
    reference = AnalyticalModelReference(
        name=request.analytical_model_name,
        space=request.space,
    )
    results = await _resolve_selected_models(
        context,
        analytical_models=(reference,),
        space=None,
        max_concurrency=DEFAULT_ANALYTICAL_MODEL_MAX_CONCURRENCY,
    )
    return results[0]


@batch_command(GET_VIEW_DEPENDENCIES_BATCH_COMMAND_NAME)
async def get_analytical_model_view_dependencies_batch(
    context: CommandContext,
    request: GetAnalyticalModelViewDependenciesBatchRequest,
) -> GetAnalyticalModelViewDependenciesBatchResult:
    """
    Loads and optionally deduplicates the view dependencies of selected
    analytical models with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (GetAnalyticalModelViewDependenciesBatchRequest): Input to
                                                                  resolve the
                                                                  dependencies.

    Returns:
        GetAnalyticalModelViewDependenciesBatchResult: Ordered results of
                                                       resolving the
                                                       dependencies.
    """
    selected, spaces_by_view_id = await _load_model_context(
        context,
        request.analytical_models,
        request.space,
    )

    # Without deduplication every model is an independent batch item, so its
    # result can be reported as soon as it is resolved
    if not request.deduplicate_views:
        results, summary = await run_batch(
            context,
            GET_VIEW_DEPENDENCIES_BATCH_COMMAND_NAME,
            tuple((model, spaces_by_view_id) for model in selected),
            _resolve_dependencies,
            max_concurrency=request.max_concurrency,
        )
        return GetAnalyticalModelViewDependenciesBatchResult(
            results=results,
            summary=summary,
        )

    # Deduplication needs every result before any of them is final, so the
    # results are resolved first and reported afterwards
    results = await execute_with_concurrency_limit(
        items=tuple((model, spaces_by_view_id) for model in selected),
        operation=lambda item: _resolve_dependencies(context, item),
        max_concurrency=request.max_concurrency,
    )
    results = _deduplicate_dependencies(results)
    summary = await report_batch_results(
        context,
        GET_VIEW_DEPENDENCIES_BATCH_COMMAND_NAME,
        results,
    )
    return GetAnalyticalModelViewDependenciesBatchResult(
        results=results,
        summary=summary,
    )


def _create_measurement_result(
    dependency: AnalyticalModelViewDependency,
    *,
    status: AnalyticalModelPersistenceItemStatus,
    previously_persisted: bool | None,
    persistence_details: dict[str, Any] | None = None,
    cleanup_details: dict[str, Any] | None = None,
    persistence_log_id: str | None = None,
    cleanup_log_id: str | None = None,
    persistence_removed: bool = False,
    manual_intervention: bool = False,
) -> MeasureAnalyticalModelViewPersistenceItemResult:
    """
    Builds the persistence measurement result of one view dependency.

    Args:
        dependency (AnalyticalModelViewDependency): View dependency measured.
        status (AnalyticalModelPersistenceItemStatus): Outcome of the item.
        previously_persisted (bool | None): State observed before the
                                            measurement.
        persistence_details (dict[str, Any] | None, optional):
            Persistence details as returned by Datasphere. Defaults to None.
        cleanup_details (dict[str, Any] | None, optional):
            Details of the cleanup action as returned by Datasphere. Defaults
            to None.
        persistence_log_id (str | None, optional): Log ID of the persistence
                                                   run. Defaults to None.
        cleanup_log_id (str | None, optional): Log ID of the cleanup action.
                                               Defaults to None.
        persistence_removed (bool, optional): Whether the temporary persistence
                                              was removed. Defaults to False.
        manual_intervention (bool, optional): Whether manual action may be
                                              needed. Defaults to False.

    Returns:
        MeasureAnalyticalModelViewPersistenceItemResult: Result of measuring
                                                         the persistence
                                                         runtime of one view.
    """
    persistence_details = persistence_details or {}
    cleanup_details = cleanup_details or {}
    return MeasureAnalyticalModelViewPersistenceItemResult(
        view_id=dependency.view_id,
        view_name=dependency.view_name,
        space=dependency.space,
        status=status,
        previously_persisted=previously_persisted,
        runtime_seconds=runtime_to_seconds(persistence_details),
        persistence_sap_status=to_text(persistence_details.get("status")),
        persistence_log_id=(
            persistence_log_id or to_text(persistence_details.get("logId"))
        ),
        cleanup_sap_status=to_text(cleanup_details.get("status")),
        cleanup_log_id=(
            cleanup_log_id or to_text(cleanup_details.get("logId"))
        ),
        persistence_removed=persistence_removed,
        manual_intervention=manual_intervention,
    )


async def _run_cleanup(
    context: CommandContext,
    dependency: AnalyticalModelViewDependency,
    space: str,
    timeout_seconds: float,
) -> tuple[bool, dict[str, Any], str | None]:
    """
    Removes the temporary persistence from one measured view. The cleanup is
    shielded so that it still finishes if the surrounding command is
    cancelled - otherwise the view would stay persisted.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        dependency (AnalyticalModelViewDependency): View to remove the
                                                    persistence for.
        space (str): Resolved space of the view.
        timeout_seconds (float): Maximum cleanup duration in seconds.

    Returns:
        tuple[bool, dict[str, Any], str | None]: Whether the cleanup succeeded,
                                                 the cleanup details, and an
                                                 optional log identifier of a
                                                 cancelled cleanup.
    """
    async def cleanup() -> tuple[bool, dict[str, Any], str | None]:
        """
        Invokes the API cleanup operation for the view dependency.

        Returns:
            tuple[bool, dict[str, Any], str | None]: Cleanup outcome, details,
                                                     and the log ID of a
                                                     cancelled cleanup.
        """
        try:
            cleaned_up, details = await context.client.views.unpersist_view(
                view=dependency.view_name,
                space=space,
                timeout_seconds=timeout_seconds,
            )
        except ViewPersistenceCancelled as error:
            return False, {}, to_text(error.log_id)

        return cleaned_up, details, None

    task = asyncio.create_task(cleanup())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with suppress(BaseException):
            await task
        raise


async def _measure_view(
    context: CommandContext,
    dependency: AnalyticalModelViewDependency,
    timeout_seconds: float,
) -> MeasureAnalyticalModelViewPersistenceItemResult:
    """
    Measures the persistence runtime of one view and restores its previous
    persistence state afterwards.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        dependency (AnalyticalModelViewDependency): Resolved view dependency to
                                                    measure.
        timeout_seconds (float): Maximum duration for persistence and cleanup.

    Raises:
        ViewPersistenceCancelled: If the API persistence operation is
                                  cancelled.

    Returns:
        MeasureAnalyticalModelViewPersistenceItemResult: Result of measuring
                                                         the view's persistence
                                                         runtime.
    """
    space = dependency.space
    assert space is not None, "Only resolved dependencies can be measured."

    # Check if the view is already persisted
    previously_persisted = await context.client.views.is_persisted(
        view=dependency.view_name,
        space=space,
    )

    # Start the persistence run
    try:
        persisted, persistence_details = (
            await context.client.views.persist_view(
                dependency.view_name,
                space,
                timeout_seconds=timeout_seconds,
            )
        )
    except ViewPersistenceTimeout as error:
        return _create_measurement_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.PERSIST_TIMED_OUT,
            previously_persisted=previously_persisted,
            persistence_log_id=to_text(error.log_id),
            manual_intervention=True,
        )

    # Return if the persistence run failed
    if not persisted:
        return _create_measurement_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.PERSIST_FAILED,
            previously_persisted=previously_persisted,
            persistence_details=persistence_details,
            manual_intervention=not previously_persisted,
        )

    # Return without cleanup if the view was already persisted before
    if previously_persisted:
        return _create_measurement_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.ALREADY_PERSISTED,
            previously_persisted=True,
            persistence_details=persistence_details,
        )

    # Remove the temporary persistence again
    try:
        cleaned_up, cleanup_details, cleanup_log_id = await _run_cleanup(
            context,
            dependency,
            space,
            timeout_seconds,
        )
    except ViewPersistenceTimeout as error:
        return _create_measurement_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.CLEANUP_TIMED_OUT,
            previously_persisted=False,
            persistence_details=persistence_details,
            cleanup_log_id=to_text(error.log_id),
            manual_intervention=True,
        )
    except Exception as error:
        return _create_measurement_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.CLEANUP_FAILED,
            previously_persisted=False,
            persistence_details=persistence_details,
            cleanup_log_id=to_text(getattr(error, "log_id", None)),
            manual_intervention=True,
        )

    if not cleaned_up:
        return _create_measurement_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.CLEANUP_FAILED,
            previously_persisted=False,
            persistence_details=persistence_details,
            cleanup_details=cleanup_details,
            cleanup_log_id=cleanup_log_id,
            manual_intervention=True,
        )
    return _create_measurement_result(
        dependency,
        status=AnalyticalModelPersistenceItemStatus.COMPLETED,
        previously_persisted=False,
        persistence_details=persistence_details,
        cleanup_details=cleanup_details,
        persistence_removed=True,
    )


async def _measure_dependencies(
    context: CommandContext,
    dependency_results: tuple[GetAnalyticalModelViewDependenciesResult, ...],
    timeout_seconds: float,
    max_concurrency: int,
) -> tuple[MeasureAnalyticalModelViewPersistenceResult, ...]:
    """
    Measures every unique view once and projects its measurement onto each
    analytical model that depends on it.

    Example: Model A depends on views X and Y, model B on views Y and Z. View Y
             is then measured once, but its result appears in the results of
             both model A and model B.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        dependency_results (tuple[GetAnalyticalModelViewDependenciesResult,
                                  ...]):
            Analytical models with the dependencies to measure.
        timeout_seconds (float): Maximum duration for persisting each view.
        max_concurrency (int): Maximum amount of concurrent tasks.

    Returns:
        tuple[MeasureAnalyticalModelViewPersistenceResult, ...]: Ordered
            results of the measured view persistence runtimes.
    """
    # Collect every resolved view exactly once
    unique_dependencies: list[AnalyticalModelViewDependency] = []
    seen: set[ViewKey] = set()
    for result in dependency_results:
        for dependency in result.dependencies:
            if dependency.space is None:
                continue
            key = (dependency.space, dependency.view_name)
            if key not in seen:
                seen.add(key)
                unique_dependencies.append(dependency)

    # Measure the unique views with concurrency
    measured = await execute_with_concurrency_limit(
        items=tuple(unique_dependencies),
        operation=lambda dependency: _measure_view(
            context,
            dependency,
            timeout_seconds,
        ),
        max_concurrency=max_concurrency,
    )
    measurement_by_view = {
        (item.space, item.view_name): item for item in measured
    }

    # Project the measurements back onto every analytical model
    results: list[MeasureAnalyticalModelViewPersistenceResult] = []
    for result in dependency_results:
        if result.status is (
            AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND
        ):
            results.append(
                MeasureAnalyticalModelViewPersistenceResult(
                    analytical_model_name=result.analytical_model_name,
                    space=result.space,
                    status=(
                        AnalyticalModelPersistenceStatus
                        .ANALYTICAL_MODEL_NOT_FOUND
                    ),
                )
            )
            continue

        # Several analytical models can reference the same view under
        # their own view ID, so the shared measurement keeps that ID per model
        dependencies = tuple(
            replace(
                measurement_by_view[
                    (dependency.space, dependency.view_name)
                ],
                view_id=dependency.view_id,
            )
            if dependency.space is not None
            else MeasureAnalyticalModelViewPersistenceItemResult(
                view_id=dependency.view_id,
                view_name=dependency.view_name,
                space=None,
                status=(
                    AnalyticalModelPersistenceItemStatus.DEPENDENCY_NOT_FOUND
                ),
                manual_intervention=True,
            )
            for dependency in result.dependencies
        )

        # Derive status from all view measurements of the analytical model
        if any(
                item.status
                in {
                    AnalyticalModelPersistenceItemStatus.PERSIST_TIMED_OUT,
                    AnalyticalModelPersistenceItemStatus.CLEANUP_TIMED_OUT,
                }
                for item in dependencies
            ):
                status = AnalyticalModelPersistenceStatus.TIMED_OUT
        elif any(
            item.status
            not in {
                AnalyticalModelPersistenceItemStatus.COMPLETED,
                AnalyticalModelPersistenceItemStatus.ALREADY_PERSISTED,
            }
            for item in dependencies
        ):
            status = AnalyticalModelPersistenceStatus.FAILED
        else:
            status = AnalyticalModelPersistenceStatus.COMPLETED

        # Add analytical model with all its view runtime measurements to the
        # results
        results.append(
            MeasureAnalyticalModelViewPersistenceResult(
                analytical_model_name=result.analytical_model_name,
                space=result.space,
                analytical_model_id=result.analytical_model_id,
                status=status,
                dependencies=dependencies,
            )
        )
    return tuple(results)


@command(MEASURE_VIEW_PERSISTENCE_COMMAND_NAME)
async def measure_analytical_model_view_persistence(
    context: CommandContext,
    request: MeasureAnalyticalModelViewPersistenceRequest,
) -> MeasureAnalyticalModelViewPersistenceResult:
    """
    Measures the persistence runtimes of all view dependencies of one
    analytical model and restores their previous persistence state.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (MeasureAnalyticalModelViewPersistenceRequest): Input for the
                                                                measurement.

    Raises:
        ViewPersistenceCancelled: If a persistence operation is cancelled.

    Returns:
        MeasureAnalyticalModelViewPersistenceResult: Result of the measurement.
    """
    reference = AnalyticalModelReference(
        name=request.analytical_model_name,
        space=request.space,
    )

    # Resolve dependencies for the analytical model
    dependency_results = await _resolve_selected_models(
        context=context,
        analytical_models=(reference,),
        space=None,
        max_concurrency=request.max_concurrency,
    )

    # Measure the persistence runtimes of all dependencies
    results = await _measure_dependencies(
        context=context,
        dependency_results=dependency_results,
        timeout_seconds=request.timeout_seconds,
        max_concurrency=request.max_concurrency,
    )
    return results[0]


@batch_command(MEASURE_VIEW_PERSISTENCE_BATCH_COMMAND_NAME)
async def measure_analytical_model_view_persistence_batch(
    context: CommandContext,
    request: MeasureAnalyticalModelViewPersistenceBatchRequest,
) -> MeasureAnalyticalModelViewPersistenceBatchResult:
    """
    Measures the persistence runtimes of all view dependencies of selected
    analytical models with concurrency and restores their previous persistence
    state.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (MeasureAnalyticalModelViewPersistenceBatchRequest): Input for
                                                                     the
                                                                     measure-
                                                                     ments.

    Raises:
        ViewPersistenceCancelled: If a persistence operation is cancelled.

    Returns:
        MeasureAnalyticalModelViewPersistenceBatchResult: Ordered results of
                                                          the measurements.
    """
    dependency_results = await _resolve_selected_models(
        context=context,
        analytical_models=request.analytical_models,
        space=request.space,
        max_concurrency=request.max_concurrency,
    )

    # Shared views are measured only once, so the results are only final after
    # every measurement completed and can only be reported afterwards
    results = await _measure_dependencies(
        context=context,
        dependency_results=dependency_results,
        timeout_seconds=request.timeout_seconds,
        max_concurrency=request.max_concurrency,
    )

    # Report results
    summary = await report_batch_results(
        context=context,
        command=MEASURE_VIEW_PERSISTENCE_BATCH_COMMAND_NAME,
        results=results,
    )
    return MeasureAnalyticalModelViewPersistenceBatchResult(
        results=results,
        summary=summary,
    )


# Define all commands
ANALYTICAL_MODELS_GET_VIEW_DEPENDENCIES_COMMAND = CommandDefinition(
    name=GET_VIEW_DEPENDENCIES_COMMAND_NAME,
    request_type=GetAnalyticalModelViewDependenciesRequest,
    result_type=GetAnalyticalModelViewDependenciesResult,
    handler=get_analytical_model_view_dependencies,
    description="Resolve all view dependencies for an analytical model.",
    default_timeout_seconds=DEFAULT_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS,
    read_only=True,
    destructive=False,
    idempotent=True,
    expose_to_mcp=False,
)

ANALYTICAL_MODELS_GET_VIEW_DEPENDENCIES_BATCH_COMMAND = CommandDefinition(
    name=GET_VIEW_DEPENDENCIES_BATCH_COMMAND_NAME,
    request_type=GetAnalyticalModelViewDependenciesBatchRequest,
    result_type=GetAnalyticalModelViewDependenciesBatchResult,
    handler=get_analytical_model_view_dependencies_batch,
    description=(
        "Resolve all view dependencies of multiple analytical models with "
        "bounded concurrency."
    ),
    default_timeout_seconds=DEFAULT_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_ANALYTICAL_MODEL_READ_TIMEOUT_SECONDS,
    read_only=True,
    destructive=False,
    idempotent=True,
    expose_to_mcp=False,
)

ANALYTICAL_MODELS_MEASURE_VIEW_PERSISTENCE_COMMAND = CommandDefinition(
    name=MEASURE_VIEW_PERSISTENCE_COMMAND_NAME,
    request_type=MeasureAnalyticalModelViewPersistenceRequest,
    result_type=MeasureAnalyticalModelViewPersistenceResult,
    handler=measure_analytical_model_view_persistence,
    description=(
        "Measure the persistence runtime of all view dependencies of an "
        "analytical model."
    ),
    default_timeout_seconds=(
        DEFAULT_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS
    ),
    maximum_timeout_seconds=(
        MAXIMUM_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS
    ),
    read_only=False,
    destructive=True,
    idempotent=False,
    expose_to_mcp=False,
)

ANALYTICAL_MODELS_MEASURE_VIEW_PERSISTENCE_BATCH_COMMAND = CommandDefinition(
    name=MEASURE_VIEW_PERSISTENCE_BATCH_COMMAND_NAME,
    request_type=MeasureAnalyticalModelViewPersistenceBatchRequest,
    result_type=MeasureAnalyticalModelViewPersistenceBatchResult,
    handler=measure_analytical_model_view_persistence_batch,
    description=(
        "Measure the persistence runtimes of all view dependencies of multiple"
        " analytical models with bounded concurrency."
    ),
    default_timeout_seconds=(
        DEFAULT_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS
    ),
    maximum_timeout_seconds=(
        MAXIMUM_ANALYTICAL_MODEL_PERSISTENCE_TIMEOUT_SECONDS
    ),
    read_only=False,
    destructive=True,
    idempotent=False,
    expose_to_mcp=False,
)

# Gather all commands (to import to registry)
ANALYTICAL_MODELS_COMMAND_DEFINITIONS: tuple[
    CommandDefinition[Any, Any], ...
] = (
    ANALYTICAL_MODELS_GET_VIEW_DEPENDENCIES_COMMAND,
    ANALYTICAL_MODELS_GET_VIEW_DEPENDENCIES_BATCH_COMMAND,
    ANALYTICAL_MODELS_MEASURE_VIEW_PERSISTENCE_COMMAND,
    ANALYTICAL_MODELS_MEASURE_VIEW_PERSISTENCE_BATCH_COMMAND,
)
