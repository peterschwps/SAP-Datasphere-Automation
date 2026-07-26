import asyncio
import math
from contextlib import suppress
from dataclasses import replace
from typing import Any

from datasphere_api import (
    ViewPersistenceCancelled,
    ViewPersistenceTimeout,
)
from datasphere_api.models import AnalyticalModelsDetailsDict

from datasphere_core.context import CommandContext
from datasphere_core.definitions import CommandDefinition
from datasphere_core.execution import (
    BatchExecution,
    batch_result_phase,
    execute_batch,
    execute_command,
    execute_with_concurrency_limit,
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
from datasphere_core.models.common import (
    BatchItemFinalStatus,
    CommandProgressPhase,
)

GET_VIEW_DEPENDENCIES_COMMAND_NAME = (
    "analytical_models.get_view_dependencies"
)
GET_VIEW_DEPENDENCIES_BATCH_COMMAND_NAME = (
    "analytical_models.get_view_dependencies_batch"
)
MEASURE_VIEW_PERSISTENCE_COMMAND_NAME = (
    "analytical_models.measure_view_persistence"
)
MEASURE_VIEW_PERSISTENCE_BATCH_COMMAND_NAME = (
    "analytical_models.measure_view_persistence_batch"
)

type ResolvedAnalyticalModel = tuple[
    AnalyticalModelReference,
    AnalyticalModelsDetailsDict | None,
]
type DependencyResolutionInput = tuple[
    ResolvedAnalyticalModel,
    dict[str, str],
]
type PhysicalViewKey = tuple[str, str]


def _as_string(value: object) -> str | None:
    """
    Converts a value to a string if it is an integer or string. Otherwise
    returns None.

    Args:
        value (object): Value to convert.

    Returns:
        str | None: String representation for integer or string values, or
                    None for unsupported values.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    return str(value)


def _get_runtime_seconds(log_details: dict[str, Any]) -> int | None:
    """
    Converts a millisecond runtime to rounded seconds.

    Args:
        log_details (dict[str, Any]): Log details containing 'runTime'.

    Returns:
        int | None: Rounded runtime in seconds, or None if the key is missing
                    or its value invalid.
    """
    runtime = log_details.get("runTime")
    if (
        isinstance(runtime, bool)
        or not isinstance(runtime, (int, float))
        or not math.isfinite(runtime)
        or runtime < 0
    ):
        return None
    return round(runtime / 1000)


def _map_dependency_result_to_command_progress_phase(
    result: GetAnalyticalModelViewDependenciesResult,
) -> CommandProgressPhase:
    """
    Maps a dependency result status to its lifecycle progress phase.

    Args:
        result (GetAnalyticalModelViewDependenciesResult): Result to classify.

    Returns:
        CommandProgressPhase: Corresponding command progress phase.
    """
    return (
        CommandProgressPhase.COMPLETED
        if result.status == "completed"
        else CommandProgressPhase.FAILED
    )


def _map_dependency_result_to_batch_item_final_status(
    result: GetAnalyticalModelViewDependenciesResult,
) -> BatchItemFinalStatus:
    """
    Maps a dependency result status to its batch item status.

    Args:
        result (GetAnalyticalModelViewDependenciesResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Corresponding batch item status.
    """
    if result.status == "completed":
        return BatchItemFinalStatus.SUCCEEDED
    if result.status == "analytical_model_not_found":
        return BatchItemFinalStatus.SKIPPED
    return BatchItemFinalStatus.FAILED


def _map_persistence_measurement_result_to_command_progress_phase(
    result: MeasureAnalyticalModelViewPersistenceResult,
) -> CommandProgressPhase:
    """
    Maps a persistence measurement result to its lifecycle progress phase.

    Args:
        result (MeasureAnalyticalModelViewPersistenceResult): Result to
                                                              classify.

    Returns:
        CommandProgressPhase: Corresponding command progress phase.
    """
    if result.status == "completed":
        return CommandProgressPhase.COMPLETED
    if result.status == "timed_out":
        return CommandProgressPhase.TIMED_OUT
    return CommandProgressPhase.FAILED


def _select_analytical_models(
    all_models: list[AnalyticalModelsDetailsDict],
    analytical_models: tuple[AnalyticalModelReference, ...] | None,
    space: str | None,
) -> tuple[ResolvedAnalyticalModel, ...]:
    """
    Maps analytical models to their API response which contains metadata.
    Offers different options:
        - create links for all analytical models
        - create links for all analytical models in a given space
        - create links for a specific set of analytical models

    Args:
        all_models (list[AnalyticalModelsDetailsDict]): List of all model
                                                        details as retrieved
                                                        from the API.
        analytical_models (tuple[AnalyticalModelReference, ...] | None):
            Explicit references to link the specific models to their metadata
            from the API response. None to select all discovered models or only
            those from a specific space (if provided).
        space (str | None): Optional space filter for discovered models.

    Returns:
        tuple[ResolvedAnalyticalModel, ...]: Selected references and matching
                                             model details, preserving explicit
                                             input order.
    """
    # Create links for all models or all models in a given space
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

    # Create links for a specific set of models
    by_name_and_space: dict[tuple[str, str], AnalyticalModelsDetailsDict] = {}
    for model in all_models:
        by_name_and_space[(model["name"], model["space_name"])] = model
    return tuple(
        (ref, by_name_and_space.get((ref.name, ref.space)))
        for ref in analytical_models
    )


async def _resolve_model_dependencies(
    context: CommandContext,
    resolved_model: ResolvedAnalyticalModel,
    spaces_by_view_id: dict[str, str],
) -> GetAnalyticalModelViewDependenciesResult:
    """
    Resolves all view dependencies of one analytical model.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        resolved_model (ResolvedAnalyticalModel): Linked model reference to its
                                                  metadata.
        spaces_by_view_id (dict[str, str]): Mapping of view IDs (as keys) to
                                            their spaces (as values).

    Returns:
        GetAnalyticalModelViewDependenciesResult: Resolved view dependencies.
    """
    reference, model_metadata = resolved_model
    if model_metadata is None:
        return GetAnalyticalModelViewDependenciesResult(
            analytical_model_name=reference.name,
            space=reference.space,
            status=(
                AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND
            ),
        )

    # Fetch all views for analytical model
    analytical_model_id = model_metadata["id"]
    dependencies_by_model = await (
        context.client.analytical_models.get_views_for_analytical_model(
            analytical_model_id=analytical_model_id
        )
    )
    dependencies_of_model = dependencies_by_model[analytical_model_id]

    # Resolve dependencies for given model
    resolved_dependencies = []
    for view_id, view_name in dependencies_of_model.items():
        resolved_dependencies.append(
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
        )

    return GetAnalyticalModelViewDependenciesResult(
        analytical_model_name=reference.name,
        space=reference.space,
        analytical_model_id=analytical_model_id,
        status=(
            AnalyticalModelDependenciesStatus.DEPENDENCY_NOT_FOUND
            if any(
                item.status is AnalyticalModelDependencyStatus.NOT_FOUND
                for item in resolved_dependencies
            )
            else AnalyticalModelDependenciesStatus.COMPLETED
        ),
        dependencies=tuple(resolved_dependencies),
    )


async def _prepare_dependency_resolution(
    context: CommandContext,
    analytical_models: tuple[AnalyticalModelReference, ...] | None,
    space: str | None,
) -> tuple[tuple[ResolvedAnalyticalModel, ...], dict[str, str]]:
    """
    Loads all analytical models and views. Then links the selected models to
    their metadata and creates a mapping of all view IDs to their spaces.
    Offers different options for the model selection:
        - select all analytical models
        - select all analytical models in a given space
        - select a specific set of analytical models

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        analytical_models (tuple[AnalyticalModelReference, ...] | None):
            Explicit references to analytical models to resolve their
            dependencies. None to select all analytical models or only
            those from a specific space (if provided).
        space (str | None): Optional space filter to only resolve dependencies
                            for analytical models of a given space.

    Returns:
        tuple[tuple[ResolvedAnalyticalModel, ...], dict[str, str]]:
            Selected models with their metadata and a mapping of all view IDs
            to their spaces.
    """
    # Fetch all analytical models and views concurrently
    f1 = context.client.analytical_models.get_all_analytical_models()
    f2 = context.client.views.get_all_views()
    discovery_tasks = (asyncio.create_task(f1), asyncio.create_task(f2))
    try:
        all_models, all_views = await asyncio.gather(*discovery_tasks)
    except BaseException:
        for task in discovery_tasks:
            task.cancel()
        await asyncio.gather(*discovery_tasks, return_exceptions=True)
        raise

    # Link selected models or all models (if analytical_models is None)
    # to their metadata
    selected = _select_analytical_models(all_models, analytical_models, space)

    # Map view ID to spaces
    spaces_by_view_id = {
        view["id"]: view["space_name"]
        for view in all_views
    }
    return selected, spaces_by_view_id


async def _resolve_dependency_input(
    context: CommandContext,
    item: DependencyResolutionInput,
) -> GetAnalyticalModelViewDependenciesResult:
    """
    Resolves dependencies for one prepared analytical model.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        item (DependencyResolutionInput): Information about the resolved model
                                          and the mapping of view IDs to their
                                          spaces.

    Returns:
        GetAnalyticalModelViewDependenciesResult: Dependency result.
    """
    resolved_model, spaces_by_view_id = item
    return await _resolve_model_dependencies(
        context=context,
        resolved_model=resolved_model,
        spaces_by_view_id=spaces_by_view_id,
    )


async def _resolve_selected_model_dependencies(
    context: CommandContext,
    selected: tuple[ResolvedAnalyticalModel, ...],
    spaces_by_view_id: dict[str, str],
    max_concurrency: int,
) -> tuple[GetAnalyticalModelViewDependenciesResult, ...]:
    """
    Resolves view dependencies of selected analytical models with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        selected (tuple[ResolvedAnalyticalModel, ...]): Analytical models to
                                                        resolve.
        spaces_by_view_id (dict[str, str]): Mapping of view IDs to their
                                            spaces.
        max_concurrency (int): Maximum amount of concurrent tasks.

    Returns:
        tuple[GetAnalyticalModelViewDependenciesResult, ...]: Results in model
                                                              selection order.
    """
    inputs = tuple((context, (model, spaces_by_view_id)) for model in selected)

    async def resolve_one(
        request: tuple[CommandContext, DependencyResolutionInput],
    ) -> GetAnalyticalModelViewDependenciesResult:
        """
        Callable that resolves the dependencies of one analytical model.

        Args:
            request (tuple[CommandContext, DependencyResolutionInput]):
                Input to resolve the dependencies.

        Returns:
            GetAnalyticalModelViewDependenciesResult: Result of resolving the
                                                      dependencies.
        """
        context, item = request
        return await _resolve_dependency_input(context, item)

    return await execute_with_concurrency_limit(
        items=inputs,
        operation=resolve_one,
        max_concurrency=max_concurrency,
    )


async def _resolve_requested_model_dependencies(
    context: CommandContext,
    analytical_models: tuple[AnalyticalModelReference, ...] | None,
    space: str | None,
    max_concurrency: int,
) -> tuple[GetAnalyticalModelViewDependenciesResult, ...]:
    """
    Maps analytical models to their metadata and creates a mapping of view IDs
    to their spaces. Then resolves all view dependencies of the analytical
    models.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        analytical_models (tuple[AnalyticalModelReference, ...] | None):
            Explicit references to analytical models to resolve their
            dependencies. None to select all analytical models or only
            those from a specific space (if provided).
        space (str | None): Optional space filter to only resolve dependencies
                            for analytical models of a given space.
        max_concurrency (int): Maximum amount of concurrent tasks.

    Returns:
        tuple[GetAnalyticalModelViewDependenciesResult, ...]: Results in model
                                                              selection order.
    """
    # Map models to their metadata and create view-id-to-space mapping
    selected, spaces_by_view_id = await _prepare_dependency_resolution(
        context,
        analytical_models,
        space,
    )
    return await _resolve_selected_model_dependencies(
        context,
        selected,
        spaces_by_view_id,
        max_concurrency,
    )


def _deduplicate_dependencies(
    results: tuple[GetAnalyticalModelViewDependenciesResult, ...],
) -> tuple[GetAnalyticalModelViewDependenciesResult, ...]:
    """
    Removes repeated resolved views while preserving result order. This can be
    used to ensure that views are not being persisted more than once even if
    different analytical models contain the same views.

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

            # Views that couldn't be mapped
            if dependency.status is AnalyticalModelDependencyStatus.NOT_FOUND:
                dependencies.append(dependency)
                continue

            # Ignore previously seen views or add new view to seen
            key = (dependency.space, dependency.view_id)
            if key in seen:
                continue
            else:
                seen.add(key)

            dependencies.append(dependency)

        # Add new result with removed duplicates to deduplicated
        ordered_dependencies = tuple(dependencies)
        deduplicated.append(
            replace(
                result,
                dependencies=ordered_dependencies,
            )
        )

    return tuple(deduplicated)


async def _get_analytical_model_view_dependencies(
    context: CommandContext,
    request: GetAnalyticalModelViewDependenciesRequest,
) -> GetAnalyticalModelViewDependenciesResult:
    """
    Resolves the dependencies for one analytical model.

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
    results = await _resolve_requested_model_dependencies(
        context=context,
        analytical_models=(reference,),
        space=None,
        max_concurrency=DEFAULT_ANALYTICAL_MODEL_MAX_CONCURRENCY,
    )
    return results[0]


async def get_analytical_model_view_dependencies(
    context: CommandContext,
    request: GetAnalyticalModelViewDependenciesRequest,
) -> GetAnalyticalModelViewDependenciesResult:
    """
    Resolves the dependencies for one analytical model.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (GetAnalyticalModelViewDependenciesRequest): Input to resolve
                                                             the dependencies.

    Returns:
        GetAnalyticalModelViewDependenciesResult: Result of resolving the
                                                  dependencies.
    """
    return await execute_command(
        context=context,
        command=GET_VIEW_DEPENDENCIES_COMMAND_NAME,
        request=request,
        operation=_get_analytical_model_view_dependencies,
        result_phase=_map_dependency_result_to_command_progress_phase,
    )


async def _get_analytical_model_view_dependencies_batch(
    execution: BatchExecution,
    request: GetAnalyticalModelViewDependenciesBatchRequest,
) -> GetAnalyticalModelViewDependenciesBatchResult:
    """
    Loads and optionally deduplicates the view dependencies of selected
    analytical models with concurrency.

    Args:
        execution (BatchExecution): Runtime state and shared operations for the
                                    batch execution.
        request (GetAnalyticalModelViewDependenciesBatchRequest): Input to
                                                                  resolve the
                                                                  dependencies.

    Returns:
        GetAnalyticalModelViewDependenciesBatchResult: Ordered results of
                                                       resolving the
                                                       dependencies.
    """
    # Load all analytical models and views, then map all models (in a given
    # space) to their metadata and create a mapping of view IDs to their spaces
    selected, spaces_by_view_id = await _prepare_dependency_resolution(
        execution.context,
        request.analytical_models,
        request.space,
    )
    items = tuple((model, spaces_by_view_id) for model in selected)

    # Resolve dependencies with concurrency and deliver each result in the
    # batch to the callback (if provided)
    # This only works if views do not need to be deduplicated, otherwise all
    # results need to be recorded first before they can be deduplicated.
    # Therefore individual results inside the batch can't be reported.
    if not request.deduplicate_views:
        results = await execution.execute_items(
            items=items,
            operation=_resolve_dependency_input,
            max_concurrency=request.max_concurrency,
            classify=_map_dependency_result_to_batch_item_final_status,
        )
        return GetAnalyticalModelViewDependenciesBatchResult(
            results=results,
            summary=execution.to_summary(),
        )

    # Resolve dependencies with concurrency but without reporting each result
    # to the callback
    results = await _resolve_selected_model_dependencies(
        context=execution.context,
        selected=selected,
        spaces_by_view_id=spaces_by_view_id,
        max_concurrency=request.max_concurrency,
    )

    # Deduplicate dependencies, then set total items
    results = _deduplicate_dependencies(results)
    execution.set_total_items(len(results))

    # Iterate over all results, record and report them to callback
    for index, result in enumerate(results):
        await execution.complete_item(
            item_index=index,
            final_status=(
                _map_dependency_result_to_batch_item_final_status(
                    result=result,
                )
            ),
            result=result,
        )
    return GetAnalyticalModelViewDependenciesBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def get_analytical_model_view_dependencies_batch(
    context: CommandContext,
    request: GetAnalyticalModelViewDependenciesBatchRequest,
) -> GetAnalyticalModelViewDependenciesBatchResult:
    """
    Loads and optionally deduplicates the view dependencies of selected
    analytical models with concurrency.

    Args:
        execution (BatchExecution): Runtime state and shared operations for the
                                    batch execution.
        request (GetAnalyticalModelViewDependenciesBatchRequest): Input to
                                                                  resolve the
                                                                  dependencies.

    Returns:
        GetAnalyticalModelViewDependenciesBatchResult: Ordered results of
                                                       resolving the
                                                       dependencies.
    """
    return await execute_batch(
        context=context,
        command=GET_VIEW_DEPENDENCIES_BATCH_COMMAND_NAME,
        request=request,
        operation=_get_analytical_model_view_dependencies_batch,
        total_items=(
            len(request.analytical_models)
            if request.analytical_models is not None
            else None
        ),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


def _create_measure_view_persistence_result(
    dependency: AnalyticalModelViewDependency,
    *,
    status: AnalyticalModelPersistenceItemStatus,
    previously_persisted: bool,
    persistence_details: dict[str, Any] | None = None,
    cleanup_details: dict[str, Any] | None = None,
    persistence_log_id: str | None = None,
    cleanup_log_id: str | None = None,
    persistence_removed: bool = False,
    manual_intervention: bool = False,
) -> MeasureAnalyticalModelViewPersistenceItemResult:
    """
    Builds a persistence item result.

    Args:
        dependency (AnalyticalModelViewDependency): View dependency measured.
        status (AnalyticalModelPersistenceItemStatus): Item outcome.
        previously_persisted (bool): State observed before measurement.
        persistence_details (dict[str, Any] | None, optional):
            Persistence details as returned by Datasphere. Defaults to None.
        cleanup_details (dict[str, Any] | None, optional):
            Details of the cleanup action as returned by Datasphere. Defaults
            to None.
        persistence_log_id (str | None, optional):
            Log ID of the persistence run. Defaults to None.
        cleanup_log_id (str | None, optional):
            Log ID of the cleanup action. Defaults to None.
        persistence_removed (bool, optional):
            Whether the temporary persistence was removed. Defaults to False.
        manual_intervention (bool, optional):
            Whether manual action may be needed (e.g. unable to check if
            persistence was removed). Defaults to False.

    Returns:
        MeasureAnalyticalModelViewPersistenceItemResult: Result of measuring
                                                         the persistence
                                                         runtime of one view.
    """
    persistence_details = persistence_details or {}
    cleanup_details = cleanup_details or {}
    runtime_seconds = _get_runtime_seconds(persistence_details)
    persistence_sap_status = _as_string(persistence_details.get("status"))
    cleanup_sap_status = _as_string(cleanup_details.get("status"))
    if persistence_log_id is None:
        persistence_log_id = _as_string(persistence_details.get("logId"))
    if cleanup_log_id is None:
        cleanup_log_id = _as_string(cleanup_details.get("logId"))
    return MeasureAnalyticalModelViewPersistenceItemResult(
        view_id=dependency.view_id,
        view_name=dependency.view_name,
        space=dependency.space,
        status=status,
        previously_persisted=previously_persisted,
        runtime_seconds=runtime_seconds,
        persistence_sap_status=persistence_sap_status,
        persistence_log_id=persistence_log_id,
        cleanup_sap_status=cleanup_sap_status,
        cleanup_log_id=cleanup_log_id,
        persistence_removed=persistence_removed,
        manual_intervention=manual_intervention,
    )


async def _run_cleanup(
    context: CommandContext,
    dependency: AnalyticalModelViewDependency,
    timeout_seconds: float,
) -> tuple[bool, dict[str, Any], str | None]:
    """
    Removes temporary persistence from one resolved view dependency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        dependency (AnalyticalModelViewDependency): View to remove persistency
                                                    for.
        timeout_seconds (float): Maximum cleanup duration in seconds.

    Returns:
        tuple[bool, dict[str, Any], str | None]: Whether cleanup succeeded,
                                                 SAP cleanup details, and an
                                                 optional log identifier.

    Raises:
        RuntimeError: If the dependency has no resolved space.
    """
    if dependency.space is None:
        raise RuntimeError("Cannot clean up an unresolved dependency.")
    space = dependency.space

    async def cleanup_operation() -> tuple[bool, dict[str, Any], str | None]:
        """
        Invokes the API cleanup operation for the view dependency.

        Returns:
            tuple[bool, dict[str, Any], str | None]: Cleanup outcome, details,
                                                     and an optional
                                                     cancellation log
                                                     identifier (only for
                                                     errors, otherwise the
                                                     log Id is part of the
                                                     details).
        """
        try:
            cleaned_up, details = await context.client.views.unpersist_view(
                view=dependency.view_name,
                space=space,
                timeout_seconds=timeout_seconds,
            )
        except ViewPersistenceCancelled as error:
            return False, {}, _as_string(error.log_id)

        return cleaned_up, details, None

    # Run cleanup task with shield (will continue even if outer method exection
    # is cancelled)
    cleanup_task = asyncio.create_task(cleanup_operation())
    try:
        return await asyncio.shield(cleanup_task)
    except asyncio.CancelledError:
        with suppress(BaseException):
            await cleanup_task
        raise


async def _measure_persistence_runtime_of_view(
    context: CommandContext,
    dependency: AnalyticalModelViewDependency,
    timeout_seconds: float,
) -> MeasureAnalyticalModelViewPersistenceItemResult:
    """
    Measures the persistence runtime of one view and removes it afterwards.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        dependency (AnalyticalModelViewDependency): View dependency to measure.
        timeout_seconds (float): Maximum duration for persistence and cleanup.

    Returns:
        MeasureAnalyticalModelViewPersistenceItemResult: Result of measuring
                                                         the view's persistence
                                                         runtime.

    Raises:
        RuntimeError: If the dependency has no resolved space.
        ViewPersistenceCancelled: If the API persistence operation is
                                  cancelled.
    """
    if dependency.space is None:
        raise RuntimeError("Cannot measure an unresolved dependency.")

    # Check if view is already persisted
    previously_persisted = await context.client.views.is_persisted(
        view=dependency.view_name,
        space=dependency.space,
    )

    # Start persistence run
    try:
        persisted, persistence_details = (
            await context.client.views.persist_view(
                dependency.view_name,
                dependency.space,
                timeout_seconds=timeout_seconds,
            )
        )
    except ViewPersistenceTimeout as error:
        return _create_measure_view_persistence_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.PERSIST_TIMED_OUT,
            previously_persisted=previously_persisted,
            persistence_log_id=_as_string(error.log_id),
            manual_intervention=True,
        )
    except ViewPersistenceCancelled:
        raise

    # Return if persistence run failed
    if not persisted:
        return _create_measure_view_persistence_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.PERSIST_FAILED,
            previously_persisted=previously_persisted,
            persistence_details=persistence_details,
            manual_intervention=not previously_persisted,
        )

    # Return without cleanup if view was persisted before
    if previously_persisted:
        return _create_measure_view_persistence_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.ALREADY_PERSISTED,
            previously_persisted=True,
            persistence_details=persistence_details,
        )

    # Remove persistence if view wasn't persisted before
    try:
        cleaned_up, cleanup_details, cleanup_log_id = (
            await _run_cleanup(context, dependency, timeout_seconds)
        )
    except ViewPersistenceTimeout as error:
        return _create_measure_view_persistence_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.CLEANUP_TIMED_OUT,
            previously_persisted=False,
            persistence_details=persistence_details,
            cleanup_log_id=_as_string(error.log_id),
            manual_intervention=True,
        )
    except Exception as error:
        return _create_measure_view_persistence_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.CLEANUP_FAILED,
            previously_persisted=False,
            persistence_details=persistence_details,
            cleanup_log_id=_as_string(getattr(error, "log_id", None)),
            persistence_removed=False,
            manual_intervention=True,
        )

    # Check if clean up was successful
    if not cleaned_up:
        return _create_measure_view_persistence_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.CLEANUP_FAILED,
            previously_persisted=False,
            persistence_details=persistence_details,
            cleanup_log_id=cleanup_log_id,
            cleanup_details=cleanup_details,
            manual_intervention=True,
        )
    return _create_measure_view_persistence_result(
        dependency,
        status=AnalyticalModelPersistenceItemStatus.COMPLETED,
        previously_persisted=False,
        persistence_details=persistence_details,
        cleanup_details=cleanup_details,
        persistence_removed=True,
    )


async def _measure_persistence_runtimes_of_dependencies(
    context: CommandContext,
    dependency_results: tuple[GetAnalyticalModelViewDependenciesResult, ...],
    timeout_seconds: float,
    max_concurrency: int,
) -> tuple[MeasureAnalyticalModelViewPersistenceResult, ...]:
    """
    Measures unique view dependencies and projects results per model.
    Example: If we have two analytical models: Model A -> View X, View Y
                                               Model B -> View Y, View Z.
             Then the persistence runtime of View Y will only be measured once
             but its result will be added to the results of Model A as well as
             Model B.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        dependency_results (
            tuple[GetAnalyticalModelViewDependenciesResult, ...]
        ): Analytical models with the dependencies to measure.
        timeout_seconds (float): Maximum duration for persisting each view.
        max_concurrency (int): Maximum amount of concurrent tasks.

    Returns:
        tuple[MeasureAnalyticalModelViewPersistenceResult, ...]:
            Ordered results of the measured view persistence runtimes.
    """
    # Filter out all unique views
    unique_dependencies: list[AnalyticalModelViewDependency] = []
    seen: set[PhysicalViewKey] = set()
    for result in dependency_results:
        for dependency in result.dependencies:
            if dependency.space is None:
                continue
            key = (dependency.space, dependency.view_name)
            if key in seen:
                continue
            seen.add(key)
            unique_dependencies.append(dependency)

    async def measure_one(
        dependency: AnalyticalModelViewDependency,
    ) -> MeasureAnalyticalModelViewPersistenceItemResult:
        """
        Callable that measures the persistence runtime of one view and removes
        it afterwards.

        Args:
            dependency (AnalyticalModelViewDependency): View to measure.

        Returns:
            MeasureAnalyticalModelViewPersistenceItemResult: Result of the
                                                             measurement.
        """
        return await _measure_persistence_runtime_of_view(
            context=context,
            dependency=dependency,
            timeout_seconds=timeout_seconds,
        )

    # Start measurements with concurrency
    measured = await execute_with_concurrency_limit(
        items=tuple(unique_dependencies),
        operation=measure_one,
        max_concurrency=max_concurrency,
    )

    # Map measurements to their views
    measurement_by_view = {
        (item.space, item.view_name): item
        for item in measured
        if item.space is not None
    }

    # Iterate over all analytical models and evaluate the results
    measure_results: list[MeasureAnalyticalModelViewPersistenceResult] = []
    for result in dependency_results:
        if result.status is (
            AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND
        ):
            measure_results.append(
                MeasureAnalyticalModelViewPersistenceResult(
                    analytical_model_name=result.analytical_model_name,
                    space=result.space,
                    status=AnalyticalModelPersistenceStatus.ANALYTICAL_MODEL_NOT_FOUND,
                )
            )
            continue

        # Iterate over all dependencies of the analytical model
        projected: list[MeasureAnalyticalModelViewPersistenceItemResult] = []
        for dependency in result.dependencies:
            if dependency.space is None:
                projected.append(
                    MeasureAnalyticalModelViewPersistenceItemResult(
                        view_id=dependency.view_id,
                        view_name=dependency.view_name,
                        space=None,
                        status=AnalyticalModelPersistenceItemStatus.DEPENDENCY_NOT_FOUND,
                        manual_intervention=True,
                    )
                )
                continue

            # Get measurement and add it to the list
            measured_item = measurement_by_view[
                (dependency.space, dependency.view_name)
            ]
            projected.append(measured_item)

        # Derive status from all view measurements of the analytical model
        dependencies = tuple(projected)
        if any(
            item.status
            in {
                AnalyticalModelPersistenceItemStatus.PERSIST_TIMED_OUT,
                AnalyticalModelPersistenceItemStatus.CLEANUP_TIMED_OUT,
            }
            for item in dependencies
        ):
            status = AnalyticalModelPersistenceStatus.TIMED_OUT
        if any(
            item.status
            not in {
                AnalyticalModelPersistenceItemStatus.COMPLETED,
                AnalyticalModelPersistenceItemStatus.ALREADY_PERSISTED,
            }
            for item in dependencies
        ):
            status = AnalyticalModelPersistenceStatus.FAILED
        status = AnalyticalModelPersistenceStatus.COMPLETED

        # Add analytical model with all its view measurements to the results
        measure_results.append(
            MeasureAnalyticalModelViewPersistenceResult(
                analytical_model_name=result.analytical_model_name,
                space=result.space,
                analytical_model_id=result.analytical_model_id,
                status=status,
                dependencies=dependencies,
            )
        )
    return tuple(measure_results)


async def _measure_analytical_model_view_persistence(
    context: CommandContext,
    request: MeasureAnalyticalModelViewPersistenceRequest,
) -> MeasureAnalyticalModelViewPersistenceResult:
    """
    Resolves the view dependencies of one analytical model and measures their
    persistence runtimes.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (MeasureAnalyticalModelViewPersistenceRequest): Input for the
                                                                measurement.

    Returns:
        MeasureAnalyticalModelViewPersistenceResult: Result of the measurement.

    Raises:
        ViewPersistenceCancelled: If the persistence operation is cancelled.
    """
    reference = AnalyticalModelReference(
        name=request.analytical_model_name,
        space=request.space,
    )

    # Resolve dependencies for the analytical model
    dependency_results = await _resolve_requested_model_dependencies(
        context=context,
        analytical_models=(reference,),
        space=None,
        max_concurrency=request.max_concurrency,
    )

    # Measure the persistence runtimes of all dependencies
    results = await _measure_persistence_runtimes_of_dependencies(
        context=context,
        dependency_results=dependency_results,
        timeout_seconds=request.timeout_seconds,
        max_concurrency=request.max_concurrency,
    )
    return results[0]


async def measure_analytical_model_view_persistence(
    context: CommandContext,
    request: MeasureAnalyticalModelViewPersistenceRequest,
) -> MeasureAnalyticalModelViewPersistenceResult:
    """
    Measures the persistence runtimes of all view dependencies of an analytical
    model and safely restores the previous persistence status.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (MeasureAnalyticalModelViewPersistenceRequest): Input for the
                                                                measurement.

    Returns:
        MeasureAnalyticalModelViewPersistenceResult: Result of the measurement.

    Raises:
        ViewPersistenceCancelled: If the persistence operation is cancelled.
    """
    return await execute_command(
        context=context,
        command=MEASURE_VIEW_PERSISTENCE_COMMAND_NAME,
        request=request,
        operation=_measure_analytical_model_view_persistence,
        result_phase=_map_persistence_measurement_result_to_command_progress_phase,
    )


async def _measure_analytical_model_view_persistence_batch(
    execution: BatchExecution,
    request: MeasureAnalyticalModelViewPersistenceBatchRequest,
) -> MeasureAnalyticalModelViewPersistenceBatchResult:
    """
    Resolves the view dependencies of selected analytical models and measures
    their persistence runtimes with concurrency.

    Args:
        execution (BatchExecution): Runtime state and shared operations for the
                                    batch execution.
        request (MeasureAnalyticalModelViewPersistenceBatchRequest):
            Input for the measurements.

    Returns:
        MeasureAnalyticalModelViewPersistenceBatchResult: Ordered results of
                                                          the measurements.

    Raises:
        ViewPersistenceCancelled: If a persistence operation is cancelled.
    """
    # Resolve dependencies for the analytical models
    dependency_results = await _resolve_requested_model_dependencies(
        context=execution.context,
        analytical_models=request.analytical_models,
        space=request.space,
        max_concurrency=request.max_concurrency,
    )

    # Measure the persistence runtimes of all dependencies
    results = await _measure_persistence_runtimes_of_dependencies(
        context=execution.context,
        dependency_results=dependency_results,
        timeout_seconds=request.timeout_seconds,
        max_concurrency=request.max_concurrency,
    )
    execution.set_total_items(len(results))

    # Evaluate results
    for index, result in enumerate(results):

        # Check final status of batch item
        if result.status == "completed":
            final_status = BatchItemFinalStatus.SUCCEEDED
        elif result.status == "analytical_model_not_found":
            final_status = BatchItemFinalStatus.SKIPPED
        elif result.status == "timed_out":
            final_status = BatchItemFinalStatus.TIMED_OUT
        else:
            final_status = BatchItemFinalStatus.FAILED

        # Record result and report to callback (if provided)
        await execution.complete_item(
            item_index=index,
            final_status=final_status,
            result=result,
        )

    return MeasureAnalyticalModelViewPersistenceBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def measure_analytical_model_view_persistence_batch(
    context: CommandContext,
    request: MeasureAnalyticalModelViewPersistenceBatchRequest,
) -> MeasureAnalyticalModelViewPersistenceBatchResult:
    """
    Measures the persistence runtimes of all view dependencies of selected
    analytical models with concurrency and safely restores the previous
    persistence status of all views.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (MeasureAnalyticalModelViewPersistenceBatchRequest):
            Input for the measurements.

    Returns:
        MeasureAnalyticalModelViewPersistenceBatchResult: Ordered results of
                                                          the measurements.

    Raises:
        ViewPersistenceCancelled: If a persistence operation is cancelled.
    """
    return await execute_batch(
        context=context,
        command=MEASURE_VIEW_PERSISTENCE_BATCH_COMMAND_NAME,
        request=request,
        operation=_measure_analytical_model_view_persistence_batch,
        total_items=(
            len(request.analytical_models)
            if request.analytical_models is not None
            else None
        ),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


# Define all commands
ANALYTICAL_MODELS_GET_VIEW_DEPENDENCIES_COMMAND = CommandDefinition(
    name=GET_VIEW_DEPENDENCIES_COMMAND_NAME,
    request_type=GetAnalyticalModelViewDependenciesRequest,
    result_type=GetAnalyticalModelViewDependenciesResult,
    handler=get_analytical_model_view_dependencies,
    description="Resolve view dependencies for an analytical model.",
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
        "Resolve analytical-model view dependencies with bounded concurrency."
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
    description=("Measure physical-view persistence for an analytical model."),
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
        "Measure analytical-model view persistence with bounded concurrency."
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
