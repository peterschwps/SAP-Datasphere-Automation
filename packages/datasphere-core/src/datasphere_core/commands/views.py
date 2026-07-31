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
    request: FindViewPersistenceCandidatesRequest,
) -> ViewPersistenceCandidate:
    """
    Converts one analyzer entity into a persistence candidate model.

    Args:
        entity (dict[str, Any]): Analyzer entity details.
        request (FindViewPersistenceCandidatesRequest): Request supplying the
                                                        fallback view, space,
                                                        and score values.

    Returns:
        ViewPersistenceCandidate: Normalized candidate details.
    """
    return ViewPersistenceCandidate(
        view=entity.get("entity") or request.view,
        space=entity.get("space") or request.space,
        score=request.candidate_score,
        business_name=entity.get("businessName"),
        is_persisted=entity.get("isPersisted"),
    )


@command(FIND_PERSISTENCE_CANDIDATES_COMMAND_NAME)
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

    Raises:
        CommandCancelledError: If the view analysis was cancelled after it had
                               already started remotely.

    Returns:
        FindViewPersistenceCandidatesResult: Matching persistence candidates.
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

    # Keep every entity that reached the requested candidate score
    entities = analysis["entityStats"]
    candidates = tuple(
        _candidate_from_entity(entity, request)
        for entity in entities
        if entity.get("persistencyCandidateScore") == request.candidate_score
    )  # TODO: adjust check to greater than or equal

    # Fetch logId
    log_id = to_text(analysis.get("logId"))

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


