import asyncio
import logging
import time
from collections.abc import Callable
from json import JSONDecodeError
from typing import Any

import httpx

from datasphere_core.commands.repository import search_views
from datasphere_core.commands.shared.conversion import (
    runtime_to_seconds,
    to_text,
)
from datasphere_core.commands.shared.persistence import (
    run_persistence,
    run_persistence_removal,
)
from datasphere_core.commands.shared.task_logs import announce_runtime
from datasphere_core.errors import CommandCancelledError, CommandTimeoutError
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
from datasphere_core.runtime.context import CommandContext
from datasphere_core.runtime.definitions import CommandDefinition
from datasphere_core.runtime.execution import batch_command, command, run_batch
from datasphere_core.session.config import request_headers

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

logger = logging.getLogger(__name__)

# Partitioning endpoint of one persisted view
_PARTITIONING_URL = "/dwaas-core/partitioning/{space}/persistedViews/{view}"


async def _get_view_attributes(
    context: CommandContext,
    *,
    view_id: str,
    view_name: str,
    space: str,
) -> list[str]:
    """
    Loads the attribute names of one view from its design object details.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view_id (str): Repository ID of the view.
        view_name (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.

    Returns:
        list[str]: Attribute names, empty if the details cannot be read.
    """
    response = await context.session.get(
        url=f"/deepsea/repository/{space}/designObjects",
        params={
            "ids": view_id,
            "details": (
                "id,#repairedCsn,#ownerBusinessName,#creatorBusinessName,"
                "#repositoryPackage,@EnterpriseSearch.enabled,"
                "@remote.source,@DataWarehouse.external.schema,"
                "#objectPathIdentifier,#repositoryPackage,"
                "#repositoryValidationDate,hasPendingError,#isI18nEnabled"
            ),
            "kinds": (
                "entity,view,sap.dwc.ermodel,sap.dis.dataflow,"
                "sap.dwc.taskChain,sap.dwc.analyticModel,"
                "sap.dwc.dac,sap.repo.folder,sap.dis.replicationflow,"
                "sap.dis.transformationflow,sap.dwc.perspective,"
                "sap.dwc.consumptionModel,sap.dwc.factModel,"
                "sap.dwc.businessEntity,sap.dwc.authscenario"
            ),
        },
        headers=request_headers(
            Accept="application/json, text/javascript, */*; q=0.01",
            **{"X-Requested-With": "XMLHttpRequest"},
        ),
    )

    # The attribute names sit in the CSN the tenant repaired for the view
    try:
        view_data = response.json()["results"][0]
        return list(
            view_data["#repairedCsn"]["definitions"][view_name]["elements"]
        )
    except (httpx.HTTPError, JSONDecodeError, KeyError, IndexError):
        logger.error(
            "Error fetching details of view '%s' in '%s'.",
            view_name,
            space,
        )
        logger.debug("Response: %s\n", response.text.strip())
        return []


async def _get_partitioning(
    context: CommandContext,
    view: str,
    space: str,
) -> dict[str, Any]:
    """
    Reads the partitioning of one persisted view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.

    Returns:
        dict[str, Any]: Partitioning with 'ranges' and 'partitioningColumns'.
    """
    response = await context.session.get(
        url=_PARTITIONING_URL.format(space=space, view=view),
        headers=request_headers(),
    )
    return response.json()


async def _set_partitioning(
    context: CommandContext,
    view: str,
    space: str,
    partitioning: dict[str, Any],
) -> bool:
    """
    Creates or replaces the partitioning of one persisted view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.
        partitioning (dict[str, Any]): Full partitioning definition, in the
                                       shape the read returns.

    Returns:
        bool: Whether the tenant accepted the partitioning.
    """
    response = await context.session.post(
        url=_PARTITIONING_URL.format(space=space, view=view),
        json=partitioning,
        headers=request_headers(),
    )
    if response.status_code != 201:
        logger.debug("Response: %s\n", response.text)
        return False
    return True


