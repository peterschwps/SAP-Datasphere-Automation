from pathlib import Path

from datasphere_core import CommandContext
from datasphere_core.commands.views import (
    create_view_partitioning_batch,
    delete_view_partitioning_batch,
    find_view_attribute_matches_batch,
    find_view_persistence_candidates_batch,
    lock_view_partitions_batch,
    persist_view_batch,
    unlock_view_partitions_batch,
    unpersist_view_batch,
)
from datasphere_core.models.views import (
    CreateViewPartitioningBatchRequest,
    CreateViewPartitioningBatchResult,
    CreateViewPartitioningRequest,
    DeleteViewPartitioningBatchRequest,
    DeleteViewPartitioningBatchResult,
    DeleteViewPartitioningRequest,
    FindViewAttributeMatchesBatchRequest,
    FindViewAttributeMatchesBatchResult,
    FindViewPersistenceCandidatesBatchRequest,
    FindViewPersistenceCandidatesBatchResult,
    LockViewPartitionsBatchRequest,
    LockViewPartitionsBatchResult,
    LockViewPartitionsRequest,
    PersistViewBatchRequest,
    PersistViewBatchResult,
    PersistViewRequest,
    UnlockViewPartitionsBatchRequest,
    UnlockViewPartitionsBatchResult,
    UnlockViewPartitionsRequest,
    UnpersistViewBatchRequest,
    UnpersistViewBatchResult,
    UnpersistViewRequest,
)

from datasphere_cli.files.records import (
    ViewAttributeResultRecord,
    ViewPartitioningResultRecord,
    ViewPersistenceCandidateResultRecord,
    ViewPersistenceResultRecord,
    ViewStatusResultRecord,
)
from datasphere_cli.files.storage import (
    initialize_result,
    read_task_csv,
    write_result_csv,
)
from datasphere_cli.logging import logger

_CANDIDATES_COMMAND = "views.find_persistence_candidates_batch"
_ATTRIBUTES_COMMAND = "views.find_attribute_matches_batch"
_CREATE_COMMAND = "views.create_partitioning_batch"
_DELETE_COMMAND = "views.delete_partitioning_batch"
_PERSIST_COMMAND = "views.persist_batch"
_UNPERSIST_COMMAND = "views.unpersist_batch"
_LOCK_COMMAND = "views.lock_partitions_batch"
_UNLOCK_COMMAND = "views.unlock_partitions_batch"

type ViewBatchResult = (
    CreateViewPartitioningBatchResult
    | DeleteViewPartitioningBatchResult
    | FindViewAttributeMatchesBatchResult
    | FindViewPersistenceCandidatesBatchResult
    | LockViewPartitionsBatchResult
    | PersistViewBatchResult
    | UnlockViewPartitionsBatchResult
    | UnpersistViewBatchResult
)


def _log_summary(
    command: str,
    result: ViewBatchResult,
    path: Path,
) -> None:
    """
    Logs the outcome counts of a batch and where its result was written.

    Args:
        command (str): Command the results belong to.
        result (ViewBatchResult): Completed batch result to summarize.
        path (Path): Path the result file was written to.
    """
    logger.info(
        "%s: %s succeeded, %s failed, %s skipped, %s timed out.",
        command,
        result.summary.succeeded,
        result.summary.failed,
        result.summary.skipped,
        result.summary.timed_out,
    )
    logger.info("Results saved to '%s'.", path)


