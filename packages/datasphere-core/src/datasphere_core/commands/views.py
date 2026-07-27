import math
from typing import Any

from datasphere_api import (
    ViewAnalysisCancelled,
    ViewAnalysisTimeout,
    ViewPersistenceCancelled,
    ViewPersistenceTimeout,
)

from datasphere_core.context import CommandContext
from datasphere_core.definitions import CommandDefinition
from datasphere_core.errors import CommandCancelledError
from datasphere_core.execution import (
    BatchExecution,
    batch_result_phase,
    execute_batch,
    execute_command,
)
from datasphere_core.models.common import (
    BatchItemFinalStatus,
    CommandProgressPhase,
)
from datasphere_core.models.views import (
    DEFAULT_VIEW_TIMEOUT_SECONDS,
    MAXIMUM_VIEW_TIMEOUT_SECONDS,
    CreateViewPartitioningBatchRequest,
    CreateViewPartitioningBatchResult,
    CreateViewPartitioningRequest,
    CreateViewPartitioningResult,
    CreateViewPartitioningStatus,
    DeleteViewPartitioningBatchRequest,
    DeleteViewPartitioningBatchResult,
    DeleteViewPartitioningRequest,
    DeleteViewPartitioningResult,
    DeleteViewPartitioningStatus,
    FindViewAttributeMatchesBatchRequest,
    FindViewAttributeMatchesBatchResult,
    FindViewAttributeMatchesRequest,
    FindViewAttributeMatchesResult,
    FindViewAttributeMatchesStatus,
    FindViewPersistenceCandidatesBatchRequest,
    FindViewPersistenceCandidatesBatchResult,
    FindViewPersistenceCandidatesRequest,
    FindViewPersistenceCandidatesResult,
    FindViewPersistenceCandidatesStatus,
    LockViewPartitionsBatchRequest,
    LockViewPartitionsBatchResult,
    LockViewPartitionsRequest,
    LockViewPartitionsResult,
    LockViewPartitionsStatus,
    PersistViewBatchRequest,
    PersistViewBatchResult,
    PersistViewRequest,
    PersistViewResult,
    PersistViewStatus,
    UnlockViewPartitionsBatchRequest,
    UnlockViewPartitionsBatchResult,
    UnlockViewPartitionsRequest,
    UnlockViewPartitionsResult,
    UnlockViewPartitionsStatus,
    UnpersistViewBatchRequest,
    UnpersistViewBatchResult,
    UnpersistViewRequest,
    UnpersistViewResult,
    UnpersistViewStatus,
    ViewPersistenceCandidate,
)

FIND_PERSISTENCE_CANDIDATES_COMMAND_NAME = "views.find_persistence_candidates"
FIND_PERSISTENCE_CANDIDATES_BATCH_COMMAND_NAME = (
    "views.find_persistence_candidates_batch"
)
FIND_ATTRIBUTE_MATCHES_COMMAND_NAME = "views.find_attribute_matches"
FIND_ATTRIBUTE_MATCHES_BATCH_COMMAND_NAME = (
    "views.find_attribute_matches_batch"
)


CREATE_PARTITIONING_COMMAND_NAME = "views.create_partitioning"
CREATE_PARTITIONING_BATCH_COMMAND_NAME = "views.create_partitioning_batch"
DELETE_PARTITIONING_COMMAND_NAME = "views.delete_partitioning"
DELETE_PARTITIONING_BATCH_COMMAND_NAME = "views.delete_partitioning_batch"
PERSIST_COMMAND_NAME = "views.persist"
PERSIST_BATCH_COMMAND_NAME = "views.persist_batch"
UNPERSIST_COMMAND_NAME = "views.unpersist"
UNPERSIST_BATCH_COMMAND_NAME = "views.unpersist_batch"
LOCK_PARTITIONS_COMMAND_NAME = "views.lock_partitions"
LOCK_PARTITIONS_BATCH_COMMAND_NAME = "views.lock_partitions_batch"
UNLOCK_PARTITIONS_COMMAND_NAME = "views.unlock_partitions"
UNLOCK_PARTITIONS_BATCH_COMMAND_NAME = "views.unlock_partitions_batch"


