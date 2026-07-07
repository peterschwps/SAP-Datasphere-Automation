import asyncio
import contextlib
import logging
from collections.abc import Callable
from json import JSONDecodeError
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx

from datasphere_api.models import (
    PartitionCreateResult,
    PartitionDeleteResult,
    PartitionLockResult,
    PartitionTask,
    PartitionUnlockResult,
    PersistenceCandidate,
    PersistResult,
    UnpersistResult,
    ViewAttributeMatch,
    ViewDetailsDict,
    ViewRef,
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

    async def get_all_views_where_attribute_contains(
        self,
        word: str,
        thread_count: int = 1,
        on_result: Callable[[ViewAttributeMatch], None] | None = None,
    ) -> list[ViewAttributeMatch]:
        """
        Retrieves all views with an attribute that contains the search
        word.

        Args:
            word (str): Search word (case-insensitive).
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            on_result (Callable | None, optional): Callback that is
                                                   invoked with each
                                                   match as soon as it
                                                   is found.
                                                   Defaults to None.

        Returns:
            list[ViewAttributeMatch]: All matches of views and their
                                      attributes containing the search
                                      word.
        """
        # Fetch all views
        all_views = await self.get_all_views()

        # Update headers
        self.session.headers.update(
            {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            }
        )

        # Prepare request
        logger.debug(
            "Searching for views that have an attribute "
            "containing the substring '%s'...",
            word,
        )
        matches: list[ViewAttributeMatch] = []

        # Function to check if view has a matching attribute
        async def check_view_for_attribute_with_substring(view) -> None:
            # Update parameters
            params = {
                "ids": view["id"],
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

            # Update request ID
            self.session.headers.update(
                {
                    "x-request-id": str(uuid4()).replace("-", ""),
                }
            )

            # Send request
            logger.debug(
                "Checking view '%s' in '%s'...",
                view["name"],
                view["space_name"],
            )
            response = await self.session.get(
                url=f"{self._base_url}/deepsea/repository"
                f"/{view['space_name']}/designObjects",
                params=params,
            )
            try:
                view_data = response.json()
            except (httpx.HTTPError, JSONDecodeError):
                logger.error(
                    "Error fetching details of view '%s' in '%s'.",
                    view["name"],
                    view["space_name"],
                )
                logger.debug(
                    "View: %s\nResponse: %s\n", view, response.text.strip()
                )
                return

            # Save view if an attribute containing the search word is
            # found
            for attribute in view_data["results"][0]["#repairedCsn"][
                "definitions"
            ][view["name"]]["elements"]:
                if word.lower() in attribute.lower():
                    logger.info(
                        "View '%s' in '%s' has attribute '%s'.",
                        view["name"],
                        view["space_name"],
                        attribute,
                    )
                    match: ViewAttributeMatch = {
                        "entity": view["name"],
                        "space": view["space_name"],
                        "businessName": view["business_name"],
                        "attribute": attribute,
                    }
                    matches.append(match)
                    if on_result is not None:
                        on_result(match)

        # Start tasks
        await self._client.run_async_tasks(
            all_views, check_view_for_attribute_with_substring, thread_count
        )
        return matches

    async def create_view_analytics(
        self,
        thread_count: int = 1,
        on_result: Callable[[PersistenceCandidate], None] | None = None,
    ) -> list[PersistenceCandidate]:
        """
        Creates view analytics for all views. Threads can be used in small
        amounts, otherwise rate limits may occur.
        Five threads have been run successfully.

        Args:
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            on_result (Callable | None, optional): Callback that is
                                                   invoked with each
                                                   candidate as soon as
                                                   it is found.
                                                   Defaults to None.

        Returns:
            list[PersistenceCandidate]: All views that received a
                                        persistence score of 10 from the
                                        view analyzer.
        """

        # Fetch all views
        all_views = await self.get_all_views()

        # Update headers
        self.session.headers.update(
            {
                "x-request-id": str(uuid4()).replace("-", ""),
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        candidates: list[PersistenceCandidate] = []

        async def analyze_view(
            view: ViewDetailsDict,
            filter_out_own_view: bool = False,
        ) -> None:
            """
            Runs the view analyzer and saves all views with a persistence
            score of 10.

            Args:
                view (ViewDetailsDict): View to analyze.
                filter_out_own_view (bool, optional): If True, the
                                                      own view is excluded
                                                      from the analysis
                                                      (meaning only other
                                                      views will be saved
                                                      if they have a
                                                      persistence score of
                                                      10).
                                                      Default is False.
            """

            # Prepare request
            logger.debug(
                "Starting view analyzer for view '%s' in '%s'...",
                view["name"],
                view["space_name"],
            )
            space_name = view["space_name"]
            view_name = view["name"]
            url = (
                f"{self._base_url}/dwaas-core/advisor/{space_name}"
                f"/execute/{view_name}"
            )
            data = {
                "withMemoryAnalysis": False,
                "maximumMemoryConsumptionInGiB": 1,
            }
            response = await self.session.post(url=url, json=data)

            # Check for errors
            if not (
                response.status_code == 409
                and "taskAlreadyRunning" in response.text
            ) and not (
                response.status_code == 202 and "Running" in response.text
            ):
                logger.error(
                    "Error starting view analyzer for view '%s' in '%s'.",
                    view_name,
                    space_name,
                )
                return
            logger.info(
                "Started view analyzer for view '%s' in '%s'.",
                view_name,
                space_name,
            )

            # Update request ID
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )

            # Fetch logs of previous runs
            async def fetch_logs() -> list[dict]:
                response = await self.session.get(
                    url=f"{self._base_url}/dwaas-core/tf/{space_name}/logs",
                    params={"objectId": view_name, "getLocks": True},
                )
                return response.json()["logs"]

            # Wait for results
            latest_status = None
            while latest_status != "COMPLETED":
                logs = await fetch_logs()
                latest_status = logs[0]["status"]
                if latest_status == "FAILED":
                    logger.error(
                        "Error generating view analysis "
                        "for view '%s' in '%s'.",
                        view_name,
                        space_name,
                    )
                    return
                logger.debug(
                    "Waiting for results for view '%s' in '%s'...",
                    view_name,
                    space_name,
                )
                await asyncio.sleep(1)

            # Fetch logId of lastest run
            log_id: int = (await fetch_logs())[0]["logId"]

            # Update request ID
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )

            # Fetch results
            response = await self.session.get(
                url=(
                    f"{self._base_url}/dwaas-core/advisor"
                    f"/{space_name}/result/{log_id}"
                )
            )

            # Filter out view with best persistence score
            # (only one view can have score 10)
            # Filter out own view if needed
            # (else small views always receive a score of 10)
            entity_stats = response.json()["entityStats"]
            if filter_out_own_view:
                entity_stats = list(
                    filter(
                        lambda entity: entity["entity"] != view_name,
                        entity_stats,
                    )
                )
            best_view = list(
                filter(
                    lambda entity: entity.get("persistencyCandidateScore", 0)
                    == 10,
                    entity_stats,
                )
            )

            # Save view with score of 10, if found
            if best_view:
                logger.info(
                    "View '%s' in '%s' has a persistence score of 10.",
                    best_view[0]["entity"],
                    best_view[0]["space"],
                )
                candidate: PersistenceCandidate = {
                    "entity": best_view[0]["entity"],
                    "space": best_view[0]["space"],
                    "businessName": best_view[0]["businessName"],
                    "isPersisted": best_view[0]["isPersisted"],
                }
                candidates.append(candidate)
                if on_result is not None:
                    on_result(candidate)
            else:
                logger.debug("No view with a persistence score of 10 found.")

        # Start tasks
        await self._client.run_async_tasks(
            all_views, analyze_view, thread_count
        )
        return candidates

    async def create_partitioning_for_views(
        self,
        views: list[PartitionTask],
        partitions: list[str],
        overwrite_existing_partitions: bool = False,
        thread_count: int = 1,
        on_result: Callable[[PartitionCreateResult], None] | None = None,
    ) -> list[PartitionCreateResult]:
        """
        Creates partitions for the given views.

        Args:
            views (list[PartitionTask]): Views to create partitions for,
                                         each with the attribute to
                                         partition by.
            partitions (list[str]): List of all partitions to be created
                                    in the correct order.
                                    Example: ['0000', '2001', '2002', ...]
                                    Last value is the upper limit of the
                                    last partition (example:
                                    FISCYEAR < 2025). Therefore has to
                                    have at least two values.
            overwrite_existing_partitions (bool, optional): If True,
                                                            existing
                                                            partitions
                                                            will get
                                                            overwritten.
                                                            Otherwise
                                                            views with
                                                            existing
                                                            partitions
                                                            will be
                                                            skipped.
                                                            Default is
                                                            False.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            on_result (Callable | None, optional): Callback that is
                                                   invoked with each
                                                   result as soon as it
                                                   is available.
                                                   Defaults to None.

        Returns:
            list[PartitionCreateResult]: Outcome for each view.
        """

        # Update headers
        self.session.headers.update({"Accept": "*/*"})
        results: list[PartitionCreateResult] = []

        # Function to save a result and notify the caller
        def save_result(result: PartitionCreateResult) -> None:
            results.append(result)
            if on_result is not None:
                on_result(result)

        # Function to create partitions for a view
        async def create_partitioning_for_view(view) -> None:
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.get(
                url=f"{self._base_url}/dwaas-core/partitioning"
                f"/{view['space']}/persistedViews/{view['entity']}"
            )
            partition_exists = len(response.json()["ranges"]) > 0
            format_check = (
                response.json()["partitioningColumns"][view["attribute"]][
                    "type"
                ]
                == "cds.String"
            )

            # Check if column used for the partition is of type string
            if not format_check:
                logger.error(
                    "Attribute '%s' of view '%s' in '%s' is not of type "
                    "string. Skipping...",
                    view["attribute"],
                    view["entity"],
                    view["space"],
                )
                save_result(
                    {
                        "entity": view["entity"],
                        "space": view["space"],
                        "attribute": view["attribute"],
                        "createdPartition": False,
                    }
                )
                return

            # Save result and skip if partition already exists and should
            # not be overwritten
            if partition_exists and not overwrite_existing_partitions:
                logger.debug(
                    "View '%s' in '%s' is already partitioned. Skipping...",
                    view["entity"],
                    view["space"],
                )
                save_result(
                    {
                        "entity": view["entity"],
                        "space": view["space"],
                        "attribute": view["attribute"],
                        "createdPartition": True,
                    }
                )
                return

            # Create partitions
            logger.debug(
                "Creating partitions for view '%s' in '%s'...",
                view["entity"],
                view["space"],
            )
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            url = (
                f"{self._base_url}/dwaas-core/partitioning/{view['space']}"
                f"/persistedViews/{view['entity']}"
            )
            data = {
                "remoteSourceName": "",
                "objectName": view["entity"],
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
                "column": view["attribute"],
                "columnType": "cds.String",
                "runtimeDataCalculation": "designtime",
                "type": "range",
            }
            response = await self.session.post(url=url, json=data)

            # Save result
            if response.status_code == 201:
                logger.info(
                    "Created partitions for view '%s' in '%s'.",
                    view["entity"],
                    view["space"],
                )
            else:
                logger.error(
                    "Error creating partitions for view '%s' in '%s'.",
                    view["entity"],
                    view["space"],
                )
                logger.debug("Response: %s\n", response.text)
            save_result(
                {
                    "entity": view["entity"],
                    "space": view["space"],
                    "attribute": view["attribute"],
                    "createdPartition": response.status_code == 201,
                }
            )

        # Start tasks
        await self._client.run_async_tasks(
            views, create_partitioning_for_view, thread_count
        )
        return results

    async def remove_partitioning_for_views(
        self,
        views: list[ViewRef],
        thread_count: int = 1,
        on_result: Callable[[PartitionDeleteResult], None] | None = None,
    ) -> list[PartitionDeleteResult]:
        """
        Removes partitions for the given views.

        Args:
            views (list[ViewRef]): Views to remove partitions for.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            on_result (Callable | None, optional): Callback that is
                                                   invoked with each
                                                   result as soon as it
                                                   is available.
                                                   Defaults to None.

        Returns:
            list[PartitionDeleteResult]: Outcome for each view.
        """

        # Update headers
        self.session.headers.update({"Accept": "*/*"})
        results: list[PartitionDeleteResult] = []

        # Function to save a result and notify the caller
        def save_result(result: PartitionDeleteResult) -> None:
            results.append(result)
            if on_result is not None:
                on_result(result)

        # Function to remove partitions for a view
        async def remove_partitioning_for_view(view) -> None:
            logger.debug(
                "Removing partitions for view '%s' in '%s'...",
                view["entity"],
                view["space"],
            )
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.delete(
                url=f"{self._base_url}/dwaas-core/partitioning"
                f"/{view['space']}/persistedViews/{view['entity']}"
            )

            # Check for errors
            if response.status_code != 200:
                logger.error(
                    "Error removing partitions for view '%s' in '%s'.",
                    view["entity"],
                    view["space"],
                )
                save_result(
                    {
                        "entity": view["entity"],
                        "space": view["space"],
                        "removedPartition": False,
                    }
                )
                return

            # Save result
            logger.info(
                "Removed partitions for view '%s' in '%s'.",
                view["entity"],
                view["space"],
            )
            save_result(
                {
                    "entity": view["entity"],
                    "space": view["space"],
                    "removedPartition": True,
                }
            )

        # Start tasks
        await self._client.run_async_tasks(
            views,
            remove_partitioning_for_view,
            thread_count,
        )
        return results

    async def persist_views(
        self,
        views: list[ViewRef],
        thread_count: int = 1,
        timer: bool = False,
        on_result: Callable[[PersistResult], None] | None = None,
    ) -> list[PersistResult]:
        """
        Persists views. Threads can be used in small amounts, otherwise
        rate limits may occur. Five threads have been run successfully.

        Args:
            views (list[ViewRef]): Views to persist.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            timer (bool, optional): If True, the duration of the
                                    persistence run is saved.
                                    Default is False.
            on_result (Callable | None, optional): Callback that is
                                                   invoked with each
                                                   result as soon as it
                                                   is available (e.g. to
                                                   save results
                                                   incrementally during
                                                   long runs).
                                                   Defaults to None.

        Returns:
            list[PersistResult]: Outcome for each view.
        """

        # Update headers
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )
        results: list[PersistResult] = []

        # Function to persist a view
        async def persist_one(view) -> None:
            success, log_details = await self.persist_view(
                view["entity"], view["space"]
            )
            runtime = round(log_details.get("runTime", 0) / 1000)

            # Save result and notify caller
            result: PersistResult = {
                "entity": view["entity"],
                "space": view["space"],
                "isPersisted": success,
                "runtime": (
                    runtime if timer and success and runtime > 0 else None
                ),
            }
            results.append(result)
            if on_result is not None:
                on_result(result)

        # Start tasks
        await self._client.run_async_tasks(
            views, persist_one, thread_count
        )
        return results

    async def persist_view(
        self, view_name: str, view_space: str
    ) -> tuple[bool, dict]:
        """
        Persists a view. Does not check if the view is already persisted.

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
        url = f"{self._base_url}/dwaas-core/tf/directexecute"
        data = {
            "applicationId": "VIEWS",
            "spaceId": view_space,
            "objectId": view_name,
            "activity": "PERSIST",
        }
        response = await self.session.post(url=url, json=data)

        # Check for errors and parse taskLogId
        if response.status_code != 202:
            logger.error(
                "Error starting persistence for view '%s' in '%s'. "
                "Skipping...",
                view_name,
                view_space,
            )
            return False, {}
        log_id = response.json()["taskLogId"]

        # Function to fetch log details
        async def fetch_log_details() -> dict:
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.get(
                url=(
                    f"{self._base_url}/dwaas-core/tf"
                    f"/{view_space}/extendedlogs/{log_id}"
                )
            )
            return response.json()["logDetails"]

        # Wait for results
        log_details = {}
        while True:
            log_details = await fetch_log_details()
            latest_status = log_details["status"]
            if latest_status == "COMPLETED":
                break
            if latest_status == "FAILED" or (
                latest_status != "COMPLETED" and latest_status != "RUNNING"
            ):
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

    async def unpersist_views(
        self,
        views: list[ViewRef],
        thread_count: int = 1,
        on_result: Callable[[UnpersistResult], None] | None = None,
    ) -> list[UnpersistResult]:
        """
        Removes persistences for views. Threads can be used in small
        amounts, otherwise rate limits may occur.
        Five threads have been run successfully.

        Args:
            views (list[ViewRef]): Views to unpersist.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            on_result (Callable | None, optional): Callback that is
                                                   invoked with each
                                                   result as soon as it
                                                   is available.
                                                   Defaults to None.

        Returns:
            list[UnpersistResult]: Outcome for each view.
        """

        # Update headers
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )
        results: list[UnpersistResult] = []

        # Function to unpersist a view
        async def unpersist_one(view) -> None:
            success, _ = await self.unpersist_view(
                view["entity"], view["space"]
            )

            # Save result and notify caller
            result: UnpersistResult = {
                "entity": view["entity"],
                "space": view["space"],
                "isRemoved": success,
            }
            results.append(result)
            if on_result is not None:
                on_result(result)

        # Start tasks
        await self._client.run_async_tasks(
            views, unpersist_one, thread_count
        )
        return results

    async def unpersist_view(
        self, view_name: str, view_space: str
    ) -> tuple[bool, dict]:
        """
        Removes the persistence for a view. Checks if view is already
        persisted.

        Args:
            view_name (str): Name of the view.
            view_space (str): Name of the view space.

        Returns:
            tuple[bool, dict]: True if persistence was removed
                               successfully, otherwise False. Dictionary
                               with log details.
        """

        # Check if view is persisted
        url = (
            f"{self._base_url}/dwaas-core/monitor/{view_space}"
            f"/persistedViews/{view_name}"
        )
        response = await self.session.get(url=url)
        if (
            response.status_code != 200
            or "dataPersistency" not in response.json()
        ):
            logger.error(
                "Error checking if view '%s' in '%s' is persisted. "
                "Status code: %s. Skipping...",
                view_name,
                view_space,
                response.status_code,
            )
            return False, {}
        if response.json()["dataPersistency"] != "Persisted":
            logger.debug(
                "View '%s' in '%s' is not persisted. Skipping...",
                view_name,
                view_space,
            )
            return True, {}

        # Remove persistence
        logger.debug(
            "Removing persistence for view '%s' in '%s'...",
            view_name,
            view_space,
        )
        self.session.headers.update(
            {"x-request-id": str(uuid4()).replace("-", "")}
        )
        url = f"{self._base_url}/dwaas-core/tf/directexecute"
        data = {
            "applicationId": "VIEWS",
            "spaceId": view_space,
            "objectId": view_name,
            "activity": "REMOVE_PERSISTED_DATA",
        }
        response = await self.session.post(url=url, json=data)

        # Check for errors and parse taskLogId
        if response.status_code != 202:
            logger.error(
                "Error removing persistence for view '%s' in '%s'. "
                "Skipping...",
                view_name,
                view_space,
            )
            return False, {}
        log_id = response.json()["taskLogId"]

        # Function to fetch log details
        async def fetch_log_details() -> dict:
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.get(
                url=(
                    f"{self._base_url}/dwaas-core/tf"
                    f"/{view_space}/extendedlogs/{log_id}"
                )
            )
            return response.json()["logDetails"]

        # Wait for results
        log_details = {}
        while True:
            log_details = await fetch_log_details()
            latest_status = log_details["status"]
            if latest_status == "COMPLETED":
                break
            if latest_status == "FAILED" or (
                latest_status != "COMPLETED" and latest_status != "RUNNING"
            ):
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

    async def lock_partitions_until_year(
        self,
        views: list[ViewRef],
        year: int,
        thread_count: int = 1,
        on_result: Callable[[PartitionLockResult], None] | None = None,
    ) -> list[PartitionLockResult]:
        """
        Locks partitions for the given views. Skips views without
        partitions.
        All partitions have to be integers!!

        Args:
            views (list[ViewRef]): Views to lock partitions for.
            year (int): Year up to which partitions should be locked
                        (including the year itself).
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            on_result (Callable | None, optional): Callback that is
                                                   invoked with each
                                                   result as soon as it
                                                   is available.
                                                   Defaults to None.

        Returns:
            list[PartitionLockResult]: Outcome for each view with
                                       partitions. Views without
                                       partitions are skipped.
        """

        # Update headers
        self.session.headers.update({"Accept": "*/*"})
        results: list[PartitionLockResult] = []

        # Function to save a result and notify the caller
        def save_result(result: PartitionLockResult) -> None:
            results.append(result)
            if on_result is not None:
                on_result(result)

        # Function to lock partitions for a view
        async def lock_partitions_for_view(view) -> None:
            # Check if partition already exists
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.get(
                url=f"{self._base_url}/dwaas-core/partitioning"
                f"/{view['space']}/persistedViews/{view['entity']}"
            )
            partition_exists = len(response.json()["ranges"]) > 0

            # Check for errors
            if not partition_exists:
                logger.error(
                    "View %s in %s has no partitions. Skipping...",
                    view["entity"],
                    view["space"],
                )
                return

            # Fetch details of the view
            view_data = response.json()

            # Lock partitions
            logger.debug(
                "Locking partitions for view '%s' in '%s' up to (including) "
                "year %s...",
                view["entity"],
                view["space"],
                year,
            )
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            url = (
                f"{self._base_url}/dwaas-core/partitioning/{view['space']}"
                f"/persistedViews/{view['entity']}"
            )
            data = {
                "remoteSourceName": view_data["remoteSourceName"],
                "objectName": view_data["objectName"],
                "numParallelPartitions": view_data["numParallelPartitions"],
                "ranges": view_data["ranges"],
                "column": view_data["column"],
                "columnType": view_data["columnType"],
                "runtimeDataCalculation": view_data["runtimeDataCalculation"],
                "type": view_data["type"],
            }
            for partition in data["ranges"]:
                if int(partition["low"]["value"]) <= year:
                    partition["locked"] = True
            response = await self.session.post(url=url, json=data)

            # Save result
            if response.status_code == 201:
                logger.info(
                    "Locked partitions for view '%s' in '%s' "
                    "up to (and including) year %s.",
                    view["entity"],
                    view["space"],
                    year,
                )
            else:
                logger.error(
                    "Error locking partitions for view '%s' in '%s'.",
                    view["entity"],
                    view["space"],
                )
                logger.debug("Response: %s\n", response.text)
            save_result(
                {
                    "entity": view["entity"],
                    "space": view["space"],
                    "lockedPartitions": response.status_code == 201,
                }
            )

        # Start tasks
        await self._client.run_async_tasks(
            views, lock_partitions_for_view, thread_count
        )
        return results

    async def unlock_all_partitions(
        self,
        views: list[ViewRef],
        thread_count: int = 1,
        on_result: Callable[[PartitionUnlockResult], None] | None = None,
    ) -> list[PartitionUnlockResult]:
        """
        Unlocks all partitions for the given views.

        Args:
            views (list[ViewRef]): Views to unlock partitions for.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            on_result (Callable | None, optional): Callback that is
                                                   invoked with each
                                                   result as soon as it
                                                   is available.
                                                   Defaults to None.

        Returns:
            list[PartitionUnlockResult]: Outcome for each view with
                                         partitions. Views without
                                         partitions are skipped.
        """

        # Update headers
        self.session.headers.update({"Accept": "*/*"})
        results: list[PartitionUnlockResult] = []

        # Function to save a result and notify the caller
        def save_result(result: PartitionUnlockResult) -> None:
            results.append(result)
            if on_result is not None:
                on_result(result)

        # Function to unlock all partitions for a view
        async def unlock_partitions_for_view(view) -> None:
            # Check if view has partitions
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.get(
                url=f"{self._base_url}/dwaas-core/partitioning"
                f"/{view['space']}/persistedViews/{view['entity']}"
            )
            partition_exists = len(response.json()["ranges"]) > 0

            # Check for errors
            if not partition_exists:
                logger.error(
                    "View '%s' in '%s' has no partitions. Skipping...",
                    view["entity"],
                    view["space"],
                )
                return

            # Fetch view data
            view_data = response.json()

            # Unlock partitions
            logger.debug(
                "Unlocking all partitions of view '%s' in '%s'...",
                view["entity"],
                view["space"],
            )
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            url = (
                f"{self._base_url}/dwaas-core/partitioning/{view['space']}"
                f"/persistedViews/{view['entity']}"
            )
            data = {
                "remoteSourceName": view_data["remoteSourceName"],
                "objectName": view_data["objectName"],
                "numParallelPartitions": view_data["numParallelPartitions"],
                "ranges": view_data["ranges"],
                "column": view_data["column"],
                "columnType": view_data["columnType"],
                "runtimeDataCalculation": view_data["runtimeDataCalculation"],
                "type": view_data["type"],
            }
            for partition in data["ranges"]:
                partition["locked"] = False
            response = await self.session.post(url=url, json=data)

            # Save result
            if response.status_code == 201:
                logger.info(
                    "Unlocked all partitions for view '%s' in '%s'.",
                    view["entity"],
                    view["space"],
                )
            else:
                logger.error(
                    "Error unlocking partitions for view '%s' in '%s'.",
                    view["entity"],
                    view["space"],
                )
                logger.debug("Response: %s\n", response.text)
            save_result(
                {
                    "entity": view["entity"],
                    "space": view["space"],
                    "unlockedPartitions": response.status_code == 201,
                }
            )

        # Start tasks
        await self._client.run_async_tasks(
            views, unlock_partitions_for_view, thread_count
        )
        return results
