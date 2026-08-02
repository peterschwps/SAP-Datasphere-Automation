from collections.abc import Callable
from typing import Any

from datasphere_api import (
    ViewAnalysisCancelled,
    ViewAnalysisTimeout,
    ViewPersistenceCancelled,
    ViewPersistenceTimeout,
)

from datasphere_core.context import CommandContext
from datasphere_core.conversion import runtime_to_seconds, to_text
from datasphere_core.definitions import CommandDefinition
from datasphere_core.errors import CommandCancelledError
from datasphere_core.execution import batch_command, command, run_batch
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


def _candidate_from_entity(
    entity: dict[str, Any],
    score: int | float,
) -> ViewPersistenceCandidate:
    """
    Converts one analyzer entity into a persistence candidate model. An entity
    usually describes a view other than the analyzed one, so its name and space
    are read directly instead of falling back to the analyzed view.

    Args:
        entity (dict[str, Any]): Analyzer entity details.
        score (int | float): Candidate score the entity actually reached.

    Returns:
        ViewPersistenceCandidate: Normalized candidate details.
    """
    return ViewPersistenceCandidate(
        view=entity["entity"],
        space=entity["space"],
        score=score,
        business_name=entity.get("businessName"),
        is_persisted=entity.get("isPersisted"),
    )


