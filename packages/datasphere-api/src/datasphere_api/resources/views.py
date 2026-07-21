import asyncio
import logging
from json import JSONDecodeError
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx

from datasphere_api.exceptions import (
    UnexpectedResponse,
    ViewAnalysisCancelled,
    ViewAnalysisTimeout,
    ViewPersistenceCancelled,
    ViewPersistenceTimeout,
)
from datasphere_api.models import (
    PartitionCreateOutcome,
    PartitionLockOutcome,
    ViewAnalyzerResultDict,
    ViewDetailsDict,
)
from datasphere_api.resources.base import BaseResource, validate_timeout

logger = logging.getLogger(__name__)


def _log_id_from_log(log: dict) -> int | None:
    """
    Fetches the logId from a payload.

    Args:
        log (dict): Payload of a log entry (as returned by get_task_logs()).

    Returns:
        int | None: LogId or None if it cannot be parsed.
    """
    log_id = log.get("logId")
    if isinstance(log_id, int) and not isinstance(log_id, bool):
        return log_id
    return None


class Views(BaseResource):

    async def get_all_views(self) -> list[ViewDetailsDict]:
        """
        Returns all views as a list of dictionaries.

        Returns:
            list[ViewDetailsDict]: List of dictionaries with view
                                   names ("name") and further details.
        """
        # Prepare request
        url = f"{self._base_url}/deepsea/repository/search/$all"
        params = {
            "$top": 10000,  # can't be omitted, else request won't work
            "$skip": 0,
            "whyfound": "true",
            "$count": "true",
            "valuehierarchy": "folder_id",
            "facets": "all",
            "facetlimit": 5,
            "$apply": (
                "filter(Search.search(query='SCOPE:SEARCH_DESIGN "
                '(technical_type_description:EQ(S):"View" AND (technical_type:'
                'EQ(S):"DWC_REMOTE_TABLE" OR technical_type:EQ(S):'
                '"DWC_LOCAL_TABLE" OR technical_type:EQ(S):"DWC_VIEW" OR '
                'technical_type:EQ(S):"DWC_ERMODEL" OR technical_type:EQ(S):'
                '"DWC_DATAFLOW" OR technical_type:EQ(S):"DWC_IDT" OR '
                'technical_type:EQ(S):"DWC_BUSINESS_ENTITY" OR technical_type:'
                'EQ(S):"DWC_AUTH_SCENARIO" OR technical_type:EQ(S):'
                '"DWC_FACT_MODEL" OR technical_type:EQ(S):'
                '"DWC_CONSUMPTION_MODEL" OR technical_type:EQ(S):'
                '"DWC_PERSPECTIVE" OR kind:EQ(S):"sap.dis.dataflow" OR kind:'
                'EQ(S):"sap.dwc.dac" OR kind:EQ(S):"sap.repo.folder" OR kind:'
                'EQ(S):"sap.dwc.analyticModel" OR kind:EQ(S):'
                '"sap.dwc.taskChain" OR kind:EQ(S):"sap.dis.replicationflow" '
                'OR technical_type:EQ(S):"DWC_TRANSFORMATIONFLOW")) *\'))'
            ),
        }

        # Send request
        logger.debug("Loading all views...")
        response = await self.session.get(
            url=f"{url}?{urlencode(params, safe='()*', quote_via=quote)}",
            headers={
                "Accept": "application/json",
                "Accept-Language": "de",
                "Cache-Control": "no-cache",
            },
        )
        all_views: list[ViewDetailsDict] = response.json()["value"]

        return all_views

    async def get_view_attributes(
        self,
        view_id: str,
        view_name: str,
        space: str,
    ) -> list[str]:
        """
        Returns the attribute names of a view (from its design object
        details).

        Args:
            view_id (str): ID of the view.
            view_name (str): Name of the view.
            space (str): Space of the view.

        Returns:
            list[str]: Attribute names of the view. Empty if the details cannot
            be fetched or parsed.
        """
        # Prepare request
        params = {
            "ids": view_id,
            "details": (
                "id,#repairedCsn,#ownerBusinessName,#creatorBusinessName,"
                "#repositoryPackage,@EnterpriseSearch.enabled,@remote.source,"
                "@DataWarehouse.external.schema,#objectPathIdentifier,"
                "#repositoryPackage,#repositoryValidationDate,hasPendingError,"
                "#isI18nEnabled"
            ),
            "kinds": (
                "entity,view,sap.dwc.ermodel,sap.dis.dataflow,"
                "sap.dwc.taskChain,sap.dwc.analyticModel,"
                "sap.dwc.dac,sap.repo.folder,sap.dis.replicationflow,"
                "sap.dis.transformationflow,sap.dwc.perspective,"
                "sap.dwc.consumptionModel,sap.dwc.factModel,"
                "sap.dwc.businessEntity,sap.dwc.authscenario"
            ),
        }

        # Send request and parse the attribute names from the CSN
        response = await self.session.get(
            url=f"{self._base_url}/deepsea/repository/{space}/designObjects",
            params=params,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        try:
            result = response.json()
            view_data = result["results"][0]
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

    async def get_partitioning(self, view: str, space: str) -> dict:
        """
        Returns the partitioning details of a persisted view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Returns:
            dict: Partitioning details (e.g. 'ranges', 'partitioningColumns').
        """
        response = await self.session.get(
            url=(
                f"{self._base_url}/dwaas-core/partitioning"
                f"/{space}/persistedViews/{view}"
            ),
            headers={
                "Accept": "*/*",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        return response.json()

    async def set_partitioning(
        self,
        view: str,
        space: str,
        data: dict,
    ) -> bool:
        """
        Creates or replaces the partitioning of a persisted view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.
            data (dict): Full partitioning definition (as returned by
                         get_partitioning()).

        Returns:
            bool: True if the partitioning was accepted, else False.
        """
        response = await self.session.post(
            url=(
                f"{self._base_url}/dwaas-core/partitioning"
                f"/{space}/persistedViews/{view}"
            ),
            json=data,
            headers={
                "Accept": "*/*",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        if response.status_code != 201:
            logger.debug("Response: %s\n", response.text)
            return False
        return True

    async def delete_partitioning(self, view: str, space: str) -> bool:
        """
        Removes the partitioning of a persisted view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Returns:
            bool: True if the partitioning was removed, else False.
        """
        response = await self.session.delete(
            url=(
                f"{self._base_url}/dwaas-core/partitioning"
                f"/{space}/persistedViews/{view}"
            ),
            headers={
                "Accept": "*/*",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        return response.status_code == 200

    async def get_monitor_details(self, view: str, space: str) -> dict:
        """
        Returns the monitor details of a view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Returns:
            dict: Monitor details. Empty if the request fails.
        """
        response = await self.session.get(
            url=f"{self._base_url}/dwaas-core/monitor/{space}"
            f"/persistedViews/{view}"
        )
        if response.status_code != 200:
            return {}
        return response.json()

    async def get_extended_log(self, log_id: int, space: str) -> dict:
        """
        Returns the extended log details of a task (e.g. a persistence run).

        Args:
            log_id (int): Task log ID.
            space (str): Space of the task.

        Returns:
            dict: Log details with 'status' and 'runTime'.
        """
        response = await self.session.get(
            url=(
                f"{self._base_url}/dwaas-core/tf/{space}/extendedlogs/{log_id}"
            ),
            headers={
                "Accept": "*/*",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        return response.json()["logDetails"]

    async def get_view_analyzer_result(
        self,
        log_id: int,
        space: str,
    ) -> dict:
        """
        Returns the result of a completed view analyzer run.

        Args:
            log_id (int): LogId of the analyzer run.
            space (str): Space of the analyzed view.

        Returns:
            dict: Analyzer result (e.g. 'entityStats').
        """
        response = await self.session.get(
            url=(
                f"{self._base_url}/dwaas-core/advisor/{space}/result/{log_id}"
            ),
            headers={
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        return response.json()

    async def get_task_logs(
        self,
        view: str,
        space: str,
    ) -> list[dict]:
        """
        Returns the task logs of a view.

        Args:
            view (str): View to fetch logs for.
            space (str): Space of the object.

        Returns:
            list[dict]: Log entries with 'status' and 'logId'.
        """
        response = await self.session.get(
            url=f"{self._base_url}/dwaas-core/tf/{space}/logs",
            params={"objectId": view, "getLocks": True},
            headers={
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        return response.json()["logs"]

    async def is_persisted(self, view: str, space: str) -> bool:
        """
        Checks if a view is currently persisted. Retries up to three times if
        the monitor endpoint doesn't answer.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Raises:
            UnexpectedResponse: If the persistence state cannot be checked
                                after three attempts.

        Returns:
            bool: True if the view is persisted, else False.
        """
        for _ in range(3):
            monitor_details = await self.get_monitor_details(view, space)
            if not monitor_details:
                await asyncio.sleep(1)
                continue
            return monitor_details.get("dataPersistency", "") == "Persisted"
        raise UnexpectedResponse(
            f"Failed to check persistence of view '{view}' in '{space}'."
        )

    async def start_persistence(self, view: str, space: str) -> int | None:
        """
        Starts the persistence of a view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Returns:
            int | None: Task log ID of the started run, or None if the start
                        failed.
        """
        response = await self.session.post(
            url=f"{self._base_url}/dwaas-core/tf/directexecute",
            json={
                "applicationId": "VIEWS",
                "spaceId": space,
                "objectId": view,
                "activity": "PERSIST",
            },
            headers={
                "Accept": "*/*",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        if response.status_code != 202:
            logger.error(
                "Error starting persistence for view '%s' in '%s'. "
                "Skipping...",
                view,
                space,
            )
            return None
        return response.json()["taskLogId"]

    async def start_persistence_removal(
        self,
        view: str,
        space: str,
    ) -> int | None:
        """
        Starts the removal of the persisted data of a view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Returns:
            int | None: Task log ID of the started run, or None if the start
                        failed.
        """
        response = await self.session.post(
            url=f"{self._base_url}/dwaas-core/tf/directexecute",
            json={
                "applicationId": "VIEWS",
                "spaceId": space,
                "objectId": view,
                "activity": "REMOVE_PERSISTED_DATA",
            },
            headers={
                "Accept": "*/*",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        if response.status_code != 202:
            logger.error(
                "Error removing persistence for view '%s' in '%s'. "
                "Skipping...",
                view,
                space,
            )
            return None
        return response.json()["taskLogId"]

    async def start_view_analyzer(self, view: str, space: str) -> bool:
        """
        Starts the view analyzer for a view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Returns:
            bool: True if the analyzer was started (or is already running),
                  else False.
        """
        started, _, _ = await self._start_view_analyzer(view, space)
        return started

    async def _start_view_analyzer(
        self,
        view: str,
        space: str,
    ) -> tuple[bool, int | None, bool]:
        """
        Starts the view analyzer.

        Args:
            view (str): View to analyze.
            space (str): Space of the view.

        Returns:
            tuple[bool, int | None, bool]: A tuple containing, in order:
                                           whether the analyzer was started,
                                           the log ID of the run (or None), and
                                           whether the analyzer was already
                                           running.
        """
        # Start view analyzer
        response = await self.session.post(
            url=f"{self._base_url}/dwaas-core/advisor/{space}/execute/{view}",
            json={
                "withMemoryAnalysis": False,
                "maximumMemoryConsumptionInGiB": 1,
            },
            headers={
                "x-request-id": str(uuid4()).replace("-", ""),
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

        # Check if analyzer was started successfully or is already running
        already_running = (
            response.status_code == 409
            and "taskAlreadyRunning" in response.text
        )
        started = response.status_code == 202 and "Running" in response.text
        if not (already_running or started):
            logger.error(
                "Error starting view analyzer for view '%s' in '%s'.",
                view,
                space,
            )
            return False, None, False

        # Fetch payload
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}

        # Extract logId from paylaod
        log_id = (
            response_payload.get("logId")
            if isinstance(response_payload, dict)
            else None
        )
        if not isinstance(log_id, int):
            log_id = None
        return True, log_id, already_running

    async def persist_view(
        self,
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict]:
        """
        Persists a view and waits for the run to finish. Does not check if the
        view is already persisted.

        Args:
            view (str): View to persist.
            space (str): Space of the view.
            timeout_seconds (float | None, optional): Maximum polling duration.
                                                      None if no timeout should
                                                      be used.

        Raises:
            ViewPersistenceTimeout: If polling times out after persistence
                                    starts. The remote operation may continue.
            ViewPersistenceCancelled: If polling is cancelled after persistence
                                      starts. The remote operation may
                                      continue.
            ValueError: If timeout_seconds is not positive and finite, or is
                        a boolean.

        Returns:
            tuple[bool, dict]: True if persistence was successful, otherwise
                               False. Dict with log details (containing the
                               keys 'status', 'runTime' and 'logId').
        """
        validate_timeout(timeout_seconds)

        # Start persistence
        logger.debug(
            "Starting persistence of view '%s' in '%s'...",
            view,
            space,
        )
        log_id = await self.start_persistence(view, space)
        if log_id is None:
            return False, {}

        # Wait for results
        log_details = {}
        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    log_details = await self.get_extended_log(log_id, space)

                    # Add logId to the log details
                    log_details["logId"] = log_id

                    # Check status of the run
                    latest_status = log_details["status"]
                    if latest_status == "COMPLETED":
                        break
                    if latest_status != "RUNNING":
                        logger.error(
                            "Error persisting view '%s' in '%s'.",
                            view,
                            space,
                        )
                        return False, log_details

                    # Convert runTime to readable format and log to console
                    milliseconds = log_details["runTime"]
                    hours, remainder = divmod(milliseconds, 3600000)
                    minutes, seconds = divmod(remainder, 60000)
                    seconds, milliseconds = divmod(seconds, 1000)
                    logger.debug(
                        "Waiting for results for view '%s' in '%s'. "
                        "Current runtime: %02d:%02d:%02d.",
                        view,
                        space,
                        hours,
                        minutes,
                        seconds,
                    )
                    await asyncio.sleep(1)

        except TimeoutError:
            exc = ViewPersistenceTimeout("persist", view, space, log_id)
            raise exc from None

        except asyncio.CancelledError:
            exc = ViewPersistenceCancelled("persist", view, space, log_id)
            raise exc from None

        # Return successful result with log details
        logger.info(
            "Completed persistence for view '%s' in '%s'.",
            view,
            space,
        )
        return True, log_details

    async def unpersist_view(
        self,
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict]:
        """
        Removes the persistence for a view and waits for the run to finish.
        Checks if the view is persisted at all.

        Args:
            view (str): View to unpersist.
            space (str): Space of the view.
            timeout_seconds (float | None, optional): Maximum polling duration.
                                                      None if no timeout should
                                                      be used.

        Raises:
            ViewPersistenceTimeout: If polling times out after removal starts.
                                    The remote operation may continue.
            ViewPersistenceCancelled: If polling is cancelled after removal
                                      starts. The remote operation may
                                      continue.
            ValueError: If timeout_seconds is not positive and finite, or is
                        a boolean.

        Returns:
            tuple[bool, dict]: True if persistence was removed successfully or
                               did not exist, otherwise False. Dict with log
                               details (containing the keys 'status', 'runTime'
                               and 'logId').
        """
        validate_timeout(timeout_seconds)

        # Check if view is persisted
        monitor_details = await self.get_monitor_details(view, space)
        if "dataPersistency" not in monitor_details:
            logger.error(
                "Error checking if view '%s' in '%s' is persisted. "
                "Skipping...",
                view,
                space,
            )
            return False, {}
        if monitor_details["dataPersistency"] != "Persisted":
            logger.debug(
                "View '%s' in '%s' is not persisted. Skipping...",
                view,
                space,
            )
            return True, {}

        # Start removal
        logger.debug(
            "Removing persistence for view '%s' in '%s'...",
            view,
            space,
        )
        log_id = await self.start_persistence_removal(view, space)
        if log_id is None:
            return False, {}

        # Wait for results
        log_details = {}
        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    log_details = await self.get_extended_log(
                        log_id, space
                    )

                    # Add logId to the log details
                    log_details["logId"] = log_id

                    # Check status of the run
                    latest_status = log_details["status"]
                    if latest_status == "COMPLETED":
                        break
                    if latest_status != "RUNNING":
                        logger.error(
                            "Error removing persistence for view '%s' in "
                            "'%s'.",
                            view,
                            space,
                        )
                        return False, log_details

                    # Convert runtime to readable format and log to console
                    milliseconds = log_details["runTime"]
                    hours, remainder = divmod(milliseconds, 3600000)
                    minutes, seconds = divmod(remainder, 60000)
                    seconds, milliseconds = divmod(seconds, 1000)
                    logger.debug(
                        "Waiting for results for view '%s' in '%s'. "
                        "Current runtime: %02d:%02d:%02d.",
                        view,
                        space,
                        hours,
                        minutes,
                        seconds,
                    )
                    await asyncio.sleep(1)

        except TimeoutError:
            exc = ViewPersistenceTimeout("unpersist", view, space, log_id)
            raise exc from None

        except asyncio.CancelledError:
            exc = ViewPersistenceCancelled("unpersist", view, space, log_id)
            raise exc from None

        # Return successful result with log details
        logger.info(
            "Removed persistence for view '%s' in '%s'.",
            view,
            space,
        )
        return True, log_details

    async def analyze_view(
        self,
        view: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ViewAnalyzerResultDict:
        """
        Runs the view analyzer for a view, waits for the run to finish and
        returns the entity statistics (including the persistency candidate
        scores).

        Args:
            view (str): Name of the view.
            space (str): Space of the view.
            timeout_seconds (float | None, optional): Maximum polling duration.
                                                      None if no timeout should
                                                      be used.

        Raises:
            ViewAnalysisTimeout: If polling times out after analysis starts.
                                 The remote operation may continue.
            ViewAnalysisCancelled: If polling is cancelled after analysis
                                   starts. The remote operation may continue.
            ValueError: If timeout_seconds is not positive and finite, or is
                        a boolean.

        Returns:
            ViewAnalyzerResultDict: The analyzer log ID and entity statistics.
                                    Entity statistics are empty if the run
                                    could not be started or failed.
        """
        validate_timeout(timeout_seconds)

        # Snapshot existing log IDs to compare with later
        existing_logs = await self.get_task_logs(view, space)
        existing_log_ids: set[int] = set()
        for log in existing_logs:
            log_id = _log_id_from_log(log)
            if log_id is not None:
                existing_log_ids.add(log_id)

        # Start the analyzer
        logger.debug(
            "Starting view analyzer for view '%s' in '%s'...",
            view,
            space,
        )
        started, log_id, already_running = await self._start_view_analyzer(
            view=view,
            space=space,
        )
        if not started:
            return {"logId": None, "entityStats": []}
        logger.info(
            "Started view analyzer for view '%s' in '%s'.",
            view,
            space,
        )

        # Poll the view analyzer run
        active_statuses = ("PENDING", "RUNNING")
        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    # Find corresponding log entry for the started run
                    logs = await self.get_task_logs(view, space)
                    matching_log = None
                    for log in logs:
                        candidate_id = _log_id_from_log(log)
                        if candidate_id is None:
                            continue
                        if log_id is not None and candidate_id != log_id:
                            continue
                        if log_id is None and candidate_id in existing_log_ids:
                            continue
                        matching_log = log
                        break

                    # Fallback if view analyzer was already running and no
                    # logId was returned
                    if matching_log is None:

                        # Fetch first log entry with an active status
                        if already_running and log_id is None:
                            for log in logs:
                                status = str(log.get("status", "")).upper()
                                if status in active_statuses:
                                    matching_log = log
                                    break

                        # Check if matching log entry was found
                        if matching_log is None:
                            await asyncio.sleep(1)
                            continue

                    # Fetch matching logId
                    matching_log_id = _log_id_from_log(matching_log)
                    if matching_log_id is None:
                        await asyncio.sleep(1)
                        continue

                    # Update log ID and check status
                    log_id = matching_log_id
                    status = str(matching_log.get("status", "")).upper()
                    if status == "COMPLETED":
                        break
                    if status not in active_statuses:
                        logger.error(
                            "Error generating view analysis for view '%s' "
                            "in '%s'.",
                            view,
                            space,
                        )
                        return {"logId": log_id, "entityStats": []}
                    logger.debug(
                        "Waiting for results for view '%s' in '%s'...",
                        view,
                        space,
                    )
                    await asyncio.sleep(1)

        except TimeoutError:
            raise ViewAnalysisTimeout(view, space, log_id) from None

        except asyncio.CancelledError:
            raise ViewAnalysisCancelled(view, space, log_id) from None

        # Fetch results of the view analyzer run
        result = await self.get_view_analyzer_result(log_id, space)
        entity_stats = result.get("entityStats", [])
        if not isinstance(entity_stats, list):
            entity_stats = []
        return {"logId": log_id, "entityStats": entity_stats}

    async def create_partitioning(
        self,
        view: str,
        space: str,
        attribute: str,
        partitions: list[str],
        overwrite_existing: bool = False,
    ) -> PartitionCreateOutcome:
        """
        Creates range partitions for a persisted view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.
            attribute (str): Attribute to partition by (has to be a string).
            partitions (list[str]): List of all partitions to be created in the
                                    correct order.
                                    Example: ['0000', '2001', '2002', ...]
                                    Last value is the upper limit of the
                                    last partition (example: FISCYEAR < 2025).
                                    Therefore the list has to have at least two
                                    values.
            overwrite_existing (bool, optional): If True, existing partitions
                                                 will get overwritten.
                                                 Otherwise views with existing
                                                 partitions are skipped.
                                                 Defaults to False.

        Returns:
            PartitionCreateOutcome: 'created', 'exists' (skipped),
                                    'invalid_column' or 'failed'.
        """
        # Fetch current partitioning
        partitioning = await self.get_partitioning(view, space)
        partition_exists = len(partitioning["ranges"]) > 0

        # Check if the column used for the partition is of type string
        column_type = partitioning["partitioningColumns"][attribute]["type"]
        if column_type != "cds.String":
            logger.error(
                "Attribute '%s' of view '%s' in '%s' is not of type "
                "string. Skipping...",
                attribute,
                view,
                space,
            )
            return "invalid_column"

        # Skip if a partitioning exists and should not be overwritten
        if partition_exists and not overwrite_existing:
            logger.debug(
                "View '%s' in '%s' is already partitioned. Skipping...",
                view,
                space,
            )
            return "exists"

        # Create partitions
        logger.debug(
            "Creating partitions for view '%s' in '%s'...",
            view,
            space,
        )
        data = {
            "remoteSourceName": "",
            "objectName": view,
            "numParallelPartitions": 1,
            "ranges": [
                {
                    "id": index + 1,
                    "low": {"include": True, "value": partitions[index]},
                    "high": {
                        "include": False,
                        "value": partitions[index + 1],
                    },
                    "locked": False,
                }
                for index in range(len(partitions) - 1)
            ],
            "column": attribute,
            "columnType": "cds.String",
            "runtimeDataCalculation": "designtime",
            "type": "range",
        }

        # Check for success
        if await self.set_partitioning(view, space, data):
            logger.info(
                "Created partitions for view '%s' in '%s'.",
                view,
                space,
            )
            return "created"
        logger.error(
            "Error creating partitions for view '%s' in '%s'.",
            view,
            space,
        )
        return "failed"

    def _build_partitioning_payload(self, partitioning: dict) -> dict:
        """
        Builds the payload for set_partitioning() from an existing partitioning
        definition.

        Args:
            partitioning (dict): Partitioning details as returned by
                                 get_partitioning().

        Returns:
            dict: Payload with all fields required by the endpoint.
        """
        return {
            "remoteSourceName": partitioning["remoteSourceName"],
            "objectName": partitioning["objectName"],
            "numParallelPartitions": partitioning["numParallelPartitions"],
            "ranges": partitioning["ranges"],
            "column": partitioning["column"],
            "columnType": partitioning["columnType"],
            "runtimeDataCalculation": partitioning["runtimeDataCalculation"],
            "type": partitioning["type"],
        }

    async def lock_partitions(
        self,
        view: str,
        space: str,
        until_year: int,
    ) -> PartitionLockOutcome:
        """
        Locks all partitions of a view up to (and including) the given year.
        All partitions have to be integers!!

        Args:
            view (str): Name of the view.
            space (str): Space of the view.
            until_year (int): Year up to which partitions should be locked
                              (including the year itself).

        Returns:
            PartitionLockOutcome: 'locked', 'no_partitions' or 'failed'.
        """
        # Fetch current partitioning
        partitioning = await self.get_partitioning(view, space)
        if len(partitioning["ranges"]) == 0:
            logger.error(
                "View '%s' in '%s' has no partitions. Skipping...",
                view,
                space,
            )
            return "no_partitions"

        # Lock all partitions up to the given year
        logger.debug(
            "Locking partitions for view '%s' in '%s' up to (including) "
            "year %s...",
            view,
            space,
            until_year,
        )
        data = self._build_partitioning_payload(partitioning)
        for partition in data["ranges"]:
            if int(partition["low"]["value"]) <= until_year:
                partition["locked"] = True
        if await self.set_partitioning(view, space, data):
            logger.info(
                "Locked partitions for view '%s' in '%s' "
                "up to (and including) year %s.",
                view,
                space,
                until_year,
            )
            return "locked"
        logger.error(
            "Error locking partitions for view '%s' in '%s'.",
            view,
            space,
        )
        return "failed"

    async def unlock_partitions(
        self,
        view: str,
        space: str,
    ) -> PartitionLockOutcome:
        """
        Unlocks all partitions of a view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Returns:
            PartitionLockOutcome: 'unlocked', 'no_partitions' or 'failed'.
        """
        # Fetch current partitioning
        partitioning = await self.get_partitioning(view, space)
        if len(partitioning["ranges"]) == 0:
            logger.error(
                "View '%s' in '%s' has no partitions. Skipping...",
                view,
                space,
            )
            return "no_partitions"

        # Unlock all partitions
        logger.debug(
            "Unlocking all partitions of view '%s' in '%s'...",
            view,
            space,
        )
        data = self._build_partitioning_payload(partitioning)
        for partition in data["ranges"]:
            partition["locked"] = False
        if await self.set_partitioning(view, space, data):
            logger.info(
                "Unlocked all partitions for view '%s' in '%s'.",
                view,
                space,
            )
            return "unlocked"
        logger.error(
            "Error unlocking partitions for view '%s' in '%s'.",
            view,
            space,
        )
        return "failed"
