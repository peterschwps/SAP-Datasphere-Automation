import asyncio
import csv
import json
from copy import deepcopy
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx

from datasphere.automation import DatasphereAutomation
from datasphere.views import Views
from utils.filehandler import ALL_FILES, settings
from utils.logging import logger
from utils.types import AnalyticalModelsDetailsDict

# Important conditions from settings
URL_TO_USE: str = settings["Setup"]["URL_TO_USE"]

# Important URLs from settings
DATASPHERE_URL: str = settings["URLs"][URL_TO_USE]


class AnalyticalModels(DatasphereAutomation):
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

    async def _get_all_analytical_models(
        self,
    ) -> list[AnalyticalModelsDetailsDict]:
        """
        Returns all analytical models as a list of dictionaries.

        Returns:
            list[AnalyticalModelsDetailsDict]: List of dictionaries with the
                                               analytical models.
        """

        # Update headers
        self.session.headers.pop("X-Csrf-Token")
        self.session.headers.pop("X-Requested-With")
        self.session.headers.pop("Priority")
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

        # Fetch all analytical models
        url = f"{DATASPHERE_URL}/deepsea/repository/search/$all"
        params = {
            "$top": 1000,  # can't be omitted, else request won't work
            "$skip": 0,
            "whyfound": "true",
            "$count": "true",
            "valuehierarchy": "folder_id",
            "facets": "all",
            "facetlimit": 5,
            "$apply": (
                "filter(Search.search(query='SCOPE:SEARCH_DESIGN "
                '(technical_type_description:EQ(S):"Analysemodell" AND '
                '(technical_type:EQ(S):"DWC_REMOTE_TABLE" OR technical_type:'
                'EQ(S):"DWC_LOCAL_TABLE" OR technical_type:EQ(S):"DWC_VIEW" '
                'OR technical_type:EQ(S):"DWC_ERMODEL" OR technical_type:'
                'EQ(S):"DWC_DATAFLOW" OR technical_type:EQ(S):"DWC_IDT" OR '
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
        response = await self.session.get(
            url=f"{url}?{urlencode(params, safe='()*', quote_via=quote)}"
        )
        all_analytical_models: list[AnalyticalModelsDetailsDict] = (
            response.json()["value"]
        )

        # Remove unnecessary headers for next requests
        self.session.headers.pop("Origin")
        self.session.headers.pop("UI5-Timezone")
        self.session.headers.pop("UI5-Timepattern")
        self.session.headers.pop("UI5-Datepattern")
        self.session.headers.pop("Cache-Control")

        return all_analytical_models

    async def _get_all_analytical_models_from_space(
        self, space_name: str
    ) -> list[AnalyticalModelsDetailsDict]:
        """
        Returns all analytical models of a specific space.

        Args:
            space_name (str): Name of the space.

        Returns:
            list[AnalyticalModelsDetailsDict]: List of dictionaries with the
                                               analytical models.
        """

        # Fetch all analytical models
        all_analytical_models_in_space = [
            model
            for model in await self._get_all_analytical_models()
            if model["space_name"] == space_name
        ]
        return all_analytical_models_in_space

    async def _get_all_views_for_analytical_model(
        self, analytical_model_id: str
    ) -> dict[str, dict[str, str]]:
        """
        Returns all views that are used in an analytical model.

        Args:
            analytical_model_id (str): ID of the analytical model.

        Returns:
            dict[str, dict[str, str]]: Dictionary with analytical model ID as
                                       key and dictionary as value.
                                       This dictionary has view IDs as keys and
                                       view names as values.
        """

        # Update headers
        # (if _get_all_analytical_models() was called before)
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )

        # Fetch details
        url = f"{DATASPHERE_URL}/deepsea/repository/dependencies/"
        params = {
            "ids": analytical_model_id,
            "recursive": True,
            "impact": True,
            "lineage": True,
            "details": (
                "#spaceName,#spaceLabel,qualified_name,@EndUserText.label,"
                "@EnterpriseSearch.enabled,owner,deployment_date,"
                "modification_date,#objectStatus,#businessType,#technicalType,"
                "@Analytics.provider,#isViewEntity,"
                "@DataWarehouse.remote.connection,#isToolingHidden,"
                "releaseStateValue,releaseDate,deprecationDate,"
                "decommissioningDate,@ObjectModel.supportedCapabilities,"
                "@DataWarehouse.consumption.external,#columnsCount,"
                "@Analytics.dbViewType,isMissingColumnLineage"
            ),
            "dependencyTypes": (
                "csn.query.from,sap.dis.source,sap.dis.targetOf,"
                "sap.dis.replicationflow.source,"
                "sap.dis.replicationflow.targetOf,"
                "sap.dwc.transformationflow.source,"
                "sap.dwc.transformationflow.targetOf,sap.dwc.idtEntity,"
                "csn.derivation.lookupEntity,csn.valueHelp.entity"
            ),
        }
        response = await self.session.get(url=url, params=params)
        model_details = response.json()[0]

        # Function for recursive iteration
        all_ids: list[tuple[str, str]] = []

        def iterate_recursively(entity: dict):
            if entity["properties"].get("#isViewEntity", "false") == "true":
                all_ids.append((entity["id"], entity["name"]))
            if len(entity["dependencies"]) > 0:
                for dependency in entity["dependencies"]:
                    iterate_recursively(dependency)

        # Iterate over all dependencies
        iterate_recursively(model_details)

        # Reverse list for bottom-up order
        all_ids.reverse()
        analytical_model_to_view_mapping = {
            analytical_model_id: {val[0]: val[1] for val in all_ids}
        }
        return analytical_model_to_view_mapping

    async def get_all_views_for_analytical_models(
        self, skip_duplicates: bool = False, thread_count: int = 1
    ) -> None:
        """
        Exports all analytical models and their associated views to a file.
        The file has the following structure:
        {
            "ID of the analytical model":
                {
                    "name": "name of the analytical model",
                    "dependencies":
                        {
                            "ID of the view": "name of the view",
                            ...
                    }
            }
        }

        Args:
            skip_duplicates (bool, optional): If True, views that already
                                              occur in other analytical models
                                              are filtered out. Default is
                                              False.
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """

        # Fetch all analytical models
        logger.debug("Loading all analytical models...")
        all_analytical_models = await self._get_all_analytical_models()
        analytical_models_with_views = {}

        # Fetch all views
        views = Views(self.session)
        all_views_list = [
            (view["id"], view["space_name"])
            for view in await views._get_all_views()
        ]

        # Function to fetch all views of an analytical model
        async def get_views_for_model(model) -> None:
            logger.debug(
                "Loading all views for analytical model '%s' in '%s'...",
                model["name"],
                model["space_name"],
            )
            all_views = await self._get_all_views_for_analytical_model(
                model["id"]
            )

            # Filter out views that already occur in other models
            # if skip_duplicates = True
            if skip_duplicates:
                for view in deepcopy(all_views[model["id"]]):
                    for saved_model in analytical_models_with_views:
                        if (
                            view
                            in analytical_models_with_views[saved_model][
                                "dependencies"
                            ]
                        ):
                            all_views[model["id"]].pop(view)
                            break

            # Save analytical model
            analytical_models_with_views[model["id"]] = {
                "name": model["name"],
                "dependencies": all_views[model["id"]],
            }

            # Extract spaces of views
            logger.debug("Mapping views to their spaces...")
            for view_id, view_name in analytical_models_with_views[
                model["id"]
            ]["dependencies"].items():
                for view in all_views_list:
                    if view_id == view[0]:
                        analytical_models_with_views[model["id"]][
                            "dependencies"
                        ][view_id] = (view[1], view_name)
                        break

        # Iterate over all models
        if thread_count > 1:
            semaphore = asyncio.Semaphore(thread_count)
            tasks = []
            for model in all_analytical_models:

                async def process_model(current_model):
                    async with semaphore:
                        await get_views_for_model(current_model)

                task = asyncio.create_task(process_model(model))
                tasks.append(task)
            await asyncio.gather(*tasks)

        else:
            for model in all_analytical_models:
                await get_views_for_model(model)

        # Save results
        with open(
            ALL_FILES["ANALYTICAL_MODELS_ALL_VIEWS"]["absolute_path"],
            "w",
        ) as file:
            json.dump(analytical_models_with_views, file, indent=4)
        logger.info(
            "Results saved to '%s'.",
            ALL_FILES["ANALYTICAL_MODELS_ALL_VIEWS"]["absolute_path"],
        )

    async def get_all_views_for_analytical_models_in_space(
        self,
        space_name: str,
        skip_duplicates: bool = False,
        thread_count: int = 1,
    ) -> None:
        """
        Saves all analytical models of a specific space with their associated
        views to a file.
        The file has the following structure:
        {
            "ID of the analytical model":
                {
                    "name": "name of the analytical model",
                    "dependencies":
                        {
                            "ID of the view": [
                                "space of the view",
                                "name of the view"
                            ], ...
                    }
            }
        }

        Args:
            space_name (str): Name of the space.
            skip_duplicates (bool, optional): If True, views that already
                                              occur in other analytical models
                                              are filtered out. Default is
                                              False.
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """

        # Fetch all analytical models
        logger.debug(
            "Loading all analytical models from space '%s'...",
            space_name,
        )
        all_analytical_models_in_space = (
            await self._get_all_analytical_models_from_space(space_name)
        )

        # Fetch all views
        views = Views(self.session)
        all_views_list = [
            (view["id"], view["space_name"])
            for view in await views._get_all_views()
        ]

        # Dictionary for results
        analytical_models_with_views_in_space = {}

        # Function to fetch and filter all views of an analytical model
        async def filter_views_for_model(model) -> None:
            logger.debug(
                "Loading all views for analytical model '%s'...",
                model["name"],
            )
            all_views = await self._get_all_views_for_analytical_model(
                model["id"]
            )

            # Filter out views that already occur in other models
            # if skip_duplicates = True
            if skip_duplicates:
                logger.debug("Filtering out previously saved views...")
                for view in deepcopy(all_views[model["id"]]):
                    for saved_model in analytical_models_with_views_in_space:
                        if (
                            view
                            in analytical_models_with_views_in_space[
                                saved_model
                            ]["dependencies"]
                        ):
                            all_views[model["id"]].pop(view)
                            break

            # Save analytical model
            analytical_models_with_views_in_space[model["id"]] = {
                "name": model["name"],
                "dependencies": all_views[model["id"]],
            }

            # Add spaces to views
            logger.debug("Mapping views to their spaces...")
            for view_id, view_name in analytical_models_with_views_in_space[
                model["id"]
            ]["dependencies"].items():
                for view in all_views_list:
                    if view_id == view[0]:
                        analytical_models_with_views_in_space[model["id"]][
                            "dependencies"
                        ][view_id] = (view[1], view_name)
                        break

        # Iterate over all models
        if thread_count > 1:
            semaphore = asyncio.Semaphore(thread_count)
            tasks = []
            for model in all_analytical_models_in_space:

                async def process_model(current_model):
                    async with semaphore:
                        await filter_views_for_model(current_model)

                task = asyncio.create_task(process_model(model))
                tasks.append(task)
            await asyncio.gather(*tasks)

        else:
            for model in all_analytical_models_in_space:
                await filter_views_for_model(model)

        # Save results
        file_name = ALL_FILES["ANALYTICAL_MODELS_ALL_VIEWS_IN_SPACE"][
            "absolute_path"
        ].replace("space", space_name)
        with open(file_name, "w") as file:
            json.dump(analytical_models_with_views_in_space, file, indent=4)
        logger.info("Results saved to '%s'.", file_name)

    async def check_runtime_for_all_views_of_analytical_models(
        self, thread_count: int = 1
    ) -> None:
        """
        Checks the persistence times of all views for analytical models that
        are stored in ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME.
        Persists the views to check the actual runtime. Unpersists views unless
        they were previously persisted. Saves the results to
        ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME_RESULT.

        Args:
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """

        # Read task file
        models_to_check = []
        file_name = ALL_FILES["ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME"][
            "absolute_path"
        ]
        with open(file_name, newline="") as file:
            reader = csv.DictReader(
                file,
                fieldnames=ALL_FILES[
                    "ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME"
                ]["columns"],
            )
            models_to_check = list(reader)[1:]

        # Fetch all analytical models and create ID mapping
        # (needed for method)
        logger.debug("Loading all analytical models...")
        all_analytical_models = await self._get_all_analytical_models()
        models_mapping_id_to_name_and_space = {
            model["id"]: (model["name"], model["space_name"])
            for model in all_analytical_models
        }

        # Fetch all views
        views = Views(self.session)
        all_views_list = [
            (view["id"], view["space_name"])
            for view in await views._get_all_views()
        ]

        # Fetch views for all analytical models
        analytical_models_with_views = {}
        for model in models_to_check:
            # Filter analytical model ID from ID-to-name-and-space mapping
            found = False
            for model_id, (
                name,
                space,
            ) in models_mapping_id_to_name_and_space.items():
                if model["modelname"] == name and model["space"] == space:
                    found = True

                    # Fetch all views for the analytical model
                    logger.debug(
                        "Loading all views for analytical model '%s'...",
                        model["modelname"],
                    )
                    all_views = await self._get_all_views_for_analytical_model(
                        model_id
                    )

                    # Save analytical model
                    analytical_models_with_views[model_id] = {
                        "name": model["modelname"],
                        "dependencies": all_views[model_id],
                    }

                    # Add spaces to views
                    logger.debug("Mapping views to their spaces...")
                    for view_id, view_name in analytical_models_with_views[
                        model_id
                    ]["dependencies"].items():
                        for view in all_views_list:
                            if view_id == view[0]:
                                analytical_models_with_views[model_id][
                                    "dependencies"
                                ][view_id] = (view[1], view_name)
                                break
                    break

            # Check if analytical model was found
            if not found:
                logger.error(
                    "Analytical model '%s' in space '%s' was not found.",
                    model["modelname"],
                    model["space"],
                )

        # Filter all views as a set
        all_views_to_persist = set()
        for model_id, model_data in analytical_models_with_views.items():
            for view_id, (view_space, view_name) in model_data[
                "dependencies"
            ].items():
                all_views_to_persist.add(
                    (model_id, view_id, view_space, view_name)
                )

        # Format analytical models and set runtime=0
        analytical_models_with_views_readable = {}
        for model_id, model_data in analytical_models_with_views.items():
            analytical_models_with_views_readable[model_id] = {
                "name": model_data["name"],
                "dependencies": {
                    view_id: {
                        "space": view_space,
                        "name": view_name,
                        "runtime": None,
                        "alreadyPersisted": False,
                        "removedPersistence": False,
                    }
                    for view_id, (view_space, view_name) in model_data[
                        "dependencies"
                    ].items()
                },
            }

        # Function to add runtime to view
        def update_runtime(
            model_id: str,
            view_id: str,
            runtime: int | None,
        ) -> None:
            analytical_models_with_views_readable[model_id]["dependencies"][
                view_id
            ]["runtime"] = runtime

        # Function to save analytical models
        file_path_results = ALL_FILES[
            "ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME_RESULT"
        ]["absolute_path"]

        def save_results() -> None:
            with open(file_path_results, "w") as file:
                json.dump(
                    analytical_models_with_views_readable, file, indent=4
                )

        # Function to check persistence
        async def check_if_persisted(view_name: str, view_space: str) -> bool:
            url = (
                f"{DATASPHERE_URL}/dwaas-core/monitor/{view_space}/"
                f"persistedViews/{view_name}"
            )
            for _ in range(3):
                response = await self.session.get(url=url)
                if response.status_code != 200:
                    await asyncio.sleep(3)
                    continue
                return (
                    response.json().get("dataPersistency", "") == "Persisted"
                )
            else:
                raise RuntimeError(
                    f"Failed to check persistence of view '{view_name}' in "
                    f"'{view_space}'."
                )

        # Check all views if they are already persisted
        logger.debug("Checking if views are already persisted...")
        for model_data in analytical_models_with_views_readable.values():
            for view_data in model_data["dependencies"].values():
                if await check_if_persisted(
                    view_data["name"], view_data["space"]
                ):
                    view_data["alreadyPersisted"] = True

        # Save results for the first time
        logger.debug("Saving results...")
        save_results()

        # Function for persisting and unpersisting views if they were not
        # previously persisted
        async def persist_and_unpersist_view(
            model_id: str,
            view_id: str,
            view_space: str,
            view_name: str,
        ) -> None:
            # Persist view
            persisted, log_details = await views._persist_view(
                view_name, view_space
            )
            runtime = round(log_details.get("runTime", -1000) / 1000)

            # Save if successfully persisted
            if persisted:
                update_runtime(
                    model_id, view_id, runtime if runtime > 0 else None
                )
                save_results()

                # Remove persistence if not previously persisted
                if not analytical_models_with_views_readable[model_id][
                    "dependencies"
                ][view_id]["alreadyPersisted"]:
                    logger.debug(
                        "Removing persistence for view '%s' in '%s'...",
                        view_name,
                        view_space,
                    )
                    unpersisted, _ = await views._unpersist_view(
                        view_name, view_space
                    )

                    # Save if successfully unpersisted
                    if unpersisted:
                        analytical_models_with_views_readable[model_id][
                            "dependencies"
                        ][view_id]["removedPersistence"] = True
                        save_results()

                    else:
                        logger.critical(
                            "Persistence of view '%s' in '%s' could not be "
                            "removed after successfully persisting it.",
                            view_name,
                            view_space,
                        )
                        logger.critical("Please check manually!")

                else:
                    logger.debug(
                        "View '%s' in '%s' was already persisted. "
                        "Persistence won't be removed.",
                        view_name,
                        view_space,
                    )
                    update_runtime(
                        model_id,
                        view_id,
                        runtime if runtime > 0 else None,
                    )
                    save_results()

            else:
                logger.critical(
                    "Failed to persist view '%s' in '%s'.",
                    view_name,
                    view_space,
                )
                logger.critical(
                    "Please check if the view was persisted anyway."
                )

        # Start tasks
        logger.debug("Starting tasks...")
        await self.run_async_tasks(
            all_views_to_persist, persist_and_unpersist_view, thread_count
        )

        # Final logging with file path
        logger.info("Results saved to '%s'.", file_path_results)
