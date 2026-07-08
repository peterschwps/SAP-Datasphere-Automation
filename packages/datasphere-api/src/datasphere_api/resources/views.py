import asyncio
import contextlib
import logging
from json import JSONDecodeError
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx

from datasphere_api.exceptions import UnexpectedResponse
from datasphere_api.models import (
    PartitionCreateOutcome,
    PartitionLockOutcome,
    ViewDetailsDict,
)
from datasphere_api.resources.base import BaseResource

logger = logging.getLogger(__name__)


class Views(BaseResource):

    # Endpoint methods (one HTTP call each)

    async def get_all_views(self) -> list[ViewDetailsDict]:
        """
        Returns all views as a list of dictionaries.

        Returns:
            list[ViewDetailsDict]: List of dictionaries with view
                                   names ("name") and further details.
        """
        # Update headers
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Accept-Language": "de",
                "Cache-Control": "no-cache",
            }
        )

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
            url=f"{url}?{urlencode(params, safe='()*', quote_via=quote)}"
        )
        all_views: list[ViewDetailsDict] = response.json()["value"]

        # Remove unnecessary headers for next requests
        with contextlib.suppress(KeyError):
            self.session.headers.pop("Cache-Control")

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
            list[str]: Attribute names of the view. Empty if the details
                       cannot be fetched or parsed.
        """
        # Update headers
        self.session.headers.update(
            {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "x-request-id": str(uuid4()).replace("-", ""),
            }
        )

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
            url=f"{self._base_url}/deepsea/repository"
            f"/{space}/designObjects",
            params=params,
        )
        try:
            view_data = response.json()
            return list(
                view_data["results"][0]["#repairedCsn"]["definitions"][
                    view_name
                ]["elements"]
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
            dict: Partitioning details (e.g. 'ranges',
                  'partitioningColumns').
        """
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )
        response = await self.session.get(
            url=f"{self._base_url}/dwaas-core/partitioning"
            f"/{space}/persistedViews/{view}"
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
        self.session.headers.update(
            {"x-request-id": str(uuid4()).replace("-", "")}
        )
        response = await self.session.post(
            url=f"{self._base_url}/dwaas-core/partitioning"
            f"/{space}/persistedViews/{view}",
            json=data,
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
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )
        response = await self.session.delete(
            url=f"{self._base_url}/dwaas-core/partitioning"
            f"/{space}/persistedViews/{view}"
        )
        return response.status_code == 200

    async def get_monitor_details(self, view: str, space: str) -> dict:
        """
        Returns the monitor details of a view (e.g. 'dataPersistency').

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
        Returns the extended log details of a task (e.g. a persistence
        run).

        Args:
            log_id (int): Task log ID.
            space (str): Space of the task.

        Returns:
            dict: Log details with 'status' and 'runTime'.
        """
        self.session.headers.update(
            {"x-request-id": str(uuid4()).replace("-", "")}
        )
        response = await self.session.get(
            url=(
                f"{self._base_url}/dwaas-core/tf"
                f"/{space}/extendedlogs/{log_id}"
            )
        )
        return response.json()["logDetails"]

    async def start_persistence(self, view: str, space: str) -> int | None:
        """
        Starts the persistence of a view.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Returns:
            int | None: Task log ID of the started run, or None if the
                        start failed.
        """
        response = await self.session.post(
            url=f"{self._base_url}/dwaas-core/tf/directexecute",
            json={
                "applicationId": "VIEWS",
                "spaceId": space,
                "objectId": view,
                "activity": "PERSIST",
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
            int | None: Task log ID of the started run, or None if the
                        start failed.
        """
        self.session.headers.update(
            {"x-request-id": str(uuid4()).replace("-", "")}
        )
        response = await self.session.post(
            url=f"{self._base_url}/dwaas-core/tf/directexecute",
            json={
                "applicationId": "VIEWS",
                "spaceId": space,
                "objectId": view,
                "activity": "REMOVE_PERSISTED_DATA",
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
            bool: True if the analyzer was started (or is already
                  running), else False.
        """
        self.session.headers.update(
            {
                "x-request-id": str(uuid4()).replace("-", ""),
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        response = await self.session.post(
            url=(
                f"{self._base_url}/dwaas-core/advisor/{space}"
                f"/execute/{view}"
            ),
            json={
                "withMemoryAnalysis": False,
                "maximumMemoryConsumptionInGiB": 1,
            },
        )

        # The analyzer counts as started if it is already running
        if not (
            response.status_code == 409
            and "taskAlreadyRunning" in response.text
        ) and not (
            response.status_code == 202 and "Running" in response.text
        ):
            logger.error(
                "Error starting view analyzer for view '%s' in '%s'.",
                view,
                space,
            )
            return False
        return True

    async def get_task_logs(
        self,
        object_id: str,
        space: str,
    ) -> list[dict]:
        """
        Returns the task logs of an object (newest first).

        Args:
            object_id (str): ID/name of the object (e.g. a view).
            space (str): Space of the object.

        Returns:
            list[dict]: Log entries with 'status' and 'logId'.
        """
        self.session.headers.update(
            {"x-request-id": str(uuid4()).replace("-", "")}
        )
        response = await self.session.get(
            url=f"{self._base_url}/dwaas-core/tf/{space}/logs",
            params={"objectId": object_id, "getLocks": True},
        )
        return response.json()["logs"]

    async def get_view_analyzer_result(
        self,
        log_id: int,
        space: str,
    ) -> dict:
        """
        Returns the result of a completed view analyzer run.

        Args:
            log_id (int): Log ID of the analyzer run.
            space (str): Space of the analyzed view.

        Returns:
            dict: Analyzer result (e.g. 'entityStats').
        """
        self.session.headers.update(
            {"x-request-id": str(uuid4()).replace("-", "")}
        )
        response = await self.session.get(
            url=(
                f"{self._base_url}/dwaas-core/advisor"
                f"/{space}/result/{log_id}"
            )
        )
        return response.json()

    # Single-view workflows (compositions of the endpoint methods)

    async def persist_view(
        self, view_name: str, view_space: str
    ) -> tuple[bool, dict]:
        """
        Persists a view and waits for the run to finish. Does not check
        if the view is already persisted.

        Args:
            view_name (str): Name of the view.
            view_space (str): Name of the view space.

        Returns:
            tuple[bool, dict]: True if persistence was successful,
                               otherwise False. Dict with log details.
        """
        # Start persistence
        logger.debug(
            "Starting persistence of view '%s' in '%s'...",
            view_name,
            view_space,
        )
        log_id = await self.start_persistence(view_name, view_space)
        if log_id is None:
            return False, {}

        # Wait for results
        log_details = {}
        while True:
            log_details = await self.get_extended_log(log_id, view_space)
            latest_status = log_details["status"]
            if latest_status == "COMPLETED":
                break
            if latest_status != "RUNNING":
                logger.error(
                    "Error persisting view '%s' in '%s'.",
                    view_name,
                    view_space,
                )
                return False, log_details

            # Convert runtime to readable format and print to console
            milliseconds = log_details["runTime"]
            hours, remainder = divmod(milliseconds, 3600000)
            minutes, seconds = divmod(remainder, 60000)
            seconds, milliseconds = divmod(seconds, 1000)
            logger.debug(
                "Waiting for results for view '%s' in '%s'. "
                "Current runtime: %02d:%02d:%02d.",
                view_name,
                view_space,
                hours,
                minutes,
                seconds,
            )
            await asyncio.sleep(1)

        # Return successful result with log details
        logger.info(
            "Completed persistence for view '%s' in '%s'.",
            view_name,
            view_space,
        )
        return True, log_details

    async def unpersist_view(
        self, view_name: str, view_space: str
    ) -> tuple[bool, dict]:
        """
        Removes the persistence for a view and waits for the run to
        finish. Checks if the view is persisted at all.

        Args:
            view_name (str): Name of the view.
            view_space (str): Name of the view space.

        Returns:
            tuple[bool, dict]: True if persistence was removed
                               successfully, otherwise False. Dictionary
                               with log details.
        """
        # Check if view is persisted
        monitor_details = await self.get_monitor_details(
            view_name, view_space
        )
        if "dataPersistency" not in monitor_details:
            logger.error(
                "Error checking if view '%s' in '%s' is persisted. "
                "Skipping...",
                view_name,
                view_space,
            )
            return False, {}
        if monitor_details["dataPersistency"] != "Persisted":
            logger.debug(
                "View '%s' in '%s' is not persisted. Skipping...",
                view_name,
                view_space,
            )
            return True, {}

        # Start removal
        logger.debug(
            "Removing persistence for view '%s' in '%s'...",
            view_name,
            view_space,
        )
        log_id = await self.start_persistence_removal(view_name, view_space)
        if log_id is None:
            return False, {}

        # Wait for results
        log_details = {}
        while True:
            log_details = await self.get_extended_log(log_id, view_space)
            latest_status = log_details["status"]
            if latest_status == "COMPLETED":
                break
            if latest_status != "RUNNING":
                logger.error(
                    "Error removing persistence for view '%s' in '%s'.",
                    view_name,
                    view_space,
                )
                return False, log_details

            # Convert runtime to readable format and print to console
            milliseconds = log_details["runTime"]
            hours, remainder = divmod(milliseconds, 3600000)
            minutes, seconds = divmod(remainder, 60000)
            seconds, milliseconds = divmod(seconds, 1000)
            logger.debug(
                "Waiting for results for view '%s' in '%s'. "
                "Current runtime: %02d:%02d:%02d.",
                view_name,
                view_space,
                hours,
                minutes,
                seconds,
            )
            await asyncio.sleep(1)

        # Return successful result with log details
        logger.info(
            "Removed persistence for view '%s' in '%s'.",
            view_name,
            view_space,
        )
        return True, log_details

    async def is_persisted(self, view: str, space: str) -> bool:
        """
        Checks if a view is currently persisted. Retries up to three
        times if the monitor endpoint doesn't answer.

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Raises:
            UnexpectedResponse: If the persistence state cannot be
                                checked after three attempts.

        Returns:
            bool: True if the view is persisted, else False.
        """
        for _ in range(3):
            monitor_details = await self.get_monitor_details(view, space)
            if not monitor_details:
                await asyncio.sleep(3)
                continue
            return monitor_details.get("dataPersistency", "") == "Persisted"
        raise UnexpectedResponse(
            f"Failed to check persistence of view '{view}' in '{space}'."
        )

    async def analyze_view(self, view: str, space: str) -> list[dict]:
        """
        Runs the view analyzer for a view, waits for the run to finish
        and returns the entity statistics (including the persistency
        candidate scores).

        Args:
            view (str): Name of the view.
            space (str): Space of the view.

        Returns:
            list[dict]: Entity statistics of the analyzer run. Empty if
                        the run could not be started or failed.
        """
        # Start the analyzer
        logger.debug(
            "Starting view analyzer for view '%s' in '%s'...",
            view,
            space,
        )
        if not await self.start_view_analyzer(view, space):
            return []
        logger.info(
            "Started view analyzer for view '%s' in '%s'.",
            view,
            space,
        )

        # Wait for results
        latest_status = None
        while latest_status != "COMPLETED":
            logs = await self.get_task_logs(view, space)
            latest_status = logs[0]["status"]
            if latest_status == "FAILED":
                logger.error(
                    "Error generating view analysis for view '%s' in '%s'.",
                    view,
                    space,
                )
                return []
            logger.debug(
                "Waiting for results for view '%s' in '%s'...",
                view,
                space,
            )
            await asyncio.sleep(1)

        # Fetch the result of the latest run
        log_id: int = (await self.get_task_logs(view, space))[0]["logId"]
        result = await self.get_view_analyzer_result(log_id, space)
        return result["entityStats"]

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
            attribute (str): Attribute to partition by (has to be of
                             type string).
            partitions (list[str]): List of all partitions to be created
                                    in the correct order.
                                    Example: ['0000', '2001', '2002', ...]
                                    Last value is the upper limit of the
                                    last partition (example:
                                    FISCYEAR < 2025). Therefore has to
                                    have at least two values.
            overwrite_existing (bool, optional): If True, existing
                                                 partitions will get
                                                 overwritten. Otherwise
                                                 views with existing
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

    async def lock_partitions(
        self,
        view: str,
        space: str,
        until_year: int,
    ) -> PartitionLockOutcome:
        """
        Locks all partitions of a view up to (and including) the given
        year. All partitions have to be integers!!

        Args:
            view (str): Name of the view.
            space (str): Space of the view.
            until_year (int): Year up to which partitions should be
                              locked (including the year itself).

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
            PartitionLockOutcome: 'unlocked', 'no_partitions' or
                                  'failed'.
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

    def _build_partitioning_payload(self, partitioning: dict) -> dict:
        """
        Builds the payload for set_partitioning() from an existing
        partitioning definition.

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
            "runtimeDataCalculation": partitioning[
                "runtimeDataCalculation"
            ],
            "type": partitioning["type"],
        }
