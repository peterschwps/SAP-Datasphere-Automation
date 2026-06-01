import asyncio
import contextlib
import csv
from json.decoder import JSONDecodeError
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx
import pandas as pd

from datasphere.automation import DatasphereAutomation
from utils.filehandler import ALL_FILES, settings
from utils.logging import logger
from utils.types import ViewDetailsDict

# Important URLs from settings
DATASPHERE_URL: str = settings["Setup"]["DATASPHERE_URL"]


class Views(DatasphereAutomation):
    def __init__(self, session: httpx.AsyncClient | None = None):
        if session is not None:
            self.session = session
        else:
            super().__init__()

    async def initialize(self) -> None:
        """
        Initializes the Datasphere session.
        """
        self.session: httpx.AsyncClient = await (
            self.initialize_datasphere_session()
        )

    async def _get_all_views(self) -> list[ViewDetailsDict]:
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
                "UI5-Timezone": "Europe/Berlin",
                "UI5-Timepattern": "H%3Amm%3Ass",
                "UI5-Datepattern": "dd.MM.yyyy",
                "Cache-Control": "no-cache",
            }
        )

        # Prepare request
        url = f"{DATASPHERE_URL}/deepsea/repository/search/$all"
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
        for header in (
            "UI5-Timezone",
            "UI5-Timepattern",
            "UI5-Datepattern",
            "Cache-Control",
        ):
            with contextlib.suppress(KeyError):
                self.session.headers.pop(header)

        return all_views

    async def get_all_views_where_attribute_contains(
        self, word: str, thread_count: int = 1
    ) -> None:
        """
        Retrieves all views with an attribute that contains the search word
        and saves it as a csv file.

        Args:
            word (str): Search word (case-insensitive).
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """
        # Fetch all views
        all_views = await self._get_all_views()

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
                url=f"{DATASPHERE_URL}/deepsea/repository"
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

            # Write view to file
            # if attribute containing search word is found
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
                    with open(
                        ALL_FILES["VIEW_ATTRIBUTE"]["absolute_path"],
                        "a",
                        newline="",
                        encoding="utf-8",
                    ) as file:
                        writer = csv.DictWriter(
                            file,
                            fieldnames=ALL_FILES["VIEW_ATTRIBUTE"]["columns"],
                        )
                        values = {
                            "entity": view["name"],
                            "space": view["space_name"],
                            "businessName": view["business_name"],
                            "attribute": attribute,
                        }
                        writer.writerow(values)

        # Start tasks
        await self.run_async_tasks(
            all_views, check_view_for_attribute_with_substring, thread_count
        )

        # Final logging with file path
        file_name = ALL_FILES["VIEW_ATTRIBUTE"]["absolute_path"]
        logger.info("Results saved to '%s'.", file_name)

    async def create_view_analytics(self, thread_count: int = 1) -> None:
        """
        Creates view analytics for all views. Threads can be used in small
        amounts, otherwise rate limits may occur.
        Five threads have been run successfully.

        Args:
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """

        # Fetch all views
        all_views = await self._get_all_views()

        # Update headers
        self.session.headers.update(
            {
                "x-request-id": str(uuid4()).replace("-", ""),
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
            }
        )

        async def create_view_analytics(
            view: ViewDetailsDict,
            filter_out_own_view: bool = False,
        ) -> None:
            """
            Runs the view analyzer and writes all views with a persistence
            score of 10 to the results file.

            Args:
                view (ViewDetailsDict): View to analyze.
                filter_out_own_view (bool, optional): If True, the
                                                      own view is excluded from
                                                      the analysis (meaning
                                                      only other views will be
                                                      saved if they have a
                                                      persistence score of 10).
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
                f"{DATASPHERE_URL}/dwaas-core/advisor/{space_name}"
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
                    url=f"{DATASPHERE_URL}/dwaas-core/tf/{space_name}/logs",
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
                    f"{DATASPHERE_URL}/dwaas-core/advisor"
                    f"/{space_name}/result/{log_id}"
                )
            )

            # Filter out view with best persistence score
            # (only one view can have score 10)
            # Filter out own view if neededelse small views
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

            # Write view with score of 10 to file, if found
            if best_view:
                logger.info(
                    "View '%s' in '%s' has a persistence score of 10.",
                    best_view[0]["entity"],
                    best_view[0]["space"],
                )
                with open(
                    ALL_FILES["VIEW_ANALYSE"]["absolute_path"],
                    "a",
                    newline="",
                ) as file:
                    writer = csv.DictWriter(
                        file,
                        fieldnames=ALL_FILES["VIEW_ANALYSE"]["columns"],
                    )
                    writer.writerow(
                        {
                            key: best_view[0][key]
                            for key in ALL_FILES["VIEW_ANALYSE"]["columns"]
                        }
                    )
            else:
                logger.debug("No view with a persistence score of 10 found.")

        # Start tasks
        await self.run_async_tasks(
            all_views, create_view_analytics, thread_count
        )

        # Final logging with file path
        file_name = ALL_FILES["VIEW_ANALYSE"]["absolute_path"]
        logger.info("Results saved to '%s'.", file_name)

    async def create_partitioning_for_views(
        self,
        partitions: list[str],
        overwrite_existing_partitions: bool = False,
        thread_count: int = 1,
    ) -> None:
        """
        Creates partitions for all views in 'views_to_partition.csv'.
        Requires the task file VIEW_PARTITIONING_CREATE.
        Writes results to VIEW_PARTITIONING_CREATE_RESULT.

        Args:
            partitions (list[str]): List of all partitions to be created
                                    in the correct order.
                                    Example: ['0000', '2001', '2002', ...]
                                    Last value is the upper limit of the last
                                    partition (example: FISCYEAR < 2025).
                                    Therefore has to have at least two values.
            overwrite_existing_partitions (bool, optional): If True, existing
                                                            partitions will get
                                                            overwritten.
                                                            Otherwise views
                                                            with existing
                                                            partitions will be
                                                            skipped.
                                                            Default is False.
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """

        # Read task file
        views_to_partition = []
        with open(
            ALL_FILES["VIEW_PARTITIONING_CREATE"]["absolute_path"],
            newline="",
            encoding="utf-8",
        ) as file:
            reader = csv.DictReader(
                file,
                fieldnames=ALL_FILES["VIEW_PARTITIONING_CREATE"]["columns"],
            )
            views_to_partition = list(reader)[1:]

        # Update headers
        self.session.headers.update({"Accept": "*/*"})

        # Function to check if a view has an existing partition
        async def create_partitioning_for_view(view) -> None:
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.get(
                url=f"{DATASPHERE_URL}/dwaas-core/partitioning"
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
                with open(
                    ALL_FILES["VIEW_PARTITIONING_CREATE_RESULT"][
                        "absolute_path"
                    ],
                    "a",
                    newline="",
                    encoding="utf-8",
                ) as file:
                    writer = csv.DictWriter(
                        file,
                        fieldnames=ALL_FILES[
                            "VIEW_PARTITIONING_CREATE_RESULT"
                        ]["columns"],
                    )
                    values = {
                        "entity": view["entity"],
                        "space": view["space"],
                        "attribute": view["attribute"],
                        "createdPartition": False,
                    }
                    writer.writerow(values)
                return

            # Write to results file and skip if partition already
            # exists and should not be overwritten
            if partition_exists and not overwrite_existing_partitions:
                logger.debug(
                    "View '%s' in '%s' is already partitioned. Skipping...",
                    view["entity"],
                    view["space"],
                )
                with open(
                    ALL_FILES["VIEW_PARTITIONING_CREATE_RESULT"][
                        "absolute_path"
                    ],
                    "a",
                    newline="",
                    encoding="utf-8",
                ) as file:
                    writer = csv.DictWriter(
                        file,
                        fieldnames=ALL_FILES[
                            "VIEW_PARTITIONING_CREATE_RESULT"
                        ]["columns"],
                    )
                    values = {
                        "entity": view["entity"],
                        "space": view["space"],
                        "attribute": view["attribute"],
                        "createdPartition": True,
                    }
                    writer.writerow(values)
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
                f"{DATASPHERE_URL}/dwaas-core/partitioning/{view['space']}"
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

            # Write to file
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
            with open(
                ALL_FILES["VIEW_PARTITIONING_CREATE_RESULT"]["absolute_path"],
                "a",
                newline="",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=ALL_FILES["VIEW_PARTITIONING_CREATE_RESULT"][
                        "columns"
                    ],
                )
                values = {
                    "entity": view["entity"],
                    "space": view["space"],
                    "attribute": view["attribute"],
                    "createdPartition": response.status_code == 201,
                }
                writer.writerow(values)

        # Start tasks
        await self.run_async_tasks(
            views_to_partition, create_partitioning_for_view, thread_count
        )

        # Final logging with file path
        file_name = ALL_FILES["VIEW_PARTITIONING_CREATE_RESULT"][
            "absolute_path"
        ]
        logger.info("Results saved to '%s'.", file_name)

    async def remove_partitioning_for_views(
        self, thread_count: int = 1
    ) -> None:
        """
        Removes partitions for all views in 'views_to_delete_partition.csv'.
        Requires the task file VIEW_PARTITIONING_DELETE.
        Writes results to VIEW_PARTITIONING_DELETE_RESULT.

        Args:
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """

        # Read task file
        views_to_delete_partition = []
        with open(
            ALL_FILES["VIEW_PARTITIONING_DELETE"]["absolute_path"],
            newline="",
            encoding="utf-8",
        ) as file:
            reader = csv.DictReader(
                file,
                fieldnames=ALL_FILES["VIEW_PARTITIONING_DELETE"]["columns"],
            )
            views_to_delete_partition = list(reader)[1:]

        # Update headers
        self.session.headers.update({"Accept": "*/*"})

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
                url=f"{DATASPHERE_URL}/dwaas-core/partitioning"
                f"/{view['space']}/persistedViews/{view['entity']}"
            )

            # Check for errors
            if response.status_code != 200:
                logger.error(
                    "Error removing partitions for view '%s' in '%s'.",
                    view["entity"],
                    view["space"],
                )
                return

            # Write to results file
            logger.info(
                "Removed partitions for view '%s' in '%s'.",
                view["entity"],
                view["space"],
            )
            with open(
                ALL_FILES["VIEW_PARTITIONING_DELETE_RESULT"]["absolute_path"],
                "a",
                newline="",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=ALL_FILES["VIEW_PARTITIONING_DELETE_RESULT"][
                        "columns"
                    ],
                )
                values = {
                    "entity": view["entity"],
                    "space": view["space"],
                    "removedPartition": True,
                }
                writer.writerow(values)

        # Start tasks
        await self.run_async_tasks(
            views_to_delete_partition,
            remove_partitioning_for_view,
            thread_count,
        )

        # Final logging with file path
        file_name = ALL_FILES["VIEW_PARTITIONING_DELETE_RESULT"][
            "absolute_path"
        ]
        logger.info("Results saved to '%s'.", file_name)

    async def persist_views(
        self,
        thread_count: int = 1,
        timer: bool = False,
    ) -> None:
        """
        Persists views. Threads can be used in small amounts, otherwise rate
        limits may occur. Five threads have been run successfully.
        Requires the task file VIEW_PERSIST.
        Writes results to VIEW_PERSIST_RESULT.

        Args:
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
            timer (bool, optional): If True, the duration of the persistence
                                    run is saved. Default is False.
        """

        # Read task file
        views_to_persist = []
        with open(
            ALL_FILES["VIEW_PERSIST"]["absolute_path"], newline=""
        ) as file:
            reader = csv.DictReader(
                file,
                fieldnames=ALL_FILES["VIEW_PERSIST"]["columns"],
            )
            views_to_persist = list(reader)[1:]

        # Pre-fill results file with values
        with open(
            ALL_FILES["VIEW_PERSIST_RESULT"]["absolute_path"],
            "a",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=ALL_FILES["VIEW_PERSIST_RESULT"]["columns"],
            )
            for view in views_to_persist:
                values = {
                    "entity": view["entity"],
                    "space": view["space"],
                    "isPersisted": False,
                    "runtime": None,
                }
                writer.writerow(values)

        # Update headers
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )

        # Function to persist a view
        async def persist_view(view):
            success, log_details = await self._persist_view(
                view["entity"], view["space"]
            )
            runtime = round(log_details.get("runTime", 0) / 1000)

            # Update results file (read in file first, then write the whole
            # file again to update the corresponding row)
            if success:
                df = pd.read_csv(
                    ALL_FILES["VIEW_PERSIST_RESULT"]["absolute_path"]
                )
                df.loc[
                    (df["entity"] == view["entity"])
                    & (df["space"] == view["space"]),
                    "isPersisted",
                ] = True
                df.to_csv(
                    ALL_FILES["VIEW_PERSIST_RESULT"]["absolute_path"],
                    index=False,
                )

                # Update runtime if it should be measured
                # (read in file first, then write the whole file again
                # to update the corresponding row)
                if timer and runtime > 0:
                    df = pd.read_csv(
                        ALL_FILES["VIEW_PERSIST_RESULT"]["absolute_path"],
                        dtype={"runtime": "Int64"},
                    )
                    df.loc[
                        (df["entity"] == view["entity"])
                        & (df["space"] == view["space"]),
                        "runtime",
                    ] = runtime
                    df.to_csv(
                        ALL_FILES["VIEW_PERSIST_RESULT"]["absolute_path"],
                        index=False,
                    )

        # Start tasks
        await self.run_async_tasks(
            views_to_persist, persist_view, thread_count
        )

        # Final logging with file path
        file_name = ALL_FILES["VIEW_PERSIST_RESULT"]["absolute_path"]
        logger.info("Results saved to '%s'.", file_name)

    async def _persist_view(
        self, view_name: str, view_space: str
    ) -> tuple[bool, dict]:
        """
        Persists a view. Does not check if the view is already persisted.

        Args:
            view_name (str): Name of the view.
            view_space (str): Name of the view space.

        Returns:
            tuple[bool, dict]: True if persistence was successful, otherwise
                               False. Dict with log details.
        """

        # Start persistence
        logger.debug(
            "Starting persistence of view '%s' in '%s'...",
            view_name,
            view_space,
        )
        url = f"{DATASPHERE_URL}/dwaas-core/tf/directexecute"
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
                    f"{DATASPHERE_URL}/dwaas-core/tf/{view_space}/extendedlogs/{log_id}"
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

        # Update results file (read in file first, then write the whole file
        # again to update the corresponding row)
        logger.info(
            "Completed persistence for view '%s' in '%s'.",
            view_name,
            view_space,
        )
        return True, log_details

    async def unpersist_views(self, thread_count: int = 1) -> None:
        """
        Removes persistences for views. Threads can be used in small amounts,
        otherwise rate limits may occur.
        Five threads have been run successfully.
        Requires the task file VIEW_UNPERSIST.
        Writes results to VIEW_UNPERSIST_RESULT.

        Args:
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """

        # Read task file
        views_to_unpersist = []
        with open(
            ALL_FILES["VIEW_UNPERSIST"]["absolute_path"], newline=""
        ) as file:
            reader = csv.DictReader(
                file,
                fieldnames=ALL_FILES["VIEW_UNPERSIST"]["columns"],
            )
            views_to_unpersist = list(reader)[1:]

        # Pre-fill results file with values
        with open(
            ALL_FILES["VIEW_UNPERSIST_RESULT"]["absolute_path"],
            "a",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=ALL_FILES["VIEW_UNPERSIST_RESULT"]["columns"],
            )
            for view in views_to_unpersist:
                values = {
                    "entity": view["entity"],
                    "space": view["space"],
                    "isRemoved": False,
                }
                writer.writerow(values)

        # Update headers
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )

        # Function to unpersist a view
        async def unpersist_view(view):
            success, _ = await self._unpersist_view(
                view["entity"], view["space"]
            )

            # Update results file (read in file first, then write the whole
            # file again to update the corresponding row)
            if success:
                df = pd.read_csv(
                    ALL_FILES["VIEW_UNPERSIST_RESULT"]["absolute_path"]
                )
                df.loc[
                    (df["entity"] == view["entity"])
                    & (df["space"] == view["space"]),
                    "isRemoved",
                ] = True
                df.to_csv(
                    ALL_FILES["VIEW_UNPERSIST_RESULT"]["absolute_path"],
                    index=False,
                )

        # Start tasks
        await self.run_async_tasks(
            views_to_unpersist, unpersist_view, thread_count
        )

        # Final logging with file path
        file_name = ALL_FILES["VIEW_UNPERSIST_RESULT"]["absolute_path"]
        logger.info("Results saved to '%s'.", file_name)

    async def _unpersist_view(
        self, view_name: str, view_space: str
    ) -> tuple[bool, dict]:
        """
        Removes the persistence for a view. Checks if view is already
        persisted.

        Args:
            view_name (str): Name of the view.
            view_space (str): Name of the view space.

        Returns:
            tuple[bool, dict]: True if persistence was removed successfully,
                               otherwise False. Dictionary with log details.
        """

        # Check if view is persisted
        url = (
            f"{DATASPHERE_URL}/dwaas-core/monitor/{view_space}"
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
        url = f"{DATASPHERE_URL}/dwaas-core/tf/directexecute"
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
                    f"{DATASPHERE_URL}/dwaas-core/tf"
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

        # Update results file
        logger.info(
            "Removed persistence for view '%s' in '%s'.", view_name, view_space
        )
        return True, log_details

    async def lock_partitions_until_year(
        self, year: int, thread_count: int = 1
    ) -> None:
        """
        Locks partitions for all views in 'views_to_lock_partitions.csv'.
        Skips views without partitions.
        All partitions have to be integers!!
        Requires the task file VIEW_PARTITION_LOCK.
        Writes results to VIEW_PARTITION_LOCK_RESULT.

        Args:
            year (int): Year up to which partitions should be locked
                        (including the year itself).
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """

        # Read task file
        views_to_lock = []
        with open(
            ALL_FILES["VIEW_PARTITION_LOCK"]["absolute_path"],
            newline="",
        ) as file:
            reader = csv.DictReader(
                file,
                fieldnames=ALL_FILES["VIEW_PARTITION_LOCK"]["columns"],
            )
            views_to_lock = list(reader)[1:]

        # Update headers
        self.session.headers.update({"Accept": "*/*"})

        # Function to lock partitions for a view
        async def lock_partitions_for_view(view) -> None:
            # Check if partition already exists
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.get(
                url=f"{DATASPHERE_URL}/dwaas-core/partitioning"
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
                f"{DATASPHERE_URL}/dwaas-core/partitioning/{view['space']}"
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

            # Write to results file
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
            with open(
                ALL_FILES["VIEW_PARTITION_LOCK_RESULT"]["absolute_path"],
                "a",
                newline="",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=ALL_FILES["VIEW_PARTITION_LOCK_RESULT"][
                        "columns"
                    ],
                )
                values = {
                    "entity": view["entity"],
                    "space": view["space"],
                    "lockedPartitions": response.status_code == 201,
                }
                writer.writerow(values)

        # Start tasks
        await self.run_async_tasks(
            views_to_lock, lock_partitions_for_view, thread_count
        )

        # Final logging with file path
        file_name = ALL_FILES["VIEW_PARTITION_LOCK_RESULT"]["absolute_path"]
        logger.info("Results saved to '%s'.", file_name)

    async def unlock_all_partitions(self, thread_count: int = 1) -> None:
        """
        Unlocks all partitions for all views in
        'views_to_unlock_partitions.csv'.
        Requires the task file VIEW_PARTITION_UNLOCK.
        Writes results to VIEW_PARTITION_UNLOCK_RESULT.

        Args:
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """

        # Read task file
        views_to_unlock = []
        with open(
            ALL_FILES["VIEW_PARTITION_UNLOCK"]["absolute_path"],
            newline="",
        ) as file:
            reader = csv.DictReader(
                file,
                fieldnames=ALL_FILES["VIEW_PARTITION_UNLOCK"]["columns"],
            )
            views_to_unlock = list(reader)[1:]

        # Update headers
        self.session.headers.update({"Accept": "*/*"})

        # Function to unlock all partitions for a view
        async def unlock_partitions_for_view(view) -> None:
            # Check if view has partitions
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.get(
                url=f"{DATASPHERE_URL}/dwaas-core/partitioning"
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
                f"{DATASPHERE_URL}/dwaas-core/partitioning/{view['space']}"
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

            # Write to results file
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
            with open(
                ALL_FILES["VIEW_PARTITION_UNLOCK_RESULT"]["absolute_path"],
                "a",
                newline="",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=ALL_FILES["VIEW_PARTITION_UNLOCK_RESULT"][
                        "columns"
                    ],
                )
                values = {
                    "entity": view["entity"],
                    "space": view["space"],
                    "unlockedPartitions": response.status_code == 201,
                }
                writer.writerow(values)

        # Start tasks
        await self.run_async_tasks(
            views_to_unlock, unlock_partitions_for_view, thread_count
        )

        # Final logging with file path
        file_name = ALL_FILES["VIEW_PARTITION_UNLOCK_RESULT"]["absolute_path"]
        logger.info("Results saved to '%s'.", file_name)
