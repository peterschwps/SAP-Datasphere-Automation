import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from datasphere_core import CommandContext
from datasphere_core.commands.analytical_models import (
    get_analytical_model_view_dependencies_batch,
    measure_analytical_model_view_persistence_batch,
)
from datasphere_core.models.analytical_models import (
    AnalyticalModelDependenciesStatus,
    AnalyticalModelPersistenceStatus,
    AnalyticalModelReference,
    GetAnalyticalModelViewDependenciesBatchRequest,
    GetAnalyticalModelViewDependenciesBatchResult,
    GetAnalyticalModelViewDependenciesResult,
    MeasureAnalyticalModelViewPersistenceBatchRequest,
    MeasureAnalyticalModelViewPersistenceBatchResult,
    MeasureAnalyticalModelViewPersistenceResult,
)
from datasphere_core.models.common import (
    BatchItemResult,
    CommandStatus,
    Outcome,
)

from datasphere_cli.files.records import (
    AnalyticalModelDependenciesBatchRecord,
    AnalyticalModelPersistenceBatchRecord,
    AnalyticalModelPersistenceItemRecord,
    AnalyticalModelPersistenceResultRecord,
    BatchSummaryRecord,
)
from datasphere_cli.files.storage import (
    initialize_result,
    read_task_csv,
    write_result_json,
)
from datasphere_cli.logging import (
    LEVEL_BY_OUTCOME,
    SUCCESS,
    log_result_file,
    logger,
)

_DEPENDENCIES_COMMAND = "analytical_models.get_view_dependencies_batch"
_MEASURE_COMMAND = "analytical_models.measure_view_persistence_batch"
type AnalyticalModelBatchResult = (
    GetAnalyticalModelViewDependenciesBatchResult
    | MeasureAnalyticalModelViewPersistenceBatchResult
)

# Log level and message per status. Both enums need their own mapping: their
# members compare equal by value, so one shared table would drop entries.
_DEPENDENCIES_MESSAGES: Mapping[CommandStatus, tuple[int, str]] = {
    AnalyticalModelDependenciesStatus.COMPLETED: (
        SUCCESS,
        "Successfully resolved the view dependencies of analytical model "
        "'%s'.",
    ),
    AnalyticalModelDependenciesStatus.DEPENDENCY_NOT_FOUND: (
        logging.ERROR,
        "Unable to resolve all view dependencies of analytical model '%s'.",
    ),
    AnalyticalModelDependenciesStatus.ANALYTICAL_MODEL_NOT_FOUND: (
        logging.INFO,
        "Analytical model '%s' not found. Skipping...",
    ),
}

_MEASURE_MESSAGES: Mapping[CommandStatus, tuple[int, str]] = {
    AnalyticalModelPersistenceStatus.COMPLETED: (
        SUCCESS,
        "Successfully measured analytical model '%s'.",
    ),
    AnalyticalModelPersistenceStatus.FAILED: (
        logging.ERROR,
        "Measuring analytical model '%s' failed.",
    ),
    AnalyticalModelPersistenceStatus.TIMED_OUT: (
        logging.ERROR,
        "Measuring analytical model '%s' timed out. It may still be running.",
    ),
    AnalyticalModelPersistenceStatus.ANALYTICAL_MODEL_NOT_FOUND: (
        logging.INFO,
        "Analytical model '%s' not found. Skipping...",
    ),
}


def _log_item(
    messages: Mapping[CommandStatus, tuple[int, str]],
    result: (
        GetAnalyticalModelViewDependenciesResult
        | MeasureAnalyticalModelViewPersistenceResult
    ),
) -> None:
    """
    Logs the outcome of one analytical model.

    Args:
        messages (Mapping[CommandStatus, tuple[int, str]]): Log level and
                                                            message per
                                                            status.
        result (GetAnalyticalModelViewDependenciesResult | \
                MeasureAnalyticalModelViewPersistenceResult): Result of one
                                                              completed model.
    """
    # A status added to the Core later would otherwise abort the batch
    level, message = messages.get(
        result.status,
        (
            LEVEL_BY_OUTCOME[result.status.outcome],
            "Analytical model '%s' finished with an unexpected status. See "
            "the result file.",
        ),
    )
    logger.log(level, message, result.analytical_model_name)