async def _delete_partitioning(
    context: CommandContext,
    view: str,
    space: str,
) -> bool:
    """
    Removes the partitioning of one persisted view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.

    Returns:
        bool: Whether the partitioning was removed.
    """
    response = await context.session.delete(
        url=_PARTITIONING_URL.format(space=space, view=view),
        headers=request_headers(),
    )
    return response.status_code == 200


async def _get_task_logs(
    context: CommandContext,
    view: str,
    space: str,
) -> list[dict[str, Any]]:
    """
    Reads the task logs of one view.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.

    Returns:
        list[dict[str, Any]]: Log entries with 'status' and 'logId'.
    """
    response = await context.session.get(
        url=f"/dwaas-core/tf/{space}/logs",
        params={"objectId": view, "getLocks": True},
        headers=request_headers(**{"X-Requested-With": "XMLHttpRequest"}),
    )
    return response.json()["logs"]


async def _start_view_analyzer(
    context: CommandContext,
    view: str,
    space: str,
) -> tuple[bool, int | None, bool]:
    """
    Starts the view analyzer without waiting for its result.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.

    Returns:
        tuple[bool, int | None, bool]: Whether an analyzer run is going, its
                                       log ID if the start reported one, and
                                       whether it was already running before.
    """
    response = await context.session.post(
        url=f"/dwaas-core/advisor/{space}/execute/{view}",
        json={
            "withMemoryAnalysis": False,
            "maximumMemoryConsumptionInGiB": 1,
        },
        headers=request_headers(**{"X-Requested-With": "XMLHttpRequest"}),
    )

    # A run that was already going is as good as one this call started
    already_running = (
        response.status_code == 409 and "taskAlreadyRunning" in response.text
    )
    started = response.status_code == 202 and "Running" in response.text
    if not (already_running or started):
        return False, None, False

    # Neither answer is guaranteed to carry a usable log ID
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    log_id = payload.get("logId") if isinstance(payload, dict) else None
    if not isinstance(log_id, int):
        log_id = None
    return True, log_id, already_running


async def _get_view_analyzer_result(
    context: CommandContext,
    log_id: int,
    space: str,
) -> dict[str, Any]:
    """
    Reads the result of one completed view analyzer run.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        log_id (int): Task log ID of the analyzer run.
        space (str): Technical name of the Datasphere space.

    Returns:
        dict[str, Any]: Analyzer result with 'entityStats'.
    """
    response = await context.session.get(
        url=f"/dwaas-core/advisor/{space}/result/{log_id}",
        headers=request_headers(**{"X-Requested-With": "XMLHttpRequest"}),
    )
    return response.json()


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


# Statuses a view analyzer run reports while it is still going
_ANALYZER_ACTIVE_STATUSES = ("PENDING", "RUNNING")

# Seconds between two polls of a running view analyzer
ANALYZER_POLL_INTERVAL_SECONDS = 1


def _log_id_of(log: dict[str, Any]) -> int | None:
    """
    Reads the task log ID of one log entry.

    Args:
        log (dict[str, Any]): Log entry as returned by the task log endpoint.

    Returns:
        int | None: Log ID, or None if the entry carries no usable one.
    """
    log_id = log.get("logId")
    if isinstance(log_id, int) and not isinstance(log_id, bool):
        return log_id
    return None


def _match_analyzer_log(
    logs: list[dict[str, Any]],
    *,
    log_id: int | None,
    known_log_ids: set[int],
    already_running: bool,
) -> dict[str, Any] | None:
    """
    Picks the log entry that belongs to the started analyzer run.

    Args:
        logs (list[dict[str, Any]]): Current log entries of the view.
        log_id (int | None): Log ID the start returned, if any.
        known_log_ids (set[int]): Log IDs that existed before the start.
        already_running (bool): Whether the analyzer was running before.

    Returns:
        dict[str, Any] | None: Matching entry, or None while none fits yet.
    """
    for log in logs:
        candidate = _log_id_of(log)
        if candidate is None:
            continue
        if log_id is not None and candidate != log_id:
            continue
        if log_id is None and candidate in known_log_ids:
            continue
        return log

    # A run that was already going may not report a log ID of its own, so the
    # first active entry is the best guess left
    if already_running and log_id is None:
        for log in logs:
            if str(log.get("status", "")).upper() in _ANALYZER_ACTIVE_STATUSES:
                return log
    return None


