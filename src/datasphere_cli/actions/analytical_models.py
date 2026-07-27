from dataclasses import replace
from pathlib import Path

from datasphere_core import CommandContext
from datasphere_core.models.analytical_models import (
    AnalyticalModelReference,
    GetAnalyticalModelViewDependenciesBatchRequest,
    GetAnalyticalModelViewDependenciesBatchResult,
    MeasureAnalyticalModelViewPersistenceBatchRequest,
    MeasureAnalyticalModelViewPersistenceBatchResult,
    MeasureAnalyticalModelViewPersistenceResult,
)
from datasphere_core.models.common import BatchItemResult

from datasphere_cli.actions.dispatch import dispatch_command
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
from datasphere_cli.logging import logger

_DEPENDENCIES_COMMAND = "analytical_models.get_view_dependencies_batch"
_MEASURE_COMMAND = "analytical_models.measure_view_persistence_batch"
type AnalyticalModelBatchResult = (
    GetAnalyticalModelViewDependenciesBatchResult
    | MeasureAnalyticalModelViewPersistenceBatchResult
)


def _log_summary(
    command: str,
    result: AnalyticalModelBatchResult,
    path: Path,
) -> None:
    summary = result.summary
    logger.info(
        "%s: %s succeeded, %s failed, %s skipped, %s timed out.",
        command,
        summary.succeeded,
        summary.failed,
        summary.skipped,
        summary.timed_out,
    )
    logger.info("Results saved to '%s'.", path)


def _summary_record(result: AnalyticalModelBatchResult) -> BatchSummaryRecord:
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
    result_records: list[AnalyticalModelPersistenceResultRecord] = []
    for item in results:
        dependency_records: list[AnalyticalModelPersistenceItemRecord] = []
        for dependency in item.dependencies:
            dependency_records.append(
                {
                    "view_id": dependency.view_id,
                    "view": dependency.view_name,
                    "space": dependency.space,
                    "status": dependency.status,
                    "previously_persisted": dependency.previously_persisted,
                    "runtime_seconds": dependency.runtime_seconds,
                    "persistence_sap_status": (
                        dependency.persistence_sap_status
                    ),
                    "persistence_log_id": (dependency.persistence_log_id),
                    "cleanup_sap_status": dependency.cleanup_sap_status,
                    "cleanup_log_id": dependency.cleanup_log_id,
                    "persistence_removed": dependency.persistence_removed,
                    "manual_intervention": dependency.manual_intervention,
                }
            )
        result_records.append(
            {
                "analytical_model": item.analytical_model_name,
                "space": item.space,
                "status": item.status,
                "analytical_model_id": item.analytical_model_id,
                "dependencies": dependency_records,
            }
        )

    return {
        "results": result_records,
        "summary": {
            "total": len(results),
            "succeeded": sum(item.status == "completed" for item in results),
            "failed": sum(item.status == "failed" for item in results),
            "skipped": sum(
                item.status == "analytical_model_not_found" for item in results
            ),
            "timed_out": sum(item.status == "timed_out" for item in results),
        },
    }


async def export_analytical_model_view_dependencies(
    context: CommandContext,
    space: str | None = None,
    deduplicate_views: bool = False,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> GetAnalyticalModelViewDependenciesBatchResult:
    """Export analytical-model dependencies through the Core command.

    Args:
        context (CommandContext): Core context with the authenticated client.
        space (str | None, optional): Space to limit dependency discovery.
        deduplicate_views (bool, optional): Whether to remove duplicate views.
        max_concurrency (int, optional): Maximum concurrent SAP operations.
        workspace_root (str | Path | None, optional): Root for task and result
            files. Uses the default workspace when None.

    Returns:
        GetAnalyticalModelViewDependenciesBatchResult: Dependency results.
    """
    initialize_result(
        _DEPENDENCIES_COMMAND,
        workspace_root,
        space=space,
    )
    request = GetAnalyticalModelViewDependenciesBatchRequest(
        space=space,
        deduplicate_views=deduplicate_views,
        max_concurrency=max_concurrency,
    )
    result = await dispatch_command(
        _DEPENDENCIES_COMMAND,
        context,
        request,
        GetAnalyticalModelViewDependenciesBatchRequest,
        GetAnalyticalModelViewDependenciesBatchResult,
    )
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
    path = write_result_json(
        _DEPENDENCIES_COMMAND,
        output,
        workspace_root,
        space=space,
    )
    _log_summary(_DEPENDENCIES_COMMAND, result, path)
    return result


async def measure_analytical_model_view_persistence_from_file(
    context: CommandContext,
    timeout_seconds: float = 3600.0,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> MeasureAnalyticalModelViewPersistenceBatchResult:
    """Measure models and write only the final result atomically.

    The Core checkpoint callback atomically persists completed model results
    while the measurement is running.

    Args:
        context (CommandContext): Core context with the authenticated client.
        timeout_seconds (float, optional): Maximum runtime for each model.
        max_concurrency (int, optional): Maximum concurrent SAP operations.
        workspace_root (str | Path | None, optional): Root for task and result
            files. Uses the default workspace when None.

    Returns:
        MeasureAnalyticalModelViewPersistenceBatchResult: Measurement results.
    """
    initialize_result(_MEASURE_COMMAND, workspace_root)
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
    checkpointed: dict[int, MeasureAnalyticalModelViewPersistenceResult] = {}

    async def checkpoint(update: BatchItemResult) -> None:
        if not isinstance(
            update.result, MeasureAnalyticalModelViewPersistenceResult
        ):
            raise TypeError(
                "Measurement checkpoint has an unexpected result type."
            )
        item = update.result
        checkpointed[update.item_index] = item
        ordered = tuple(checkpointed[index] for index in sorted(checkpointed))
        write_result_json(
            _MEASURE_COMMAND,
            _measure_output(ordered),
            workspace_root,
        )

    result = await dispatch_command(
        _MEASURE_COMMAND,
        replace(context, batch_item_result_callback=checkpoint),
        request,
        MeasureAnalyticalModelViewPersistenceBatchRequest,
        MeasureAnalyticalModelViewPersistenceBatchResult,
    )
    path = write_result_json(
        _MEASURE_COMMAND,
        _measure_output(result.results),
        workspace_root,
    )
    _log_summary(_MEASURE_COMMAND, result, path)
    return result