@batch_command(FIND_PERSISTENCE_CANDIDATES_BATCH_COMMAND_NAME)
async def find_view_persistence_candidates_batch(
    context: CommandContext,
    request: FindViewPersistenceCandidatesBatchRequest,
) -> FindViewPersistenceCandidatesBatchResult:
    """
    Analyzes views concurrently and retains the input result order. Discovers
    every view of the tenant if the request carries no explicit requests.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewPersistenceCandidatesBatchRequest): Views and batch
                                                             options to use.

    Raises:
        CommandCancelledError: If a view analysis was cancelled after it had
                               already started remotely.

    Returns:
        FindViewPersistenceCandidatesBatchResult: Ordered candidate results and
                                                  their summary.
    """
    requests = request.requests

    # Fetch all views to create mapping for the view analyzing
    if requests is None:
        views = await context.client.views.get_all_views()
        requests = tuple(
            FindViewPersistenceCandidatesRequest(
                view=view["name"],
                space=view["space_name"],
                candidate_score=request.candidate_score,
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
        request (FindViewAttributeMatchesRequest): View and substring to search
                                                   for.

    Returns:
        FindViewAttributeMatchesResult: Matching view attributes.
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
    Finds attribute matches concurrently and retains the input result order.
    Discovers every view of the tenant if the request carries no explicit
    requests.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (FindViewAttributeMatchesBatchRequest): Search options and
                                                        batch options to use.

    Returns:
        FindViewAttributeMatchesBatchResult: Ordered attribute results and
                                             their summary.
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
        request (CreateViewPartitioningRequest): View and partition range to
                                                 create.

    Returns:
        CreateViewPartitioningResult: The resulting partition status.
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
    Creates yearly partitions concurrently and retains the input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (CreateViewPartitioningBatchRequest): Partition requests and
                                                      batch options to use.

    Returns:
        CreateViewPartitioningBatchResult: Ordered partition results and their
                                           summary.
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
        request (DeleteViewPartitioningRequest): View partitioning to delete.

    Returns:
        DeleteViewPartitioningResult: The resulting deletion status.
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
    Deletes partitioning concurrently and retains the input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (DeleteViewPartitioningBatchRequest): Partition requests and
                                                      batch options to use.

    Returns:
        DeleteViewPartitioningBatchResult: Ordered deletion results and their
                                           summary.
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
        request (PersistViewRequest): View and persistence options to use.

    Raises:
        CommandCancelledError: If the persistence was cancelled after it had
                               already started remotely.

    Returns:
        PersistViewResult: The persistence status and operation details.
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

    return PersistViewResult(
        view=request.view,
        space=request.space,
        status=status,
        sap_status=to_text(details.get("status")),
        log_id=to_text(details.get("logId")),
        runtime_seconds=runtime_to_seconds(details),
    )


@batch_command(PERSIST_BATCH_COMMAND_NAME)
async def persist_view_batch(
    context: CommandContext,
    request: PersistViewBatchRequest,
) -> PersistViewBatchResult:
    """
    Persists views concurrently and retains the input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (PersistViewBatchRequest): Persistence requests and batch
                                           options to use.

    Raises:
        CommandCancelledError: If a persistence was cancelled after it had
                               already started remotely.

    Returns:
        PersistViewBatchResult: Ordered persistence results and their summary.
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
        request (UnpersistViewRequest): View and unpersistence options to use.

    Raises:
        CommandCancelledError: If the unpersistence was cancelled after it had
                               already started remotely.

    Returns:
        UnpersistViewResult: The unpersistence status and operation details.
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

    return UnpersistViewResult(
        view=request.view,
        space=request.space,
        status=status,
        sap_status=to_text(details.get("status")),
        log_id=to_text(details.get("logId")),
        runtime_seconds=runtime_to_seconds(details),
    )


@batch_command(UNPERSIST_BATCH_COMMAND_NAME)
async def unpersist_view_batch(
    context: CommandContext,
    request: UnpersistViewBatchRequest,
) -> UnpersistViewBatchResult:
    """
    Unpersists views concurrently and retains the input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnpersistViewBatchRequest): Unpersistence requests and batch
                                             options to use.

    Raises:
        CommandCancelledError: If an unpersistence was cancelled after it had
                               already started remotely.

    Returns:
        UnpersistViewBatchResult: Ordered unpersistence results and their
                                  summary.
    """
    results, summary = await run_batch(
        context=context,
        command=UNPERSIST_BATCH_COMMAND_NAME,
        items=request.requests,
        operation=unpersist_view,
        max_concurrency=request.max_concurrency,
    )
    return UnpersistViewBatchResult(results=results, summary=summary)


@command(LOCK_PARTITIONS_COMMAND_NAME)
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
    """
    outcome = await context.client.views.lock_partitions(
        view=request.view,
        space=request.space,
        until_year=request.until_year,
    )
    return LockViewPartitionsResult(
        view=request.view,
        space=request.space,
        status=LockViewPartitionsStatus(outcome),
    )


@batch_command(LOCK_PARTITIONS_BATCH_COMMAND_NAME)
async def lock_view_partitions_batch(
    context: CommandContext,
    request: LockViewPartitionsBatchRequest,
) -> LockViewPartitionsBatchResult:
    """
    Locks partitions concurrently and retains the input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (LockViewPartitionsBatchRequest): Lock requests and batch
                                                  options to use.

    Returns:
        LockViewPartitionsBatchResult: Ordered lock results and their summary.
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
        request (UnlockViewPartitionsRequest): View whose partitions to unlock.

    Returns:
        UnlockViewPartitionsResult: The resulting unlock status.
    """
    outcome = await context.client.views.unlock_partitions(
        view=request.view,
        space=request.space,
    )
    return UnlockViewPartitionsResult(
        view=request.view,
        space=request.space,
        status=UnlockViewPartitionsStatus(outcome),
    )


@batch_command(UNLOCK_PARTITIONS_BATCH_COMMAND_NAME)
async def unlock_view_partitions_batch(
    context: CommandContext,
    request: UnlockViewPartitionsBatchRequest,
) -> UnlockViewPartitionsBatchResult:
    """
    Unlocks partitions concurrently and retains the input result order.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (UnlockViewPartitionsBatchRequest): Unlock requests and batch
                                                    options to use.

    Returns:
        UnlockViewPartitionsBatchResult: Ordered unlock results and their
                                         summary.
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