def _log_summary(result: AnalyticalModelBatchResult, path: Path) -> None:
    """
    Logs the outcome counts of a batch and where its result was written.

    Args:
        result (AnalyticalModelBatchResult): Completed batch result to
                                             summarize.
        path (Path): Path the result file was written to.
    """
    summary = result.summary
    logger.info(
        "Results: %s succeeded, %s failed, %s skipped, %s timed out.",
        summary.succeeded,
        summary.failed,
        summary.skipped,
        summary.timed_out,
    )
    log_result_file(path)


def _summary_record(result: AnalyticalModelBatchResult) -> BatchSummaryRecord:
    """
    Converts a batch summary into its JSON record.

    Args:
        result (AnalyticalModelBatchResult): Completed batch result to convert.

    Returns:
        BatchSummaryRecord: Outcome counts of the batch.
    """
    summary = result.summary
    return {
        "total": summary.total,
        "succeeded": summary.succeeded,
        "failed": summary.failed,
        "skipped": summary.skipped,
        "timed_out": summary.timed_out,
    }


def _measure_output(
    results: tuple[MeasureAnalyticalModelViewPersistenceResult, ...],
) -> AnalyticalModelPersistenceBatchRecord:
    """
    Converts persistence measurements into their JSON record. The summary is
    recomputed here because checkpoints are written while the batch is still
    running.

    Args:
        results (tuple[MeasureAnalyticalModelViewPersistenceResult, ...]):
            Measurements completed so far.

    Returns:
        AnalyticalModelPersistenceBatchRecord: Measurements and their summary.
    """
    result_records: list[AnalyticalModelPersistenceResultRecord] = []

    # Iterate over analytical models
    for item in results:
        dependency_records: list[AnalyticalModelPersistenceItemRecord] = []

        # Iterate over view dependencies and add them to results
        for dependency in item.dependencies:
            dependency_records.append(
                {
                    "view_id": dependency.view_id,
                    "view": dependency.view_name,
                    "space": dependency.space,
                    "status": dependency.status,
                    "previously_persisted": dependency.previously_persisted,
                    "runtime_seconds": dependency.runtime_seconds,
                    "persistence_log_status": (
                        dependency.persistence_log_status
                    ),
                    "persistence_log_id": dependency.persistence_log_id,
                    "cleanup_log_status": dependency.cleanup_log_status,
                    "cleanup_log_id": dependency.cleanup_log_id,
                    "persistence_removed": dependency.persistence_removed,
                    "manual_intervention": dependency.manual_intervention,
                }
            )

        # Add analytical model and its dependencies to the result
        result_records.append(
            {
                "analytical_model": item.analytical_model_name,
                "space": item.space,
                "status": item.status,
                "analytical_model_id": item.analytical_model_id,
                "dependencies": dependency_records,
            }
        )

    # Count different statuses
    counts = Counter(item.status.outcome for item in results)
    return {
        "results": result_records,
        "summary": {
            "total": len(results),
            "succeeded": counts[Outcome.SUCCEEDED],
            "failed": counts[Outcome.FAILED],
            "skipped": counts[Outcome.SKIPPED],
            "timed_out": counts[Outcome.TIMED_OUT],
        },
    }


