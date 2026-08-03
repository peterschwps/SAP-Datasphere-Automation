import asyncio
from contextlib import suppress
from dataclasses import replace
from typing import Any

from datasphere_core.commands.repository import (
    search_analytical_models,
    search_views,
)
from datasphere_core.commands.shared.conversion import (
    runtime_to_seconds,
    to_text,
)
from datasphere_core.commands.shared.persistence import (
    is_persisted,
    run_persistence,
    run_persistence_removal,
)
from datasphere_core.errors import CommandCancelledError, CommandTimeoutError
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
    AnalyticalModelsDetailsDict,
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
from datasphere_core.runtime.context import CommandContext
from datasphere_core.runtime.definitions import CommandDefinition
from datasphere_core.runtime.execution import (
    BatchReporter,
    batch_command,
    command,
    execute_with_concurrency_limit,
    run_batch,
)
from datasphere_core.session.config import request_headers

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
type ViewMeasurement = MeasureAnalyticalModelViewPersistenceItemResult


def _collect_views(entity: dict[str, Any]) -> list[tuple[str, str]]:
    """
    Collects every view of one dependency tree, each entity before the
    entities it depends on.

    Args:
        entity (dict[str, Any]): Entity to descend into, with its own
                                 dependencies nested inside it.

    Returns:
        list[tuple[str, str]]: ID and name of every view of the tree.
    """
    views: list[tuple[str, str]] = []
    if entity["properties"].get("#isViewEntity", "false") == "true":
        views.append((entity["id"], entity["name"]))
    for dependency in entity["dependencies"]:
        views.extend(_collect_views(dependency))
    return views