async def _run_view_analyzer(
    context: CommandContext,
    *,
    view: str,
    space: str,
    timeout_seconds: float | None,
) -> tuple[int | None, list[dict[str, Any]]]:
    """
    Starts the view analyzer and waits for its entity statistics.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        view (str): Technical name of the view.
        space (str): Technical name of the Datasphere space.
        timeout_seconds (float | None): Maximum polling duration, or None to
                                        poll without a limit.

    Raises:
        CommandTimeoutError: If the run is still going when the timeout
                             expires. It continues remotely.
        CommandCancelledError: If polling is cancelled after the run started.
                               It continues remotely.

    Returns:
        tuple[int | None, list[dict[str, Any]]]: Log ID of the run and its
                                                 entity statistics. The
                                                 statistics are empty if the
                                                 run failed or never started.
    """
    # Remember the existing runs, so a new one can be told apart from them
    known_log_ids = {
        log_id
        for log in await _get_task_logs(context, view, space)
        if (log_id := _log_id_of(log)) is not None
    }

    started, log_id, already_running = await _start_view_analyzer(
        context,
        view,
        space,
    )
    if not started:
        return None, []

    started = time.monotonic()
    announced = started
    try:
        async with asyncio.timeout(timeout_seconds):
            while True:
                # Announce at the top, so the early continue below reports
                # its wait just like the completed run does
                announced = announce_runtime(
                    f"view '{view}'",
                    started,
                    announced,
                )
                logs = await _get_task_logs(context, view, space)
                matching = _match_analyzer_log(
                    logs,
                    log_id=log_id,
                    known_log_ids=known_log_ids,
                    already_running=already_running,
                )
                matching_id = (
                    None if matching is None else _log_id_of(matching)
                )
                if matching is None or matching_id is None:
                    await asyncio.sleep(ANALYZER_POLL_INTERVAL_SECONDS)
                    continue

                log_id = matching_id
                status = str(matching.get("status", "")).upper()
                if status == "COMPLETED":
                    break
                if status not in _ANALYZER_ACTIVE_STATUSES:
                    return log_id, []
                await asyncio.sleep(ANALYZER_POLL_INTERVAL_SECONDS)

    except TimeoutError:
        raise CommandTimeoutError(
            f"Analysis of view '{view}' in '{space}' timed out. "
            "The remote operation may continue.",
            log_id=to_text(log_id),
        ) from None
    except asyncio.CancelledError:
        raise CommandCancelledError(
            f"Analysis of view '{view}' in '{space}' was cancelled. "
            "The remote operation may continue.",
            log_id=to_text(log_id),
        ) from None

    result = await _get_view_analyzer_result(context, log_id, space)
    entities = result.get("entityStats", [])
    return log_id, entities if isinstance(entities, list) else []


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
    # Announce the analysis, because a batch reaches this command per item
    logger.info(
        "Analyzing view '%s' in space '%s'...",
        request.view,
        request.space,
    )

    # Run the view analyzer
    try:
        analyzer_log_id, entities = await _run_view_analyzer(
            context,
            view=request.view,
            space=request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except CommandTimeoutError as error:
        return FindViewPersistenceCandidatesResult(
            view=request.view,
            space=request.space,
            status=FindViewPersistenceCandidatesStatus.TIMED_OUT,
            candidates=(),
            log_id=to_text(error.log_id),
        )

    # Keep every entity that reached at least the requested candidate score
    candidates: list[ViewPersistenceCandidate] = []
    for entity in entities:

        # An entity without a usable score is dropped instead of compared,
        # because comparing None would raise a TypeError
        score = entity.get("persistencyCandidateScore")
        if not isinstance(score, int | float):
            continue

        if score >= request.minimum_candidate_score:
            candidates.append(_candidate_from_entity(entity, score))

    log_id = to_text(analyzer_log_id)

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
        views = await search_views(context)
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
    logger.info(
        "Searching the attributes of view '%s' in space '%s'...",
        request.view,
        request.space,
    )

    # Fetch all attributes of the view
    attributes = await _get_view_attributes(
        context,
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
        views = await search_views(context)
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
    logger.info(
        "Creating partitioning for view '%s' in space '%s'...",
        request.view,
        request.space,
    )
    partitioning = await _get_partitioning(
        context,
        request.view,
        request.space,
    )

    # Only a string column can carry a range partitioning
    column = partitioning["partitioningColumns"][request.attribute]
    if column["type"] != "cds.String":
        status = CreateViewPartitioningStatus.INVALID_COLUMN

    # Keep an existing partitioning unless the caller asked to replace it
    elif partitioning["ranges"] and not request.overwrite_existing:
        status = CreateViewPartitioningStatus.ALREADY_EXISTS

    else:
        accepted = await _set_partitioning(
            context,
            request.view,
            request.space,
            _yearly_partitioning(request),
        )
        status = (
            CreateViewPartitioningStatus.CREATED
            if accepted
            else CreateViewPartitioningStatus.FAILED
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
    logger.info(
        "Deleting the partitioning of view '%s' in space '%s'...",
        request.view,
        request.space,
    )
    deleted = await _delete_partitioning(
        context,
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
    logger.info(
        "Persisting view '%s' in space '%s'...",
        request.view,
        request.space,
    )

    # Start persistence
    try:
        success, details = await run_persistence(
            context,
            view=request.view,
            space=request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except CommandTimeoutError as error:
        return PersistViewResult(
            view=request.view,
            space=request.space,
            status=PersistViewStatus.TIMED_OUT,
            log_id=to_text(error.log_id),
        )

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
    logger.info(
        "Removing the persisted data of view '%s' in space '%s'...",
        request.view,
        request.space,
    )

    # Start removal of persistence
    try:
        success, details = await run_persistence_removal(
            context,
            view=request.view,
            space=request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except CommandTimeoutError as error:
        return UnpersistViewResult(
            view=request.view,
            space=request.space,
            status=UnpersistViewStatus.TIMED_OUT,
            log_id=to_text(error.log_id),
        )

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


def _yearly_partitioning(
    request: CreateViewPartitioningRequest,
) -> dict[str, Any]:
    """
    Builds the partitioning payload of one range per year.

    Args:
        request (CreateViewPartitioningRequest): Input for the partition
                                                 creation.

    Returns:
        dict[str, Any]: Payload for the partitioning endpoint.
    """
    # Each range spans one year, so the last year is only an upper bound
    years = [str(year) for year in range(request.start_year, request.end_year)]
    return {
        "remoteSourceName": "",
        "objectName": request.view,
        "numParallelPartitions": 1,
        "ranges": [
            {
                "id": index + 1,
                "low": {"include": True, "value": years[index]},
                "high": {"include": False, "value": years[index + 1]},
                "locked": False,
            }
            for index in range(len(years) - 1)
        ],
        "column": request.attribute,
        "columnType": "cds.String",
        "runtimeDataCalculation": "designtime",
        "type": "range",
    }


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
    partitioning = await _get_partitioning(context, view, space)
    if not partitioning["ranges"]:
        return "no_partitions"

    # Write back every field the endpoint expects, with the new lock flags
    payload = {field: partitioning[field] for field in _PARTITIONING_FIELDS}
    for partition in payload["ranges"]:
        partition["locked"] = locked(partition)

    accepted = await _set_partitioning(context, view, space, payload)
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
    logger.info(
        "Locking the partitions of view '%s' in space '%s'...",
        request.view,
        request.space,
    )
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
    logger.info(
        "Unlocking the partitions of view '%s' in space '%s'...",
        request.view,
        request.space,
    )
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