async def export_analytical_model_view_dependencies(
    context: CommandContext,
    space: str | None = None,
    deduplicate_views: bool = False,
    max_concurrency: int = 5,
    workspace_root: str | Path | None = None,
) -> GetAnalyticalModelViewDependenciesBatchResult:
    """
    Exports all view dependencies of analytical models.

    Args:
        context (CommandContext): Context with the authenticated client.
        space (str | None, optional): Space to limit dependency discovery.
                                      Defaults to None.
        deduplicate_views (bool, optional): Whether to remove duplicate views.
                                            Defaults to False.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 5.
        workspace_root (str | Path | None, optional): Root for task and
                                                      result files. Uses the
                                                      default workspace when
                                                      None. Defaults to None.

    Returns:
        GetAnalyticalModelViewDependenciesBatchResult: Dependency results.
    """
    # Write empty result file
    initialize_result(
        command=_DEPENDENCIES_COMMAND,
        root=workspace_root,
        space=space,
    )

    # Resolve all analytical models and their view dependencies
    request = GetAnalyticalModelViewDependenciesBatchRequest(
        space=space,
        deduplicate_views=deduplicate_views,
        max_concurrency=max_concurrency,
    )

    async def report(update: BatchItemResult) -> None:
        """
        Logs the outcome of one resolved analytical model.

        Args:
            update (BatchItemResult): Result of one completed model.

        Raises:
            TypeError: If the item carries an unexpected result type.
        """
        if not isinstance(
            update.result, GetAnalyticalModelViewDependenciesResult
        ):
            raise TypeError("Analytical model item has an unexpected result.")
        _log_item(_DEPENDENCIES_MESSAGES, update.result)

    # Report every model as soon as it is resolved
    result = await get_analytical_model_view_dependencies_batch(
        replace(context, batch_item_result_callback=report),
        request,
    )

    # Loop over all views inside all models to build the JSON record
    output: AnalyticalModelDependenciesBatchRecord = {
        "results": [
            {
                "analytical_model": item.analytical_model_name,
                "space": item.space,
                "status": item.status,
                "analytical_model_id": item.analytical_model_id,
                "dependencies": [
                    {
                        "view_id": dependency.view_id,
                        "view": dependency.view_name,
                        "space": dependency.space,
                        "status": dependency.status,
                    }
                    for dependency in item.dependencies
                ],
            }
            for item in result.results
        ],
        "summary": _summary_record(result),
    }

    # Write result JSON
    path = write_result_json(
        command=_DEPENDENCIES_COMMAND,
        data=output,
        root=workspace_root,
        space=space,
    )

    # Log outcome counts
    _log_summary(result, path)
    return result


async def measure_analytical_model_view_persistence_from_file(
    context: CommandContext,
    timeout_seconds: float = 3600.0,
    max_concurrency: int = 5,
    workspace_root: str | Path | None = None,
) -> MeasureAnalyticalModelViewPersistenceBatchResult:
    """
    Measures the persistence runtimes of view dependencies of analytical
    models. Writes the result after every completed model to ensure that
    results are persisted as soon as possible.

    Args:
        context (CommandContext): Context with the authenticated client.
        timeout_seconds (float, optional): Maximum runtime for each model.
                                           Defaults to 3600.0 seconds.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 5.
        workspace_root (str | Path | None, optional): Root for task and
                                                      result files. Uses the
                                                      default workspace when
                                                      None. Defaults to None.

    Raises:
        TypeError: If a checkpoint carries an unexpected result type.

    Returns:
        MeasureAnalyticalModelViewPersistenceBatchResult: Measurement results.
    """
    # Write empty result file
    initialize_result(_MEASURE_COMMAND, workspace_root)

    # Build request from task file
    records = read_task_csv(_MEASURE_COMMAND, workspace_root)
    request = MeasureAnalyticalModelViewPersistenceBatchRequest(
        analytical_models=tuple(
            AnalyticalModelReference(
                name=record["analytical_model"],
                space=record["space"],
            )
            for record in records
        ),
        timeout_seconds=timeout_seconds,
        max_concurrency=max_concurrency,
    )

    # Dict to store measurements of completed models
    checkpointed: dict[int, MeasureAnalyticalModelViewPersistenceResult] = {}

    async def checkpoint(update: BatchItemResult) -> None:
        """
        Callable that writes every completed measurement of an analytical model
        after it is completed.

        Args:
            update (BatchItemResult): Result of one completed model.

        Raises:
            TypeError: If the checkpoint carries an unexpected result.
        """
        if not isinstance(
            update.result, MeasureAnalyticalModelViewPersistenceResult
        ):
            raise TypeError(
                "Measurement checkpoint has an unexpected result type."
            )
        item = update.result
        checkpointed[update.item_index] = item

        # Rewrite the result JSON
        # Models finish in any order, so the file is rebuilt in input order
        ordered = tuple(checkpointed[index] for index in sorted(checkpointed))
        write_result_json(
            command=_MEASURE_COMMAND,
            data=_measure_output(ordered),
            root=workspace_root,
        )

        # Report the model once its measurement is safely on disk
        _log_item(_MEASURE_MESSAGES, item)

    # Start the batch measurement with the callback to write results after
    # each completed model
    result = await measure_analytical_model_view_persistence_batch(
        replace(context, batch_item_result_callback=checkpoint),
        request,
    )

    # Write result JSON
    path = write_result_json(
        _MEASURE_COMMAND,
        _measure_output(result.results),
        workspace_root,
    )

    # Log outcome counts
    _log_summary(result, path)
    return result
