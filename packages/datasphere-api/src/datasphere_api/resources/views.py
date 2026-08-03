import asyncio
import logging
from json import JSONDecodeError
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx

from datasphere_api.exceptions import (
    UnexpectedResponse,
)
from datasphere_api.models import (
    ViewDetailsDict,
)
from datasphere_api.resources.base import BaseResource

logger = logging.getLogger(__name__)


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

    async def start_view_analyzer(
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