def _log_id(value: object) -> str | None:
    """
    Converts a scalar SAP log identifier to a string.

    Args:
        value (object): Candidate identifier returned by the API.

    Returns:
        str | None: Identifier string, or None for unsupported values.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    return str(value)


def _sap_status(details: dict[str, Any]) -> str | None:
    """
    Reads a string SAP status from operation details.

    Args:
        details (dict[str, Any]): SAP detail mapping to inspect.

    Returns:
        str | None: SAP status when present as a string.
    """
    status = details.get("status")
    return status if isinstance(status, str) else None


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


def _result_phase(status: str) -> CommandProgressPhase:
    """
    Maps a view command status to its lifecycle progress phase.

    Args:
        status (str): Result status to classify.

    Returns:
        CommandProgressPhase: Timed out, failed, or completed phase.
    """
    if status == "timed_out":
        return CommandProgressPhase.TIMED_OUT
    if status in ("failed", "start_failed", "invalid_column"):
        return CommandProgressPhase.FAILED
    return CommandProgressPhase.COMPLETED


def _candidate_from_entity(
    entity: dict[str, Any],
    request: FindViewPersistenceCandidatesRequest,
) -> ViewPersistenceCandidate:
    """
    Converts an analyzer entity into a persistence candidate model.

    Args:
        entity (dict[str, Any]): Analyzer entity details.
        request (FindViewPersistenceCandidatesRequest): Request supplying
            fallback view, space, and score values.

    Returns:
        ViewPersistenceCandidate: Normalized candidate details.
    """
    entity_view = entity.get("entity")
    entity_space = entity.get("space")
    business_name = entity.get("businessName")
    is_persisted = entity.get("isPersisted")
    return ViewPersistenceCandidate(
        view=entity_view if isinstance(entity_view, str) else request.view,
        space=(
            entity_space if isinstance(entity_space, str) else request.space
        ),
        score=request.candidate_score,
        business_name=(
            business_name if isinstance(business_name, str) else None
        ),
        is_persisted=is_persisted if isinstance(is_persisted, bool) else None,
    )


async def _find_view_persistence_candidates(
    context: CommandContext,
    request: FindViewPersistenceCandidatesRequest,
) -> FindViewPersistenceCandidatesResult:
    """
    Analyzes one view and normalizes its persistence candidates.

    Args:
        context (CommandContext): Authenticated client used for analysis.
        request (FindViewPersistenceCandidatesRequest): View and score to use.

    Returns:
        FindViewPersistenceCandidatesResult: Candidate analysis result.

    Raises:
        CommandCancelledError: If view analysis is cancelled.
    """
    try:
        analysis = await context.client.views.analyze_view(
            request.view,
            request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except ViewAnalysisTimeout as error:
        return FindViewPersistenceCandidatesResult(
            view=request.view,
            space=request.space,
            status=FindViewPersistenceCandidatesStatus.TIMED_OUT,
            candidates=(),
            log_id=_log_id(error.log_id),
        )
    except ViewAnalysisCancelled as error:
        raise CommandCancelledError(
            str(error),
            log_id=_log_id(error.log_id),
        ) from None

    entities = analysis["entityStats"]
    candidates = tuple(
        _candidate_from_entity(entity, request)
        for entity in entities
        if entity.get("persistencyCandidateScore") == request.candidate_score
    )
    log_id = _log_id(analysis.get("logId"))
    if not log_id:
        for entity in entities:
            log_id = _log_id(entity.get("logId"))
            if log_id:
                break
    return FindViewPersistenceCandidatesResult(
        view=request.view,
        space=request.space,
        status=(
            FindViewPersistenceCandidatesStatus.COMPLETED
            if entities
            else FindViewPersistenceCandidatesStatus.FAILED
        ),
        candidates=candidates,
        log_id=log_id,
    )


async def find_view_persistence_candidates(
    context: CommandContext,
    request: FindViewPersistenceCandidatesRequest,
) -> FindViewPersistenceCandidatesResult:
    """
    Analyzes one view and returns every entity at the requested score.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewPersistenceCandidatesRequest): View and score to
            analyze.

    Returns:
        FindViewPersistenceCandidatesResult: Matching persistence candidates.

    Raises:
        CommandCancelledError: If view analysis is cancelled.
    """

    return await execute_command(
        context=context,
        command=FIND_PERSISTENCE_CANDIDATES_COMMAND_NAME,
        request=request,
        operation=_find_view_persistence_candidates,
        result_phase=lambda result: _result_phase(result.status),
    )


def _persistence_candidate_outcome(
    result: FindViewPersistenceCandidatesResult,
) -> BatchItemFinalStatus:
    """
    Classifies one persistence-candidate result for batch accounting.

    Args:
        result (FindViewPersistenceCandidatesResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Normalized final status.
    """
    if result.status is FindViewPersistenceCandidatesStatus.COMPLETED:
        return BatchItemFinalStatus.SUCCEEDED
    if result.status is FindViewPersistenceCandidatesStatus.TIMED_OUT:
        return BatchItemFinalStatus.TIMED_OUT
    return BatchItemFinalStatus.FAILED


async def _find_view_persistence_candidates_batch(
    execution: BatchExecution,
    request: FindViewPersistenceCandidatesBatchRequest,
) -> FindViewPersistenceCandidatesBatchResult:
    """
    Discovers views when needed and analyzes them as a bounded batch.

    Args:
        execution (BatchExecution): Runtime state of the batch execution.
        request (FindViewPersistenceCandidatesBatchRequest): Views and batch
            options to use.

    Returns:
        FindViewPersistenceCandidatesBatchResult: Ordered candidate results
            and summary.
    """
    requests = request.requests
    if requests is None:
        views = await execution.context.client.views.get_all_views()
        requests = tuple(
            FindViewPersistenceCandidatesRequest(
                view=view["name"],
                space=view["space_name"],
                candidate_score=request.candidate_score,
                timeout_seconds=request.timeout_seconds,
            )
            for view in views
        )
    results = await execution.execute_items(
        requests,
        _find_view_persistence_candidates,
        max_concurrency=request.max_concurrency,
        classify=_persistence_candidate_outcome,
    )
    return FindViewPersistenceCandidatesBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def find_view_persistence_candidates_batch(
    context: CommandContext,
    request: FindViewPersistenceCandidatesBatchRequest,
) -> FindViewPersistenceCandidatesBatchResult:
    """
    Analyzes views concurrently and retains input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewPersistenceCandidatesBatchRequest): Views and batch
            options to use.

    Returns:
        FindViewPersistenceCandidatesBatchResult: Ordered candidate results
            and their summary.

    Raises:
        CommandCancelledError: If view analysis is cancelled.
    """

    return await execute_batch(
        context=context,
        command=FIND_PERSISTENCE_CANDIDATES_BATCH_COMMAND_NAME,
        request=request,
        operation=_find_view_persistence_candidates_batch,
        total_items=(
            len(request.requests) if request.requests is not None else None
        ),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


async def _find_view_attribute_matches(
    context: CommandContext,
    request: FindViewAttributeMatchesRequest,
) -> FindViewAttributeMatchesResult:
    """
    Finds attributes containing the requested substring in one view.

    Args:
        context (CommandContext): Authenticated client used to list attributes.
        request (FindViewAttributeMatchesRequest): View and search options.

    Returns:
        FindViewAttributeMatchesResult: Matching attribute result.
    """
    attributes = await context.client.views.get_view_attributes(
        view_id=request.view_id,
        view_name=request.view,
        space=request.space,
    )
    needle = (
        request.substring
        if request.case_sensitive
        else request.substring.casefold()
    )
    matches = tuple(
        attribute
        for attribute in attributes
        if needle
        in (attribute if request.case_sensitive else attribute.casefold())
    )
    return FindViewAttributeMatchesResult(
        view=request.view,
        space=request.space,
        business_name=request.business_name,
        status=(
            FindViewAttributeMatchesStatus.COMPLETED
            if attributes
            else FindViewAttributeMatchesStatus.FAILED
        ),
        attributes=matches,
    )


async def find_view_attribute_matches(
    context: CommandContext,
    request: FindViewAttributeMatchesRequest,
) -> FindViewAttributeMatchesResult:
    """
    Returns all attributes containing a requested substring.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewAttributeMatchesRequest): View and substring to
            search for.

    Returns:
        FindViewAttributeMatchesResult: Matching view attributes.
    """

    return await execute_command(
        context=context,
        command=FIND_ATTRIBUTE_MATCHES_COMMAND_NAME,
        request=request,
        operation=_find_view_attribute_matches,
    )


def _attribute_matches_outcome(
    result: FindViewAttributeMatchesResult,
) -> BatchItemFinalStatus:
    """
    Classifies one attribute-match result for batch accounting.

    Args:
        result (FindViewAttributeMatchesResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Normalized final status.
    """
    if result.status is FindViewAttributeMatchesStatus.COMPLETED:
        return BatchItemFinalStatus.SUCCEEDED
    return BatchItemFinalStatus.FAILED


async def _find_view_attribute_matches_batch(
    execution: BatchExecution,
    request: FindViewAttributeMatchesBatchRequest,
) -> FindViewAttributeMatchesBatchResult:
    """
    Discovers views when needed and searches them as a bounded batch.

    Args:
        execution (BatchExecution): Runtime state of the batch execution.
        request (FindViewAttributeMatchesBatchRequest): Search and batch
            options to use.

    Returns:
        FindViewAttributeMatchesBatchResult: Ordered attribute results and
            summary.
    """
    requests = request.requests
    if requests is None:
        views = await execution.context.client.views.get_all_views()
        requests = tuple(
            FindViewAttributeMatchesRequest(
                view_id=view["id"],
                view=view["name"],
                space=view["space_name"],
                business_name=view["business_name"],
                substring=request.substring,
                case_sensitive=request.case_sensitive,
            )
            for view in views
        )
    results = await execution.execute_items(
        requests,
        _find_view_attribute_matches,
        max_concurrency=request.max_concurrency,
        classify=_attribute_matches_outcome,
    )
    return FindViewAttributeMatchesBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def find_view_attribute_matches_batch(
    context: CommandContext,
    request: FindViewAttributeMatchesBatchRequest,
) -> FindViewAttributeMatchesBatchResult:
    """
    Finds attribute matches concurrently and retains input order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewAttributeMatchesBatchRequest): Search options and
            batch options to use.

    Returns:
        FindViewAttributeMatchesBatchResult: Ordered attribute results and
            their summary.
    """

    return await execute_batch(
        context=context,
        command=FIND_ATTRIBUTE_MATCHES_BATCH_COMMAND_NAME,
        request=request,
        operation=_find_view_attribute_matches_batch,
        total_items=(
            len(request.requests) if request.requests is not None else None
        ),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


async def _create_view_partitioning(
    context: CommandContext,
    request: CreateViewPartitioningRequest,
) -> CreateViewPartitioningResult:
    """
    Creates the requested yearly partition range for one view.

    Args:
        context (CommandContext): Authenticated client used for creation.
        request (CreateViewPartitioningRequest): View and partition range.

    Returns:
        CreateViewPartitioningResult: Partition-creation outcome.
    """
    outcome = await context.client.views.create_partitioning(
        view=request.view,
        space=request.space,
        attribute=request.attribute,
        partitions=[
            str(year) for year in range(request.start_year, request.end_year)
        ],
        overwrite_existing=request.overwrite_existing,
    )
    status = (
        CreateViewPartitioningStatus.ALREADY_EXISTS
        if outcome == "exists"
        else CreateViewPartitioningStatus(outcome)
    )
    return CreateViewPartitioningResult(
        view=request.view,
        space=request.space,
        status=status,
    )


async def create_view_partitioning(
    context: CommandContext,
    request: CreateViewPartitioningRequest,
) -> CreateViewPartitioningResult:
    """
    Creates yearly range partitions for one persisted view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (CreateViewPartitioningRequest): View and partition range to
            create.

    Returns:
        CreateViewPartitioningResult: The resulting partition status.
    """

    return await execute_command(
        context=context,
        command=CREATE_PARTITIONING_COMMAND_NAME,
        request=request,
        operation=_create_view_partitioning,
        result_phase=lambda result: _result_phase(result.status),
    )


def _create_partitioning_outcome(
    result: CreateViewPartitioningResult,
) -> BatchItemFinalStatus:
    """
    Classifies one partition-creation result for batch accounting.

    Args:
        result (CreateViewPartitioningResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Normalized final status.
    """
    if result.status is CreateViewPartitioningStatus.CREATED:
        return BatchItemFinalStatus.SUCCEEDED
    if result.status is CreateViewPartitioningStatus.ALREADY_EXISTS:
        return BatchItemFinalStatus.SKIPPED
    return BatchItemFinalStatus.FAILED


async def _create_view_partitioning_batch(
    execution: BatchExecution,
    request: CreateViewPartitioningBatchRequest,
) -> CreateViewPartitioningBatchResult:
    """
    Creates the requested partition ranges as a bounded batch.

    Args:
        execution (BatchExecution): Runtime state of the batch execution.
        request (CreateViewPartitioningBatchRequest): Partition requests and
            batch options to use.

    Returns:
        CreateViewPartitioningBatchResult: Ordered outcomes and summary.
    """
    results = await execution.execute_items(
        request.requests,
        _create_view_partitioning,
        max_concurrency=request.max_concurrency,
        classify=_create_partitioning_outcome,
    )
    return CreateViewPartitioningBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def create_view_partitioning_batch(
    context: CommandContext,
    request: CreateViewPartitioningBatchRequest,
) -> CreateViewPartitioningBatchResult:
    """
    Creates yearly partitions concurrently and retains input order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (CreateViewPartitioningBatchRequest): Partition requests and
            batch options to use.

    Returns:
        CreateViewPartitioningBatchResult: Ordered partition results and their
            summary.
    """
    return await execute_batch(
        context=context,
        command=CREATE_PARTITIONING_BATCH_COMMAND_NAME,
        request=request,
        operation=_create_view_partitioning_batch,
        total_items=len(request.requests),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


async def _delete_view_partitioning(
    context: CommandContext,
    request: DeleteViewPartitioningRequest,
) -> DeleteViewPartitioningResult:
    """
    Deletes partitioning from one view.

    Args:
        context (CommandContext): Authenticated client used for deletion.
        request (DeleteViewPartitioningRequest): View partitioning to delete.

    Returns:
        DeleteViewPartitioningResult: Partition-deletion outcome.
    """
    deleted = await context.client.views.delete_partitioning(
        request.view,
        request.space,
    )
    return DeleteViewPartitioningResult(
        view=request.view,
        space=request.space,
        status=(
            DeleteViewPartitioningStatus.DELETED
            if deleted
            else DeleteViewPartitioningStatus.FAILED
        ),
    )


async def delete_view_partitioning(
    context: CommandContext,
    request: DeleteViewPartitioningRequest,
) -> DeleteViewPartitioningResult:
    """
    Deletes the partitioning of one persisted view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (DeleteViewPartitioningRequest): View partitioning to delete.

    Returns:
        DeleteViewPartitioningResult: The resulting deletion status.
    """

    return await execute_command(
        context=context,
        command=DELETE_PARTITIONING_COMMAND_NAME,
        request=request,
        operation=_delete_view_partitioning,
        result_phase=lambda result: _result_phase(result.status),
    )


def _delete_partitioning_outcome(
    result: DeleteViewPartitioningResult,
) -> BatchItemFinalStatus:
    """
    Classifies one partition-deletion result for batch accounting.

    Args:
        result (DeleteViewPartitioningResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Normalized final status.
    """
    if result.status is DeleteViewPartitioningStatus.DELETED:
        return BatchItemFinalStatus.SUCCEEDED
    return BatchItemFinalStatus.FAILED


async def _delete_view_partitioning_batch(
    execution: BatchExecution,
    request: DeleteViewPartitioningBatchRequest,
) -> DeleteViewPartitioningBatchResult:
    """
    Deletes the requested partitioning as a bounded batch.

    Args:
        execution (BatchExecution): Runtime state of the batch execution.
        request (DeleteViewPartitioningBatchRequest): Partition requests and
            batch options to use.

    Returns:
        DeleteViewPartitioningBatchResult: Ordered outcomes and summary.
    """
    results = await execution.execute_items(
        request.requests,
        _delete_view_partitioning,
        max_concurrency=request.max_concurrency,
        classify=_delete_partitioning_outcome,
    )
    return DeleteViewPartitioningBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def delete_view_partitioning_batch(
    context: CommandContext,
    request: DeleteViewPartitioningBatchRequest,
) -> DeleteViewPartitioningBatchResult:
    """
    Deletes partitioning concurrently and retains input order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (DeleteViewPartitioningBatchRequest): Partition requests and
            batch options to use.

    Returns:
        DeleteViewPartitioningBatchResult: Ordered deletion results and their
            summary.
    """
    return await execute_batch(
        context=context,
        command=DELETE_PARTITIONING_BATCH_COMMAND_NAME,
        request=request,
        operation=_delete_view_partitioning_batch,
        total_items=len(request.requests),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


async def _persist_view(
    context: CommandContext,
    request: PersistViewRequest,
) -> PersistViewResult:
    """
    Persists one view and normalizes the API outcome.

    Args:
        context (CommandContext): Authenticated client used for persistence.
        request (PersistViewRequest): View and persistence options.

    Returns:
        PersistViewResult: Normalized persistence outcome.

    Raises:
        CommandCancelledError: If view persistence is cancelled.
    """
    try:
        success, details = await context.client.views.persist_view(
            request.view,
            request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except ViewPersistenceTimeout as error:
        return PersistViewResult(
            view=request.view,
            space=request.space,
            status=PersistViewStatus.TIMED_OUT,
            log_id=_log_id(error.log_id),
        )
    except ViewPersistenceCancelled as error:
        raise CommandCancelledError(
            str(error),
            log_id=_log_id(error.log_id),
        ) from None

    status: PersistViewStatus
    if success:
        status = PersistViewStatus.COMPLETED
    elif details:
        status = PersistViewStatus.FAILED
    else:
        status = PersistViewStatus.START_FAILED

    return PersistViewResult(
        view=request.view,
        space=request.space,
        status=status,
        sap_status=_sap_status(details),
        log_id=_log_id(details.get("logId")),
        runtime_seconds=_get_runtime_seconds(details),
    )


async def persist_view(
    context: CommandContext,
    request: PersistViewRequest,
) -> PersistViewResult:
    """
    Persists one view and waits for its terminal status.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (PersistViewRequest): View and persistence options to use.

    Returns:
        PersistViewResult: The persistence status and operation details.

    Raises:
        CommandCancelledError: If view persistence is cancelled.
    """

    return await execute_command(
        context=context,
        command=PERSIST_COMMAND_NAME,
        request=request,
        operation=_persist_view,
        result_phase=lambda result: _result_phase(result.status),
    )


def _persist_outcome(result: PersistViewResult) -> BatchItemFinalStatus:
    """
    Classifies one persistence result for batch accounting.

    Args:
        result (PersistViewResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Normalized final status.
    """
    if result.status is PersistViewStatus.COMPLETED:
        return BatchItemFinalStatus.SUCCEEDED
    if result.status is PersistViewStatus.TIMED_OUT:
        return BatchItemFinalStatus.TIMED_OUT
    return BatchItemFinalStatus.FAILED


async def _persist_view_batch(
    execution: BatchExecution,
    request: PersistViewBatchRequest,
) -> PersistViewBatchResult:
    """
    Persists the requested views as a bounded batch.

    Args:
        execution (BatchExecution): Runtime state of the batch execution.
        request (PersistViewBatchRequest): Persistence requests and batch
            options to use.

    Returns:
        PersistViewBatchResult: Ordered outcomes and summary.
    """
    results = await execution.execute_items(
        request.requests,
        _persist_view,
        max_concurrency=request.max_concurrency,
        classify=_persist_outcome,
    )
    return PersistViewBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def persist_view_batch(
    context: CommandContext,
    request: PersistViewBatchRequest,
) -> PersistViewBatchResult:
    """
    Persists views concurrently and retains input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (PersistViewBatchRequest): Persistence requests and batch
            options to use.

    Returns:
        PersistViewBatchResult: Ordered persistence results and their summary.

    Raises:
        CommandCancelledError: If a view persistence operation is cancelled.
    """
    return await execute_batch(
        context=context,
        command=PERSIST_BATCH_COMMAND_NAME,
        request=request,
        operation=_persist_view_batch,
        total_items=len(request.requests),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


async def _unpersist_view(
    context: CommandContext,
    request: UnpersistViewRequest,
) -> UnpersistViewResult:
    """
    Removes one view's persisted data and normalizes the API outcome.

    Args:
        context (CommandContext): Authenticated client used for unpersistence.
        request (UnpersistViewRequest): View and unpersistence options.

    Returns:
        UnpersistViewResult: Normalized unpersistence outcome.

    Raises:
        CommandCancelledError: If view unpersistence is cancelled.
    """
    try:
        success, details = await context.client.views.unpersist_view(
            request.view,
            request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except ViewPersistenceTimeout as error:
        return UnpersistViewResult(
            view=request.view,
            space=request.space,
            status=UnpersistViewStatus.TIMED_OUT,
            log_id=_log_id(error.log_id),
        )
    except ViewPersistenceCancelled as error:
        raise CommandCancelledError(
            str(error),
            log_id=_log_id(error.log_id),
        ) from None

    status: UnpersistViewStatus
    if success and not details:
        status = UnpersistViewStatus.ALREADY_ABSENT
    elif success:
        status = UnpersistViewStatus.COMPLETED
    elif details:
        status = UnpersistViewStatus.FAILED
    else:
        status = UnpersistViewStatus.START_FAILED

    return UnpersistViewResult(
        view=request.view,
        space=request.space,
        status=status,
        sap_status=_sap_status(details),
        log_id=_log_id(details.get("logId")),
        runtime_seconds=_get_runtime_seconds(details),
    )


async def unpersist_view(
    context: CommandContext,
    request: UnpersistViewRequest,
) -> UnpersistViewResult:
    """
    Removes persisted data for one view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnpersistViewRequest): View and unpersistence options to use.

    Returns:
        UnpersistViewResult: The unpersistence status and operation details.

    Raises:
        CommandCancelledError: If view unpersistence is cancelled.
    """

    return await execute_command(
        context=context,
        command=UNPERSIST_COMMAND_NAME,
        request=request,
        operation=_unpersist_view,
        result_phase=lambda result: _result_phase(result.status),
    )


def _unpersist_outcome(result: UnpersistViewResult) -> BatchItemFinalStatus:
    """
    Classifies one unpersistence result for batch accounting.

    Args:
        result (UnpersistViewResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Normalized final status.
    """
    if result.status is UnpersistViewStatus.COMPLETED:
        return BatchItemFinalStatus.SUCCEEDED
    if result.status is UnpersistViewStatus.ALREADY_ABSENT:
        return BatchItemFinalStatus.SKIPPED
    if result.status is UnpersistViewStatus.TIMED_OUT:
        return BatchItemFinalStatus.TIMED_OUT
    return BatchItemFinalStatus.FAILED


async def _unpersist_view_batch(
    execution: BatchExecution,
    request: UnpersistViewBatchRequest,
) -> UnpersistViewBatchResult:
    """
    Unpersists the requested views as a bounded batch.

    Args:
        execution (BatchExecution): Runtime state of the batch execution.
        request (UnpersistViewBatchRequest): Unpersistence requests and batch
            options to use.

    Returns:
        UnpersistViewBatchResult: Ordered outcomes and summary.
    """
    results = await execution.execute_items(
        request.requests,
        _unpersist_view,
        max_concurrency=request.max_concurrency,
        classify=_unpersist_outcome,
    )
    return UnpersistViewBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def unpersist_view_batch(
    context: CommandContext,
    request: UnpersistViewBatchRequest,
) -> UnpersistViewBatchResult:
    """
    Unpersists views concurrently and retains input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnpersistViewBatchRequest): Unpersistence requests and batch
            options to use.

    Returns:
        UnpersistViewBatchResult: Ordered unpersistence results and their
            summary.

    Raises:
        CommandCancelledError: If a view unpersistence operation is cancelled.
    """
    return await execute_batch(
        context=context,
        command=UNPERSIST_BATCH_COMMAND_NAME,
        request=request,
        operation=_unpersist_view_batch,
        total_items=len(request.requests),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


async def _lock_view_partitions(
    context: CommandContext,
    request: LockViewPartitionsRequest,
) -> LockViewPartitionsResult:
    """
    Locks partitions through the requested year for one view.

    Args:
        context (CommandContext): Authenticated client used for locking.
        request (LockViewPartitionsRequest): View and year to use.

    Returns:
        LockViewPartitionsResult: Partition-lock outcome.

    Raises:
        RuntimeError: If the API returns an unexpected lock outcome.
    """
    outcome = await context.client.views.lock_partitions(
        view=request.view,
        space=request.space,
        until_year=request.until_year,
    )
    try:
        status = LockViewPartitionsStatus(outcome)
    except ValueError:
        raise RuntimeError(f"Unexpected lock outcome: {outcome}") from None
    return LockViewPartitionsResult(
        view=request.view,
        space=request.space,
        status=status,
    )


async def lock_view_partitions(
    context: CommandContext,
    request: LockViewPartitionsRequest,
) -> LockViewPartitionsResult:
    """
    Locks partitions through a requested year for one view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (LockViewPartitionsRequest): View and year through which to
            lock partitions.

    Returns:
        LockViewPartitionsResult: The resulting lock status.

    Raises:
        RuntimeError: If the API returns an unexpected lock outcome.
    """

    return await execute_command(
        context=context,
        command=LOCK_PARTITIONS_COMMAND_NAME,
        request=request,
        operation=_lock_view_partitions,
        result_phase=lambda result: _result_phase(result.status),
    )


def _lock_partitions_outcome(
    result: LockViewPartitionsResult,
) -> BatchItemFinalStatus:
    """
    Classifies one partition-lock result for batch accounting.

    Args:
        result (LockViewPartitionsResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Normalized final status.
    """
    if result.status is LockViewPartitionsStatus.LOCKED:
        return BatchItemFinalStatus.SUCCEEDED
    if result.status is LockViewPartitionsStatus.NO_PARTITIONS:
        return BatchItemFinalStatus.SKIPPED
    return BatchItemFinalStatus.FAILED


async def _lock_view_partitions_batch(
    execution: BatchExecution,
    request: LockViewPartitionsBatchRequest,
) -> LockViewPartitionsBatchResult:
    """
    Locks the requested view partitions as a bounded batch.

    Args:
        execution (BatchExecution): Runtime state of the batch execution.
        request (LockViewPartitionsBatchRequest): Lock requests and batch
            options to use.

    Returns:
        LockViewPartitionsBatchResult: Ordered outcomes and summary.
    """
    results = await execution.execute_items(
        request.requests,
        _lock_view_partitions,
        max_concurrency=request.max_concurrency,
        classify=_lock_partitions_outcome,
    )
    return LockViewPartitionsBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def lock_view_partitions_batch(
    context: CommandContext,
    request: LockViewPartitionsBatchRequest,
) -> LockViewPartitionsBatchResult:
    """
    Locks partitions concurrently and retains input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (LockViewPartitionsBatchRequest): Lock requests and batch
            options to use.

    Returns:
        LockViewPartitionsBatchResult: Ordered lock results and their summary.

    Raises:
        RuntimeError: If the API returns an unexpected lock outcome.
    """
    return await execute_batch(
        context=context,
        command=LOCK_PARTITIONS_BATCH_COMMAND_NAME,
        request=request,
        operation=_lock_view_partitions_batch,
        total_items=len(request.requests),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


async def _unlock_view_partitions(
    context: CommandContext,
    request: UnlockViewPartitionsRequest,
) -> UnlockViewPartitionsResult:
    """
    Unlocks every partition of one view.

    Args:
        context (CommandContext): Authenticated client used for unlocking.
        request (UnlockViewPartitionsRequest): View whose partitions are
            unlocked.

    Returns:
        UnlockViewPartitionsResult: Partition-unlock outcome.

    Raises:
        RuntimeError: If the API returns an unexpected unlock outcome.
    """
    outcome = await context.client.views.unlock_partitions(
        request.view,
        request.space,
    )
    try:
        status = UnlockViewPartitionsStatus(outcome)
    except ValueError:
        raise RuntimeError(f"Unexpected unlock outcome: {outcome}") from None
    return UnlockViewPartitionsResult(
        view=request.view,
        space=request.space,
        status=status,
    )


async def unlock_view_partitions(
    context: CommandContext,
    request: UnlockViewPartitionsRequest,
) -> UnlockViewPartitionsResult:
    """
    Unlocks every partition of one view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnlockViewPartitionsRequest): View whose partitions to
            unlock.

    Returns:
        UnlockViewPartitionsResult: The resulting unlock status.

    Raises:
        RuntimeError: If the API returns an unexpected unlock outcome.
    """

    return await execute_command(
        context=context,
        command=UNLOCK_PARTITIONS_COMMAND_NAME,
        request=request,
        operation=_unlock_view_partitions,
        result_phase=lambda result: _result_phase(result.status),
    )


def _unlock_partitions_outcome(
    result: UnlockViewPartitionsResult,
) -> BatchItemFinalStatus:
    """
    Classifies one partition-unlock result for batch accounting.

    Args:
        result (UnlockViewPartitionsResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Normalized final status.
    """
    if result.status is UnlockViewPartitionsStatus.UNLOCKED:
        return BatchItemFinalStatus.SUCCEEDED
    if result.status is UnlockViewPartitionsStatus.NO_PARTITIONS:
        return BatchItemFinalStatus.SKIPPED
    return BatchItemFinalStatus.FAILED


async def _unlock_view_partitions_batch(
    execution: BatchExecution,
    request: UnlockViewPartitionsBatchRequest,
) -> UnlockViewPartitionsBatchResult:
    """
    Unlocks the requested view partitions as a bounded batch.

    Args:
        execution (BatchExecution): Runtime state of the batch execution.
        request (UnlockViewPartitionsBatchRequest): Unlock requests and batch
            options to use.

    Returns:
        UnlockViewPartitionsBatchResult: Ordered outcomes and summary.
    """
    results = await execution.execute_items(
        request.requests,
        _unlock_view_partitions,
        max_concurrency=request.max_concurrency,
        classify=_unlock_partitions_outcome,
    )
    return UnlockViewPartitionsBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def unlock_view_partitions_batch(
    context: CommandContext,
    request: UnlockViewPartitionsBatchRequest,
) -> UnlockViewPartitionsBatchResult:
    """
    Unlocks partitions concurrently and retains input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnlockViewPartitionsBatchRequest): Unlock requests and batch
            options to use.

    Returns:
        UnlockViewPartitionsBatchResult: Ordered unlock results and their
            summary.

    Raises:
        RuntimeError: If the API returns an unexpected unlock outcome.
    """
    return await execute_batch(
        context=context,
        command=UNLOCK_PARTITIONS_BATCH_COMMAND_NAME,
        request=request,
        operation=_unlock_view_partitions_batch,
        total_items=len(request.requests),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


VIEWS_FIND_PERSISTENCE_CANDIDATES_COMMAND = CommandDefinition(
    name=FIND_PERSISTENCE_CANDIDATES_COMMAND_NAME,
    request_type=FindViewPersistenceCandidatesRequest,
    result_type=FindViewPersistenceCandidatesResult,
    handler=find_view_persistence_candidates,
    description="Find persistence candidates for one analyzed view.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=True,
    destructive=False,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_FIND_PERSISTENCE_CANDIDATES_BATCH_COMMAND = CommandDefinition(
    name=FIND_PERSISTENCE_CANDIDATES_BATCH_COMMAND_NAME,
    request_type=FindViewPersistenceCandidatesBatchRequest,
    result_type=FindViewPersistenceCandidatesBatchResult,
    handler=find_view_persistence_candidates_batch,
    description="Find persistence candidates with bounded concurrency.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=True,
    destructive=False,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_FIND_ATTRIBUTE_MATCHES_COMMAND = CommandDefinition(
    name=FIND_ATTRIBUTE_MATCHES_COMMAND_NAME,
    request_type=FindViewAttributeMatchesRequest,
    result_type=FindViewAttributeMatchesResult,
    handler=find_view_attribute_matches,
    description="Find matching attributes in one view.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=True,
    destructive=False,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_FIND_ATTRIBUTE_MATCHES_BATCH_COMMAND = CommandDefinition(
    name=FIND_ATTRIBUTE_MATCHES_BATCH_COMMAND_NAME,
    request_type=FindViewAttributeMatchesBatchRequest,
    result_type=FindViewAttributeMatchesBatchResult,
    handler=find_view_attribute_matches_batch,
    description="Find matching attributes with bounded concurrency.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=True,
    destructive=False,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_CREATE_PARTITIONING_COMMAND = CommandDefinition(
    name=CREATE_PARTITIONING_COMMAND_NAME,
    request_type=CreateViewPartitioningRequest,
    result_type=CreateViewPartitioningResult,
    handler=create_view_partitioning,
    description="Create yearly range partitions for one view.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_CREATE_PARTITIONING_BATCH_COMMAND = CommandDefinition(
    name=CREATE_PARTITIONING_BATCH_COMMAND_NAME,
    request_type=CreateViewPartitioningBatchRequest,
    result_type=CreateViewPartitioningBatchResult,
    handler=create_view_partitioning_batch,
    description="Create yearly partitions with bounded concurrency.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_DELETE_PARTITIONING_COMMAND = CommandDefinition(
    name=DELETE_PARTITIONING_COMMAND_NAME,
    request_type=DeleteViewPartitioningRequest,
    result_type=DeleteViewPartitioningResult,
    handler=delete_view_partitioning,
    description="Delete partitioning for one view.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_DELETE_PARTITIONING_BATCH_COMMAND = CommandDefinition(
    name=DELETE_PARTITIONING_BATCH_COMMAND_NAME,
    request_type=DeleteViewPartitioningBatchRequest,
    result_type=DeleteViewPartitioningBatchResult,
    handler=delete_view_partitioning_batch,
    description="Delete partitioning with bounded concurrency.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_PERSIST_COMMAND = CommandDefinition(
    name=PERSIST_COMMAND_NAME,
    request_type=PersistViewRequest,
    result_type=PersistViewResult,
    handler=persist_view,
    description="Persist one view and await its result.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=False,
    expose_to_mcp=False,
)

VIEWS_PERSIST_BATCH_COMMAND = CommandDefinition(
    name=PERSIST_BATCH_COMMAND_NAME,
    request_type=PersistViewBatchRequest,
    result_type=PersistViewBatchResult,
    handler=persist_view_batch,
    description="Persist views with bounded concurrency.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=False,
    expose_to_mcp=False,
)

VIEWS_UNPERSIST_COMMAND = CommandDefinition(
    name=UNPERSIST_COMMAND_NAME,
    request_type=UnpersistViewRequest,
    result_type=UnpersistViewResult,
    handler=unpersist_view,
    description="Remove persisted data for one view.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_UNPERSIST_BATCH_COMMAND = CommandDefinition(
    name=UNPERSIST_BATCH_COMMAND_NAME,
    request_type=UnpersistViewBatchRequest,
    result_type=UnpersistViewBatchResult,
    handler=unpersist_view_batch,
    description="Remove persisted data with bounded concurrency.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_LOCK_PARTITIONS_COMMAND = CommandDefinition(
    name=LOCK_PARTITIONS_COMMAND_NAME,
    request_type=LockViewPartitionsRequest,
    result_type=LockViewPartitionsResult,
    handler=lock_view_partitions,
    description="Lock view partitions through a requested year.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_LOCK_PARTITIONS_BATCH_COMMAND = CommandDefinition(
    name=LOCK_PARTITIONS_BATCH_COMMAND_NAME,
    request_type=LockViewPartitionsBatchRequest,
    result_type=LockViewPartitionsBatchResult,
    handler=lock_view_partitions_batch,
    description="Lock view partitions with bounded concurrency.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_UNLOCK_PARTITIONS_COMMAND = CommandDefinition(
    name=UNLOCK_PARTITIONS_COMMAND_NAME,
    request_type=UnlockViewPartitionsRequest,
    result_type=UnlockViewPartitionsResult,
    handler=unlock_view_partitions,
    description="Unlock all partitions of one view.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_UNLOCK_PARTITIONS_BATCH_COMMAND = CommandDefinition(
    name=UNLOCK_PARTITIONS_BATCH_COMMAND_NAME,
    request_type=UnlockViewPartitionsBatchRequest,
    result_type=UnlockViewPartitionsBatchResult,
    handler=unlock_view_partitions_batch,
    description="Unlock view partitions with bounded concurrency.",
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

VIEWS_COMMAND_DEFINITIONS: tuple[CommandDefinition[Any, Any], ...] = (
    VIEWS_FIND_PERSISTENCE_CANDIDATES_COMMAND,
    VIEWS_FIND_PERSISTENCE_CANDIDATES_BATCH_COMMAND,
    VIEWS_FIND_ATTRIBUTE_MATCHES_COMMAND,
    VIEWS_FIND_ATTRIBUTE_MATCHES_BATCH_COMMAND,
    VIEWS_CREATE_PARTITIONING_COMMAND,
    VIEWS_CREATE_PARTITIONING_BATCH_COMMAND,
    VIEWS_DELETE_PARTITIONING_COMMAND,
    VIEWS_DELETE_PARTITIONING_BATCH_COMMAND,
    VIEWS_PERSIST_COMMAND,
    VIEWS_PERSIST_BATCH_COMMAND,
    VIEWS_UNPERSIST_COMMAND,
    VIEWS_UNPERSIST_BATCH_COMMAND,
    VIEWS_LOCK_PARTITIONS_COMMAND,
    VIEWS_LOCK_PARTITIONS_BATCH_COMMAND,
    VIEWS_UNLOCK_PARTITIONS_COMMAND,
    VIEWS_UNLOCK_PARTITIONS_BATCH_COMMAND,
)