async def _get_view_dependencies(
    context: CommandContext,
    model_id: str,
) -> dict[str, str]:
    """
    Loads every view one analytical model is built on.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        model_id (str): Repository ID of the analytical model.

    Returns:
        dict[str, str]: Name of every view the model depends on, keyed by view
                        ID and ordered bottom-up.
    """
    response = await context.session.get(
        url="/deepsea/repository/dependencies/",
        params={
            "ids": model_id,
            "recursive": True,
            "impact": True,
            "lineage": True,
            "details": (
                "#spaceName,#spaceLabel,qualified_name,@EndUserText.label,"
                "@EnterpriseSearch.enabled,owner,deployment_date,"
                "modification_date,#objectStatus,#businessType,"
                "#technicalType,@Analytics.provider,#isViewEntity,"
                "@DataWarehouse.remote.connection,#isToolingHidden,"
                "releaseStateValue,releaseDate,deprecationDate,"
                "decommissioningDate,@ObjectModel.supportedCapabilities,"
                "@DataWarehouse.consumption.external,#columnsCount,"
                "@Analytics.dbViewType,isMissingColumnLineage"
            ),
            "dependencyTypes": (
                "csn.query.from,sap.dis.source,sap.dis.targetOf,"
                "sap.dis.replicationflow.source,"
                "sap.dis.replicationflow.targetOf,"
                "sap.dwc.transformationflow.source,"
                "sap.dwc.transformationflow.targetOf,sap.dwc.idtEntity,"
                "csn.derivation.lookupEntity,csn.valueHelp.entity"
            ),
        },
        headers=request_headers(),
    )

    # Reverse the tree to put the deepest view first
    # Persisting a view only pays off once the views below it are persisted
    views = _collect_views(response.json()[0])
    views.reverse()
    return dict(views)


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
        asyncio.create_task(search_analytical_models(context)),
        asyncio.create_task(search_views(context)),
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
    views = await _get_view_dependencies(context, model_id)

    # Resolve every view to its space
    # A view without a space could not be found in the repository
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
        for view_id, view_name in views.items()
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
    result: GetAnalyticalModelViewDependenciesResult,
    seen: set[str],
) -> GetAnalyticalModelViewDependenciesResult:
    """
    Removes the views of one analytical model that an earlier model already
    claimed. This ensures that views shared by several analytical models are
    only processed once.

    The 'seen' set is carried across calls and grows with every kept view, so
    results have to be deduplicated in their input order.

    Args:
        result (GetAnalyticalModelViewDependenciesResult): Dependency result to
                                                           deduplicate.
        seen (set[str]): IDs of the views claimed by earlier results.

    Returns:
        GetAnalyticalModelViewDependenciesResult: Result with the duplicate
                                                  dependencies removed.
    """
    dependencies: list[AnalyticalModelViewDependency] = []

    # Iterate over each dependency of the analytical model
    for dependency in result.dependencies:

        # Keep every view that could not be mapped
        if dependency.status is AnalyticalModelDependencyStatus.NOT_FOUND:
            dependencies.append(dependency)
            continue

        # Skip previously seen views and remember new ones
        if dependency.view_id in seen:
            continue

        seen.add(dependency.view_id)
        dependencies.append(dependency)

    return replace(result, dependencies=tuple(dependencies))


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

    # Deduplication keeps the first occurrence of a view, so a model is only
    # final once every earlier model was resolved. The tasks still run
    # concurrently, but only the deduplication and reporting follow input
    # order.
    semaphore = asyncio.Semaphore(request.max_concurrency)

    async def resolve(
        item: DependencyItem,
    ) -> GetAnalyticalModelViewDependenciesResult:
        """
        Resolves the dependencies of one model once the semaphore admits it.

        Args:
            item (DependencyItem): Model linked to its metadata and the mapping
                                   of view IDs to their spaces.

        Returns:
            GetAnalyticalModelViewDependenciesResult: Resolved view
                                                      dependencies.
        """
        async with semaphore:
            return await _resolve_dependencies(context, item)

    # Create tasks to resolve dependencies of every selected analytical model
    # with bounded concurrency
    tasks = [
        asyncio.create_task(resolve(item=(model, spaces_by_view_id)))
        for model in selected
    ]

    # Create reporter to report every model as soon as its last view was
    # resolved
    reporter = BatchReporter(
        context=context,
        command=GET_VIEW_DEPENDENCIES_BATCH_COMMAND_NAME,
        total_items=len(tasks),
    )

    # Start resolving every model's dependencies
    seen: set[str] = set()
    results = []
    try:
        for item_index, task in enumerate(tasks):
            resolved_dependencies_result = await task

            # Deduplicate the result using the previously seen views
            result = _deduplicate_dependencies(
                result=resolved_dependencies_result,
                seen=seen,
            )
            results.append(result)

            # Report results
            await reporter.complete(item_index, result)

    # Cancel all pending tasks on BaseException (includes CancelledError)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise  # to re-raise the exception

    return GetAnalyticalModelViewDependenciesBatchResult(
        results=tuple(results),
        summary=reporter.summary,
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
        persistence_details (dict[str, Any] | None, optional): Persistence
                                                               details as
                                                               returned by
                                                               Datasphere.
                                                               Defaults to
                                                               None.
        cleanup_details (dict[str, Any] | None, optional): Details of the
                                                           cleanup action as
                                                           returned by
                                                           Datasphere.
                                                           Defaults to None.
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
    # Details are empty whenever a step never ran or its outcome could
    # not be read, so every key is optional.
    # An explicit logId beats the details, because the two never appear
    # together.
    persistence_details = persistence_details or {}
    cleanup_details = cleanup_details or {}
    return MeasureAnalyticalModelViewPersistenceItemResult(
        view_id=dependency.view_id,
        view_name=dependency.view_name,
        space=dependency.space,
        status=status,
        previously_persisted=previously_persisted,
        runtime_seconds=runtime_to_seconds(persistence_details),
        persistence_log_status=to_text(persistence_details.get("status")),
        persistence_log_id=(
            persistence_log_id or to_text(persistence_details.get("logId"))
        ),
        cleanup_log_status=to_text(cleanup_details.get("status")),
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
            cleaned_up, details = await run_persistence_removal(
                context,
                view=dependency.view_name,
                space=space,
                timeout_seconds=timeout_seconds,
            )
        except CommandCancelledError as error:
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
        CommandCancelledError: If the persistence run is cancelled after
                               it started remotely.

    Returns:
        MeasureAnalyticalModelViewPersistenceItemResult: Result of measuring
                                                         the view's persistence
                                                         runtime.
    """
    space = dependency.space
    assert space is not None, "Only resolved dependencies can be measured."

    # Check if the view is already persisted
    previously_persisted = await is_persisted(
        context,
        dependency.view_name,
        space,
    )

    # Start the persistence run
    try:
        persisted, persistence_details = await run_persistence(
            context,
            view=dependency.view_name,
            space=space,
            timeout_seconds=timeout_seconds,
        )
    except CommandTimeoutError as error:
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

    # If timeout is exceeded
    except CommandTimeoutError as error:
        return _create_measurement_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.CLEANUP_TIMED_OUT,
            previously_persisted=False,
            persistence_details=persistence_details,
            cleanup_log_id=to_text(error.log_id),
            manual_intervention=True,
        )

    # If any other errors occur
    # Only HTTP and parsing errors reach this branch. A cancellation is turned
    # into a return value by _run_cleanup, a timeout is caught above, and
    # neither of the remaining errors carries a log ID.
    except Exception:
        return _create_measurement_result(
            dependency,
            status=AnalyticalModelPersistenceItemStatus.CLEANUP_FAILED,
            previously_persisted=False,
            persistence_details=persistence_details,
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


def _create_measurement_result_for_model(
    result: GetAnalyticalModelViewDependenciesResult,
    measurement_by_view_id: dict[str, ViewMeasurement],
) -> MeasureAnalyticalModelViewPersistenceResult:
    """
    Builds the measurement result of one analytical model from the already
    measured views it depends on.

    Args:
        result (GetAnalyticalModelViewDependenciesResult): Model with the
                                                           dependencies to
                                                           project.
        measurement_by_view_id (dict[str, ViewMeasurement]): Mapping of every
                                                             view ID the model
                                                             depends on to
                                                             their measurement
                                                             results.

    Returns:
        MeasureAnalyticalModelViewPersistenceResult: Result of the model.
    """
    # A missing model has no dependencies to measure
    if result.status is (
        AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND
    ):
        return MeasureAnalyticalModelViewPersistenceResult(
            analytical_model_name=result.analytical_model_name,
            space=result.space,
            status=AnalyticalModelPersistenceStatus.ANALYTICAL_MODEL_NOT_FOUND,
        )

    # Views shared by several analytical models are measured once and the
    # measurement is projected onto every model that depends on them
    dependencies = tuple(
        measurement_by_view_id[dependency.view_id]
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

    return MeasureAnalyticalModelViewPersistenceResult(
        analytical_model_name=result.analytical_model_name,
        space=result.space,
        analytical_model_id=result.analytical_model_id,
        status=status,
        dependencies=dependencies,
    )


async def _measure_dependencies(
    context: CommandContext,
    dependency_results: tuple[GetAnalyticalModelViewDependenciesResult, ...],
    timeout_seconds: float,
    max_concurrency: int,
    reporter: BatchReporter | None = None,
) -> tuple[MeasureAnalyticalModelViewPersistenceResult, ...]:
    """
    Measures every unique view once and projects its measurement onto each
    analytical model that depends on it.

    Example: Model A depends on views X and Y, model B on views Y and Z. View Y
             is then measured once, but its result appears in the results of
             both model A and model B.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        dependency_results (tuple[GetAnalyticalModelViewDependenciesResult, \
                                  ...]): Analytical models with the
                                         dependencies to measure.
        timeout_seconds (float): Maximum duration for persisting each view.
        max_concurrency (int): Maximum amount of concurrent tasks.
        reporter (BatchReporter | None, optional): Reporter that receives every
                                                   model as soon as its last
                                                   view was measured. None if
                                                   a sinle analytical model is
                                                   measured. Defaults to None.

    Returns:
        tuple[MeasureAnalyticalModelViewPersistenceResult, ...]: Ordered
            results of the measured view persistence runtimes.
    """
    # Collect every resolved view exactly once and remember which views each
    # model is still waiting for. A model is final once its set runs empty.
    unique_dependencies: list[AnalyticalModelViewDependency] = []
    collected: set[str] = set()
    pending: dict[int, set[str]] = {}
    for index, result in enumerate(dependency_results):
        pending[index] = set()
        for dependency in result.dependencies:
            if dependency.space is None:
                continue
            pending[index].add(dependency.view_id)
            if dependency.view_id not in collected:
                collected.add(dependency.view_id)
                unique_dependencies.append(dependency)

    measurement_by_view_id: dict[str, ViewMeasurement] = {}
    results: dict[int, MeasureAnalyticalModelViewPersistenceResult] = {}
    lock = asyncio.Lock()

    async def finalize(indexes: list[int]) -> None:
        """
        Projects and reports every model that just became final (meaning all
        the persistence runtimes of its views have been measured).

        Args:
            indexes (list[int]): Indexes of the models to finalize.
        """
        for index in indexes:
            measurement_result = _create_measurement_result_for_model(
                result=dependency_results[index],
                measurement_by_view_id=measurement_by_view_id,
            )
            results[index] = measurement_result
            if reporter is not None:
                await reporter.complete(index, measurement_result)

    # Models without any measurable view are final right away
    async with lock:
        finished = [index for index, keys in pending.items() if not keys]
        for index in finished:
            del pending[index]
    await finalize(finished)

    async def measure(dependency: AnalyticalModelViewDependency) -> None:
        """
        Callable that measures one view and finalizes every model that only
        waited for it.

        Args:
            dependency (AnalyticalModelViewDependency): View to measure.
        """
        measurement = await _measure_view(context, dependency, timeout_seconds)

        # Record the measurement and collect the models it completed. Reporting
        # happens outside the lock because the BatchReporter holds its own
        # lock.
        async with lock:
            measurement_by_view_id[dependency.view_id] = measurement
            finished = []
            for index, view_ids in list(pending.items()):
                view_ids.discard(dependency.view_id)
                if not view_ids:
                    finished.append(index)
                    del pending[index]
        await finalize(finished)

    await execute_with_concurrency_limit(
        items=tuple(unique_dependencies),
        operation=measure,
        max_concurrency=max_concurrency,
    )
    return tuple(results[index] for index in range(len(dependency_results)))


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
        CommandCancelledError: If a persistence run is cancelled.

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
        CommandCancelledError: If a persistence run is cancelled.

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

    # Shared views are measured only once, so a model becomes final with its
    # last measured view. The reporter delivers it right then, which lets the
    # caller persist finished models while the run is still going.
    reporter = BatchReporter(
        context=context,
        command=MEASURE_VIEW_PERSISTENCE_BATCH_COMMAND_NAME,
        total_items=len(dependency_results),
    )
    results = await _measure_dependencies(
        context=context,
        dependency_results=dependency_results,
        timeout_seconds=request.timeout_seconds,
        max_concurrency=request.max_concurrency,
        reporter=reporter,
    )
    summary = reporter.summary
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