@command(FIND_PERSISTENCE_CANDIDATES_COMMAND_NAME)
async def find_view_persistence_candidates(
    context: CommandContext,
    request: FindViewPersistenceCandidatesRequest,
) -> FindViewPersistenceCandidatesResult:
    """
    Analyzes one view and returns every entity that reached at least the
    requested candidate score.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewPersistenceCandidatesRequest): Input for the view
                                                        analysis.

    Raises:
        CommandCancelledError: If the view analysis was cancelled after it had
                               already started remotely.

    Returns:
        FindViewPersistenceCandidatesResult: Result of the view analysis.
    """
    # Run the view analyzer
    try:
        analysis = await context.client.views.analyze_view(
            view=request.view,
            space=request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except ViewAnalysisTimeout as error:
        return FindViewPersistenceCandidatesResult(
            view=request.view,
            space=request.space,
            status=FindViewPersistenceCandidatesStatus.TIMED_OUT,
            candidates=(),
            log_id=to_text(error.log_id),
        )
    except ViewAnalysisCancelled as error:
        log_id = to_text(error.log_id)
        raise CommandCancelledError(str(error), log_id=log_id) from None

    # Keep every entity that reached at least the requested candidate score
    entities = analysis["entityStats"]
    candidates: list[ViewPersistenceCandidate] = []
    for entity in entities:

        # An entity without a usable score is dropped instead of compared,
        # because comparing None would raise a TypeError
        score = entity.get("persistencyCandidateScore")
        if not isinstance(score, int | float):
            continue

        if score >= request.minimum_candidate_score:
            candidates.append(_candidate_from_entity(entity, score))

    # Fetch logId
    log_id = to_text(analysis["logId"])

    return FindViewPersistenceCandidatesResult(
        view=request.view,
        space=request.space,
        status=(
            FindViewPersistenceCandidatesStatus.COMPLETED
            if entities
            else FindViewPersistenceCandidatesStatus.FAILED
        ),
        candidates=tuple(candidates),
        log_id=log_id,
    )


@batch_command(FIND_PERSISTENCE_CANDIDATES_BATCH_COMMAND_NAME)
async def find_view_persistence_candidates_batch(
    context: CommandContext,
    request: FindViewPersistenceCandidatesBatchRequest,
) -> FindViewPersistenceCandidatesBatchResult:
    """
    Analyzes selected views with concurrency. Discovers every view of the
    tenant if the request carries no explicit requests.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewPersistenceCandidatesBatchRequest): Input for the view
                                                             analyses with
                                                             concurrency.

    Raises:
        CommandCancelledError: If a view analysis was cancelled after it had
                               already started remotely.

    Returns:
        FindViewPersistenceCandidatesBatchResult: Ordered results of the view
                                                  analyses.
    """
    requests = request.requests

    # Fetch all views to create mapping for the view analyzing
    if requests is None:
        views = await context.client.views.get_all_views()
        requests = tuple(
            FindViewPersistenceCandidatesRequest(
                view=view["name"],
                space=view["space_name"],
                minimum_candidate_score=request.minimum_candidate_score,
                timeout_seconds=request.timeout_seconds,
            )
            for view in views
        )

    # Start batch
    results, summary = await run_batch(
        context=context,
        command=FIND_PERSISTENCE_CANDIDATES_BATCH_COMMAND_NAME,
        items=requests,
        operation=find_view_persistence_candidates,
        max_concurrency=request.max_concurrency,
    )
    return FindViewPersistenceCandidatesBatchResult(
        results=results,
        summary=summary,
    )


@command(FIND_ATTRIBUTE_MATCHES_COMMAND_NAME)
async def find_view_attribute_matches(
    context: CommandContext,
    request: FindViewAttributeMatchesRequest,
) -> FindViewAttributeMatchesResult:
    """
    Returns all attributes of one view containing the requested substring.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewAttributeMatchesRequest): Input for the attribute
                                                   search.

    Returns:
        FindViewAttributeMatchesResult: Result of the attribute search.
    """
    # Fetch all attributes of the view
    attributes = await context.client.views.get_view_attributes(
        view_id=request.view_id,
        view_name=request.view,
        space=request.space,
    )

    # Check for matches in the attributes
    # Convert substring and attributes to lower case if not case-sensitive
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


@batch_command(FIND_ATTRIBUTE_MATCHES_BATCH_COMMAND_NAME)
async def find_view_attribute_matches_batch(
    context: CommandContext,
    request: FindViewAttributeMatchesBatchRequest,
) -> FindViewAttributeMatchesBatchResult:
    """
    Finds matching attributes in selected views with concurrency. Discovers
    every view of the tenant if the request carries no explicit requests.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewAttributeMatchesBatchRequest): Input for the attribute
                                                        searches with
                                                        concurrency.

    Returns:
        FindViewAttributeMatchesBatchResult: Ordered results of the attribute
                                             searches.
    """
    requests = request.requests
    if requests is None:
        views = await context.client.views.get_all_views()
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

    # Run batch
    results, summary = await run_batch(
        context=context,
        command=FIND_ATTRIBUTE_MATCHES_BATCH_COMMAND_NAME,
        items=requests,
        operation=find_view_attribute_matches,
        max_concurrency=request.max_concurrency,
    )
    return FindViewAttributeMatchesBatchResult(
        results=results,
        summary=summary,
    )


@command(CREATE_PARTITIONING_COMMAND_NAME)
async def create_view_partitioning(
    context: CommandContext,
    request: CreateViewPartitioningRequest,
) -> CreateViewPartitioningResult:
    """
    Creates yearly range partitions for one persisted view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (CreateViewPartitioningRequest): Input for the partition
                                                 creation.

    Returns:
        CreateViewPartitioningResult: Result of the partition creation.
    """
    # Create partitioning
    outcome = await context.client.views.create_partitioning(
        view=request.view,
        space=request.space,
        attribute=request.attribute,
        partitions=[
            str(year) for year in range(request.start_year, request.end_year)
        ],
        overwrite_existing=request.overwrite_existing,
    )

    # Check result
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


@batch_command(CREATE_PARTITIONING_BATCH_COMMAND_NAME)
async def create_view_partitioning_batch(
    context: CommandContext,
    request: CreateViewPartitioningBatchRequest,
) -> CreateViewPartitioningBatchResult:
    """
    Creates yearly range partitions for multiple views with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (CreateViewPartitioningBatchRequest): Input for the partition
                                                      creations with
                                                      concurrency.

    Returns:
        CreateViewPartitioningBatchResult: Ordered results of the partition
                                           creations.
    """
    results, summary = await run_batch(
        context=context,
        command=CREATE_PARTITIONING_BATCH_COMMAND_NAME,
        items=request.requests,
        operation=create_view_partitioning,
        max_concurrency=request.max_concurrency,
    )
    return CreateViewPartitioningBatchResult(results=results, summary=summary)


@command(DELETE_PARTITIONING_COMMAND_NAME)
async def delete_view_partitioning(
    context: CommandContext,
    request: DeleteViewPartitioningRequest,
) -> DeleteViewPartitioningResult:
    """
    Deletes the partitioning of one persisted view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (DeleteViewPartitioningRequest): Input for the partition
                                                 deletion.

    Returns:
        DeleteViewPartitioningResult: Result of the partition deletion.
    """
    deleted = await context.client.views.delete_partitioning(
        view=request.view,
        space=request.space,
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


@batch_command(DELETE_PARTITIONING_BATCH_COMMAND_NAME)
async def delete_view_partitioning_batch(
    context: CommandContext,
    request: DeleteViewPartitioningBatchRequest,
) -> DeleteViewPartitioningBatchResult:
    """
    Deletes the partitioning of multiple views with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (DeleteViewPartitioningBatchRequest): Input for the partition
                                                      deletions with
                                                      concurrency.

    Returns:
        DeleteViewPartitioningBatchResult: Ordered results of the partition
                                           deletions.
    """
    results, summary = await run_batch(
        context=context,
        command=DELETE_PARTITIONING_BATCH_COMMAND_NAME,
        items=request.requests,
        operation=delete_view_partitioning,
        max_concurrency=request.max_concurrency,
    )
    return DeleteViewPartitioningBatchResult(results=results, summary=summary)


@command(PERSIST_COMMAND_NAME)
async def persist_view(
    context: CommandContext,
    request: PersistViewRequest,
) -> PersistViewResult:
    """
    Persists one view and waits for its terminal status.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (PersistViewRequest): Input for the persistence run.

    Raises:
        CommandCancelledError: If the persistence was cancelled after it had
                               already started remotely.

    Returns:
        PersistViewResult: Result of the persistence run.
    """
    # Start persistence
    try:
        success, details = await context.client.views.persist_view(
            view=request.view,
            space=request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except ViewPersistenceTimeout as error:
        return PersistViewResult(
            view=request.view,
            space=request.space,
            status=PersistViewStatus.TIMED_OUT,
            log_id=to_text(error.log_id),
        )
    except ViewPersistenceCancelled as error:
        raise CommandCancelledError(
            str(error),
            log_id=to_text(error.log_id),
        ) from None

    # Check result
    status: PersistViewStatus
    if success:
        status = PersistViewStatus.COMPLETED
    elif details:
        status = PersistViewStatus.FAILED
    else:
        status = PersistViewStatus.START_FAILED

    # Datasphere returns an empty dict when the run never started, so
    # both keys are read defensively. A filled dict always carries them.
    return PersistViewResult(
        view=request.view,
        space=request.space,
        status=status,
        log_status=to_text(details.get("status")),
        log_id=to_text(details.get("logId")),
        runtime_seconds=runtime_to_seconds(details),
    )


@batch_command(PERSIST_BATCH_COMMAND_NAME)
async def persist_view_batch(
    context: CommandContext,
    request: PersistViewBatchRequest,
) -> PersistViewBatchResult:
    """
    Persists multiple views with concurrency and waits for their terminal
    status.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (PersistViewBatchRequest): Input for the persistence runs with
                                           concurrency.

    Raises:
        CommandCancelledError: If a persistence was cancelled after it had
                               already started remotely.

    Returns:
        PersistViewBatchResult: Ordered results of the persistence runs.
    """
    results, summary = await run_batch(
        context=context,
        command=PERSIST_BATCH_COMMAND_NAME,
        items=request.requests,
        operation=persist_view,
        max_concurrency=request.max_concurrency,
    )
    return PersistViewBatchResult(results=results, summary=summary)


@command(UNPERSIST_COMMAND_NAME)
async def unpersist_view(
    context: CommandContext,
    request: UnpersistViewRequest,
) -> UnpersistViewResult:
    """
    Removes the persisted data of one view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnpersistViewRequest): Input for the unpersistence run.

    Raises:
        CommandCancelledError: If the unpersistence was cancelled after it had
                               already started remotely.

    Returns:
        UnpersistViewResult: Result of the unpersistence run.
    """
    # Start removal of persistence
    try:
        success, details = await context.client.views.unpersist_view(
            view=request.view,
            space=request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except ViewPersistenceTimeout as error:
        return UnpersistViewResult(
            view=request.view,
            space=request.space,
            status=UnpersistViewStatus.TIMED_OUT,
            log_id=to_text(error.log_id),
        )
    except ViewPersistenceCancelled as error:
        raise CommandCancelledError(
            str(error),
            log_id=to_text(error.log_id),
        ) from None

    # Check result
    status: UnpersistViewStatus
    if success and not details:
        status = UnpersistViewStatus.ALREADY_ABSENT
    elif success:
        status = UnpersistViewStatus.COMPLETED
    elif details:
        status = UnpersistViewStatus.FAILED
    else:
        status = UnpersistViewStatus.START_FAILED

    # Datasphere returns an empty dict when the run never started, so
    # both keys are read defensively. A filled dict always carries them.
    return UnpersistViewResult(
        view=request.view,
        space=request.space,
        status=status,
        log_status=to_text(details.get("status")),
        log_id=to_text(details.get("logId")),
        runtime_seconds=runtime_to_seconds(details),
    )


@batch_command(UNPERSIST_BATCH_COMMAND_NAME)
async def unpersist_view_batch(
    context: CommandContext,
    request: UnpersistViewBatchRequest,
) -> UnpersistViewBatchResult:
    """
    Removes the persisted data of multiple views with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnpersistViewBatchRequest): Input for the unpersistence runs
                                             with concurrency.

    Raises:
        CommandCancelledError: If an unpersistence was cancelled after it had
                               already started remotely.

    Returns:
        UnpersistViewBatchResult: Ordered results of the unpersistence runs.
    """
    results, summary = await run_batch(
        context=context,
        command=UNPERSIST_BATCH_COMMAND_NAME,
        items=request.requests,
        operation=unpersist_view,
        max_concurrency=request.max_concurrency,
    )
    return UnpersistViewBatchResult(results=results, summary=summary)


# Fields the partitioning endpoint expects back when it is written
_PARTITIONING_FIELDS = (
    "remoteSourceName",
    "objectName",
    "numParallelPartitions",
    "ranges",
    "column",
    "columnType",
    "runtimeDataCalculation",
    "type",
)


async def _set_partition_lock(
    context: CommandContext,
    *,
    view: str,
    space: str,
    locked: Callable[[dict[str, Any]], bool],
    success_status: str,
) -> str:
    """
    Rewrites the lock flag of every partition of one view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.
        locked (Callable[[dict[str, Any]], bool]): Decides whether one
                                                   partition ends up locked.
        success_status (str): Status to report once the write was accepted.

    Returns:
        str: The requested status, 'no_partitions' or 'failed'.
    """
    # Read the current partitioning
    partitioning = await context.client.views.get_partitioning(view, space)
    if not partitioning["ranges"]:
        return "no_partitions"

    # Write back every field the endpoint expects, with the new lock flags
    payload = {field: partitioning[field] for field in _PARTITIONING_FIELDS}
    for partition in payload["ranges"]:
        partition["locked"] = locked(partition)

    accepted = await context.client.views.set_partitioning(
        view,
        space,
        payload,
    )
    return success_status if accepted else "failed"


@command(LOCK_PARTITIONS_COMMAND_NAME)
async def lock_view_partitions(
    context: CommandContext,
    request: LockViewPartitionsRequest,
) -> LockViewPartitionsResult:
    """
    Locks partitions through a requested year for one view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (LockViewPartitionsRequest): Input for the partition lock.

    Returns:
        LockViewPartitionsResult: Result of the partition lock.
    """
    status = await _set_partition_lock(
        context,
        view=request.view,
        space=request.space,
        locked=lambda partition: (
            int(partition["low"]["value"]) <= request.until_year
        ),
        success_status="locked",
    )
    return LockViewPartitionsResult(
        view=request.view,
        space=request.space,
        status=LockViewPartitionsStatus(status),
    )


@batch_command(LOCK_PARTITIONS_BATCH_COMMAND_NAME)
async def lock_view_partitions_batch(
    context: CommandContext,
    request: LockViewPartitionsBatchRequest,
) -> LockViewPartitionsBatchResult:
    """
    Locks partitions through a requested year for multiple views with
    concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (LockViewPartitionsBatchRequest): Input for the partition locks
                                                  with concurrency.

    Returns:
        LockViewPartitionsBatchResult: Ordered results of the partition locks.
    """
    results, summary = await run_batch(
        context=context,
        command=LOCK_PARTITIONS_BATCH_COMMAND_NAME,
        items=request.requests,
        operation=lock_view_partitions,
        max_concurrency=request.max_concurrency,
    )
    return LockViewPartitionsBatchResult(results=results, summary=summary)


@command(UNLOCK_PARTITIONS_COMMAND_NAME)
async def unlock_view_partitions(
    context: CommandContext,
    request: UnlockViewPartitionsRequest,
) -> UnlockViewPartitionsResult:
    """
    Unlocks every partition of one view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnlockViewPartitionsRequest): Input for the partition unlock.

    Returns:
        UnlockViewPartitionsResult: Result of the partition unlock.
    """
    status = await _set_partition_lock(
        context,
        view=request.view,
        space=request.space,
        locked=lambda partition: False,
        success_status="unlocked",
    )
    return UnlockViewPartitionsResult(
        view=request.view,
        space=request.space,
        status=UnlockViewPartitionsStatus(status),
    )


@batch_command(UNLOCK_PARTITIONS_BATCH_COMMAND_NAME)
async def unlock_view_partitions_batch(
    context: CommandContext,
    request: UnlockViewPartitionsBatchRequest,
) -> UnlockViewPartitionsBatchResult:
    """
    Unlocks every partition of multiple views with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnlockViewPartitionsBatchRequest): Input for the partition
                                                    unlocks with concurrency.

    Returns:
        UnlockViewPartitionsBatchResult: Ordered results of the partition
                                         unlocks.
    """
    results, summary = await run_batch(
        context=context,
        command=UNLOCK_PARTITIONS_BATCH_COMMAND_NAME,
        items=request.requests,
        operation=unlock_view_partitions,
        max_concurrency=request.max_concurrency,
    )
    return UnlockViewPartitionsBatchResult(results=results, summary=summary)


# Define all commands
VIEWS_FIND_PERSISTENCE_CANDIDATES_COMMAND = CommandDefinition(
    name=FIND_PERSISTENCE_CANDIDATES_COMMAND_NAME,
    request_type=FindViewPersistenceCandidatesRequest,
    result_type=FindViewPersistenceCandidatesResult,
    handler=find_view_persistence_candidates,
    description=(
        "Run the view analyzer for one view to find persistence candidates."
    ),
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
    description=(
        "Run the view analyzer for multiple views with bounded concurrency to "
        "find persistence candidates."
    ),
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
    description=(
        "Find matching attributes with a specific substring in one view."
    ),
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
    description=(
        "Find matching attributes with a specific substring in multiple views "
        "with bounded concurrency."
    ),
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
    description=(
        "Create yearly partitions for multiple views with bounded concurrency."
    ),
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
    description=(
        "Delete partitioning for multiple views with bounded concurrency."
    ),
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
    description=(
        "Persist multiple views with bounded concurrency and await their "
        "results."
    ),
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
    description=(
        "Remove persisted data for multiple views with bounded concurrency."
    ),
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
    description="Lock partitions through a requested year for one view.",
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
    description=(
        "Lock partitions through a requested year for multiple views "
        "with bounded concurrency."),
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
    description=(
        "Unlock all partitions of multiple views with bounded concurrency."
    ),
    default_timeout_seconds=DEFAULT_VIEW_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_VIEW_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=True,
    expose_to_mcp=False,
)

# Gather all commands (to import to registry)
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