async def export_view_persistence_candidates(
    context: CommandContext,
    minimum_candidate_score: int | float = 10,
    timeout_seconds: float = 3600.0,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> FindViewPersistenceCandidatesBatchResult:
    """
    Exports view persistence candidates.

    Args:
        context (CommandContext): Context with the authenticated client.
        minimum_candidate_score (int | float, optional): Lowest candidate
                                                         score a view has to
                                                         reach. Defaults to 10.
        timeout_seconds (float, optional): Maximum runtime for each view.
                                           Defaults to 3600.0 seconds.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.
        workspace_root (str | Path | None, optional): Root for the result
                                                      file. Uses the default
                                                      workspace when None.
                                                      Defaults to None.

    Returns:
        FindViewPersistenceCandidatesBatchResult: Candidate results.
    """
    initialize_result(_CANDIDATES_COMMAND, workspace_root)
    request = FindViewPersistenceCandidatesBatchRequest(
        minimum_candidate_score=minimum_candidate_score,
        timeout_seconds=timeout_seconds,
        max_concurrency=max_concurrency,
    )
    result = await find_view_persistence_candidates_batch(context, request)

    # Write one row per candidate
    # A view without candidates keeps a row with empty candidate fields
    rows: list[ViewPersistenceCandidateResultRecord] = []
    for item in result.results:
        if not item.candidates:
            rows.append(
                {
                    "source_view": item.view,
                    "source_space": item.space,
                    "view": None,
                    "space": None,
                    "business_name": None,
                    "score": None,
                    "is_persisted": None,
                    "status": item.status,
                    "log_id": item.log_id,
                }
            )
            continue
        rows.extend(
            {
                "source_view": item.view,
                "source_space": item.space,
                "view": candidate.view,
                "space": candidate.space,
                "business_name": candidate.business_name,
                "score": candidate.score,
                "is_persisted": candidate.is_persisted,
                "status": item.status,
                "log_id": item.log_id,
            }
            for candidate in item.candidates
        )
    path = write_result_csv(_CANDIDATES_COMMAND, rows, workspace_root)
    _log_summary(_CANDIDATES_COMMAND, result, path)
    return result


async def export_view_attribute_matches(
    context: CommandContext,
    attribute_substring: str,
    case_sensitive: bool = False,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> FindViewAttributeMatchesBatchResult:
    """
    Exports view attributes matching a substring.

    Args:
        context (CommandContext): Context with the authenticated client.
        attribute_substring (str): Substring to find in view attributes.
        case_sensitive (bool, optional): Whether matching respects case.
                                         Defaults to False.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.
        workspace_root (str | Path | None, optional): Root for the result
                                                      file. Uses the default
                                                      workspace when None.
                                                      Defaults to None.

    Returns:
        FindViewAttributeMatchesBatchResult: Attribute-match results.
    """
    initialize_result(_ATTRIBUTES_COMMAND, workspace_root)
    request = FindViewAttributeMatchesBatchRequest(
        substring=attribute_substring,
        case_sensitive=case_sensitive,
        max_concurrency=max_concurrency,
    )
    result = await find_view_attribute_matches_batch(context, request)
    rows: list[ViewAttributeResultRecord] = []
    for item in result.results:
        for attribute in item.attributes:
            rows.append(
                {
                    "view": item.view,
                    "space": item.space,
                    "business_name": item.business_name,
                    "attribute": attribute,
                    "status": item.status,
                }
            )
    path = write_result_csv(_ATTRIBUTES_COMMAND, rows, workspace_root)
    _log_summary(_ATTRIBUTES_COMMAND, result, path)
    return result


async def create_view_partitioning_from_file(
    context: CommandContext,
    start_year: int,
    end_year: int,
    overwrite_existing: bool = False,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> CreateViewPartitioningBatchResult:
    """
    Creates partitioning for views listed in the task file.

    Args:
        context (CommandContext): Context with the authenticated client.
        start_year (int): First year included in the partitioning range.
        end_year (int): Last year included in the partitioning range.
        overwrite_existing (bool, optional): Whether to replace existing
                                             partitioning. Defaults to False.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.
        workspace_root (str | Path | None, optional): Root for task and
                                                      result files. Uses the
                                                      default workspace when
                                                      None. Defaults to None.

    Returns:
        CreateViewPartitioningBatchResult: Partitioning operation results.
    """
    initialize_result(_CREATE_COMMAND, workspace_root)
    records = read_task_csv(_CREATE_COMMAND, workspace_root)
    request = CreateViewPartitioningBatchRequest(
        requests=tuple(
            CreateViewPartitioningRequest(
                view=record["view"],
                space=record["space"],
                attribute=record["attribute"],
                start_year=start_year,
                end_year=end_year,
                overwrite_existing=overwrite_existing,
            )
            for record in records
        ),
        max_concurrency=max_concurrency,
    )
    result = await create_view_partitioning_batch(context, request)
    return _write_partitioning_result(
        _CREATE_COMMAND,
        result,
        workspace_root,
        records,
    )


async def delete_view_partitioning_from_file(
    context: CommandContext,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> DeleteViewPartitioningBatchResult:
    """
    Deletes partitioning for views listed in the task file.

    Args:
        context (CommandContext): Context with the authenticated client.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.
        workspace_root (str | Path | None, optional): Root for task and
                                                      result files. Uses the
                                                      default workspace when
                                                      None. Defaults to None.

    Returns:
        DeleteViewPartitioningBatchResult: Partitioning operation results.
    """
    initialize_result(_DELETE_COMMAND, workspace_root)
    records = read_task_csv(_DELETE_COMMAND, workspace_root)

    # Build request from task file
    # The columns are named after the request fields, so a record splats
    request = DeleteViewPartitioningBatchRequest(
        requests=tuple(
            DeleteViewPartitioningRequest(**record) for record in records
        ),
        max_concurrency=max_concurrency,
    )
    result = await delete_view_partitioning_batch(context, request)
    return _write_status_result(
        _DELETE_COMMAND,
        result,
        workspace_root,
    )


async def persist_views_from_file(
    context: CommandContext,
    timeout_seconds: float = 3600.0,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> PersistViewBatchResult:
    """
    Persists the views listed in the task file. Writes the result once the
    batch completed.

    Args:
        context (CommandContext): Context with the authenticated client.
        timeout_seconds (float, optional): Maximum runtime for each view.
                                           Defaults to 3600.0 seconds.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.
        workspace_root (str | Path | None, optional): Root for task and
                                                      result files. Uses the
                                                      default workspace when
                                                      None. Defaults to None.

    Returns:
        PersistViewBatchResult: View persistence results.
    """
    initialize_result(_PERSIST_COMMAND, workspace_root)
    records = read_task_csv(_PERSIST_COMMAND, workspace_root)
    request = PersistViewBatchRequest(
        requests=tuple(
            PersistViewRequest(
                **record,
                timeout_seconds=timeout_seconds,
            )
            for record in records
        ),
        max_concurrency=max_concurrency,
    )
    result = await persist_view_batch(context, request)
    return _write_persistence_result(
        _PERSIST_COMMAND,
        result,
        workspace_root,
    )


async def unpersist_views_from_file(
    context: CommandContext,
    timeout_seconds: float = 3600.0,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> UnpersistViewBatchResult:
    """
    Removes the persisted data of the views listed in the task file. Writes
    the result once the batch completed.

    Args:
        context (CommandContext): Context with the authenticated client.
        timeout_seconds (float, optional): Maximum runtime for each view.
                                           Defaults to 3600.0 seconds.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.
        workspace_root (str | Path | None, optional): Root for task and
                                                      result files. Uses the
                                                      default workspace when
                                                      None. Defaults to None.

    Returns:
        UnpersistViewBatchResult: View unpersistence results.
    """
    initialize_result(_UNPERSIST_COMMAND, workspace_root)
    records = read_task_csv(_UNPERSIST_COMMAND, workspace_root)
    request = UnpersistViewBatchRequest(
        requests=tuple(
            UnpersistViewRequest(
                **record,
                timeout_seconds=timeout_seconds,
            )
            for record in records
        ),
        max_concurrency=max_concurrency,
    )
    result = await unpersist_view_batch(context, request)
    return _write_persistence_result(
        _UNPERSIST_COMMAND,
        result,
        workspace_root,
    )


async def lock_view_partitions_from_file(
    context: CommandContext,
    until_year: int,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> LockViewPartitionsBatchResult:
    """
    Locks partitions for views listed in the task file.

    Args:
        context (CommandContext): Context with the authenticated client.
        until_year (int): Last year whose partitions should be locked.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.
        workspace_root (str | Path | None, optional): Root for task and
                                                      result files. Uses the
                                                      default workspace when
                                                      None. Defaults to None.

    Returns:
        LockViewPartitionsBatchResult: Partition-lock operation results.
    """
    initialize_result(_LOCK_COMMAND, workspace_root)
    records = read_task_csv(_LOCK_COMMAND, workspace_root)
    request = LockViewPartitionsBatchRequest(
        requests=tuple(
            LockViewPartitionsRequest(
                **record,
                until_year=until_year,
            )
            for record in records
        ),
        max_concurrency=max_concurrency,
    )
    result = await lock_view_partitions_batch(context, request)
    return _write_status_result(
        _LOCK_COMMAND,
        result,
        workspace_root,
    )


async def unlock_view_partitions_from_file(
    context: CommandContext,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> UnlockViewPartitionsBatchResult:
    """
    Unlocks partitions for views listed in the task file.

    Args:
        context (CommandContext): Context with the authenticated client.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.
        workspace_root (str | Path | None, optional): Root for task and
                                                      result files. Uses the
                                                      default workspace when
                                                      None. Defaults to None.

    Returns:
        UnlockViewPartitionsBatchResult: Partition-unlock operation results.
    """
    initialize_result(_UNLOCK_COMMAND, workspace_root)
    records = read_task_csv(_UNLOCK_COMMAND, workspace_root)
    request = UnlockViewPartitionsBatchRequest(
        requests=tuple(
            UnlockViewPartitionsRequest(**record) for record in records
        ),
        max_concurrency=max_concurrency,
    )
    result = await unlock_view_partitions_batch(context, request)
    return _write_status_result(
        _UNLOCK_COMMAND,
        result,
        workspace_root,
    )


def _write_status_result[ResultT: ViewBatchResult](
    command: str,
    result: ResultT,
    workspace_root: str | Path | None,
) -> ResultT:
    """
    Writes the view statuses of a batch result and logs its summary.

    Args:
        command (str): Command the results belong to.
        result (ResultT): Completed batch result to write.
        workspace_root (str | Path | None): Root for the result file. Uses
                                            the default workspace when
                                            None.

    Returns:
        ResultT: The unchanged batch result.
    """
    rows: list[ViewStatusResultRecord] = [
        {
            "view": item.view,
            "space": item.space,
            "status": item.status,
        }
        for item in result.results
    ]
    path = write_result_csv(command, rows, workspace_root)
    _log_summary(command, result, path)
    return result


def _write_partitioning_result(
    command: str,
    result: CreateViewPartitioningBatchResult,
    workspace_root: str | Path | None,
    records: list[dict[str, str]],
) -> CreateViewPartitioningBatchResult:
    """
    Writes the partitioning results of a batch and logs its summary. The
    partitioned attribute is only known from the task records.

    Args:
        command (str): Command the results belong to.
        result (CreateViewPartitioningBatchResult): Completed batch result
                                                    to write.
        workspace_root (str | Path | None): Root for the result file. Uses
                                            the default workspace when
                                            None.
        records (list[dict[str, str]]): Task records the batch was built
                                        from.

    Returns:
        CreateViewPartitioningBatchResult: The unchanged batch result.
    """
    # Pair every result with its task record to recover the attribute
    # 'strict=True' guards the assumption that both keep the input order
    rows: list[ViewPartitioningResultRecord] = [
        {
            "view": item.view,
            "space": item.space,
            "attribute": record["attribute"],
            "status": item.status,
        }
        for item, record in zip(result.results, records, strict=True)
    ]
    path = write_result_csv(command, rows, workspace_root)
    _log_summary(command, result, path)
    return result


def _write_persistence_result[
    ResultT: PersistViewBatchResult | UnpersistViewBatchResult
](
    command: str,
    result: ResultT,
    workspace_root: str | Path | None,
) -> ResultT:
    """
    Writes the persistence results of a batch and logs its summary.

    Args:
        command (str): Command the results belong to.
        result (ResultT): Completed batch result to write.
        workspace_root (str | Path | None): Root for the result file. Uses
                                            the default workspace when
                                            None.

    Returns:
        ResultT: The unchanged batch result.
    """
    rows: list[ViewPersistenceResultRecord] = [
        {
            "view": item.view,
            "space": item.space,
            "status": item.status,
            "log_status": item.log_status,
            "log_id": item.log_id,
            "runtime_seconds": item.runtime_seconds,
        }
        for item in result.results
    ]
    path = write_result_csv(command, rows, workspace_root)
    _log_summary(command, result, path)
    return result
