import asyncio
import contextlib
import logging
from collections.abc import Callable
from copy import deepcopy
from urllib.parse import quote, urlencode
from uuid import uuid4

from datasphere_api.exceptions import UnexpectedResponse
from datasphere_api.models import (
    AnalyticalModelsDetailsDict,
    ModelRef,
    ModelsRuntimeReport,
    ModelsWithViews,
)
from datasphere_api.resources.base import BaseResource

logger = logging.getLogger(__name__)


class AnalyticalModels(BaseResource):

    async def get_all_analytical_models(
        self,
    ) -> list[AnalyticalModelsDetailsDict]:
        """
        Returns all analytical models as a list of dictionaries.

        Returns:
            list[AnalyticalModelsDetailsDict]: List of dictionaries with
                                               the analytical models.
        """

        # Update headers
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Accept-Language": "de",
                "Cache-Control": "no-cache",
            }
        )

        # Fetch all analytical models
        url = f"{self._base_url}/deepsea/repository/search/$all"
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
        with contextlib.suppress(KeyError):
            self.session.headers.pop("Cache-Control")

        return all_analytical_models

    async def get_analytical_models_in_space(
        self, space_name: str
    ) -> list[AnalyticalModelsDetailsDict]:
        """
        Returns all analytical models of a specific space.

        Args:
            space_name (str): Name of the space.

        Returns:
            list[AnalyticalModelsDetailsDict]: List of dictionaries with
                                               the analytical models.
        """

        # Fetch all analytical models
        all_analytical_models_in_space = [
            model
            for model in await self.get_all_analytical_models()
            if model["space_name"] == space_name
        ]
        return all_analytical_models_in_space

    async def get_views_for_analytical_model(
        self, analytical_model_id: str
    ) -> dict[str, dict[str, str]]:
        """
        Returns all views that are used in an analytical model.

        Args:
            analytical_model_id (str): ID of the analytical model.

        Returns:
            dict[str, dict[str, str]]: Dictionary with analytical model
                                       ID as key and dictionary as value.
                                       This dictionary has view IDs as
                                       keys and view names as values.
        """

        # Update headers
        # (if get_all_analytical_models() was called before)
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )

        # Fetch details
        url = f"{self._base_url}/deepsea/repository/dependencies/"
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
    ) -> ModelsWithViews:
        """
        Returns all analytical models and their associated views.
        The result has the following structure:
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
            skip_duplicates (bool, optional): If True, views that already
                                              occur in other analytical
                                              models are filtered out.
                                              Default is False.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.

        Returns:
            ModelsWithViews: All analytical models with their views.
        """

        # Fetch all analytical models
        logger.debug("Loading all analytical models...")
        all_analytical_models = await self.get_all_analytical_models()
        analytical_models_with_views: ModelsWithViews = {}

        # Fetch all views
        views = self._client.views
        all_views_list = [
            (view["id"], view["space_name"])
            for view in await views.get_all_views()
        ]

        # Function to fetch all views of an analytical model
        async def get_views_for_model(model) -> None:
            logger.debug(
                "Loading all views for analytical model '%s' in '%s'...",
                model["name"],
                model["space_name"],
            )
            all_views = await self.get_views_for_analytical_model(
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

            # Extract spaces of views
            logger.debug("Mapping views to their spaces...")
            dependencies: dict[str, str | tuple[str, str]] = {}
            for view_id, view_name in all_views[model["id"]].items():
                for view in all_views_list:
                    if view_id == view[0]:
                        dependencies[view_id] = (view[1], view_name)
                        break
                else:
                    dependencies[view_id] = view_name

            # Save analytical model
            analytical_models_with_views[model["id"]] = {
                "name": model["name"],
                "dependencies": dependencies,
            }

        # Iterate over all models
        await self._client.run_async_tasks(
            all_analytical_models, get_views_for_model, thread_count
        )
        return analytical_models_with_views

    async def get_all_views_for_analytical_models_in_space(
        self,
        space_name: str,
        skip_duplicates: bool = False,
        thread_count: int = 1,
    ) -> ModelsWithViews:
        """
        Returns all analytical models of a specific space with their
        associated views.
        The result has the following structure:
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
                                              occur in other analytical
                                              models are filtered out.
                                              Default is False.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.

        Returns:
            ModelsWithViews: All analytical models of the space with
                             their views.
        """

        # Fetch all analytical models
        logger.debug(
            "Loading all analytical models from space '%s'...",
            space_name,
        )
        all_analytical_models_in_space = (
            await self.get_analytical_models_in_space(space_name)
        )

        # Fetch all views
        views = self._client.views
        all_views_list = [
            (view["id"], view["space_name"])
            for view in await views.get_all_views()
        ]

        # Dictionary for results
        analytical_models_with_views_in_space: ModelsWithViews = {}

        # Function to fetch and filter all views of an analytical model
        async def filter_views_for_model(model) -> None:
            logger.debug(
                "Loading all views for analytical model '%s'...",
                model["name"],
            )
            all_views = await self.get_views_for_analytical_model(
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

            # Add spaces to views
            logger.debug("Mapping views to their spaces...")
            dependencies: dict[str, str | tuple[str, str]] = {}
            for view_id, view_name in all_views[model["id"]].items():
                for view in all_views_list:
                    if view_id == view[0]:
                        dependencies[view_id] = (view[1], view_name)
                        break
                else:
                    dependencies[view_id] = view_name

            # Save analytical model
            analytical_models_with_views_in_space[model["id"]] = {
                "name": model["name"],
                "dependencies": dependencies,
            }

        # Iterate over all models
        await self._client.run_async_tasks(
            all_analytical_models_in_space,
            filter_views_for_model,
            thread_count,
        )
        return analytical_models_with_views_in_space

    async def check_runtime_for_all_views_of_analytical_models(
        self,
        models: list[ModelRef],
        thread_count: int = 1,
        on_update: Callable[[ModelsRuntimeReport], None] | None = None,
    ) -> ModelsRuntimeReport:
        """
        Checks the persistence times of all views for the given
        analytical models. Persists the views to check the actual
        runtime. Unpersists views unless they were previously persisted.

        Args:
            models (list[ModelRef]): Analytical models to check.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            on_update (Callable | None, optional): Callback that is
                                                   invoked with the
                                                   current report at
                                                   every state change
                                                   (e.g. to save results
                                                   incrementally during
                                                   long runs).
                                                   Defaults to None.

        Raises:
            UnexpectedResponse: If the persistence state of a view cannot
                                be checked.

        Returns:
            ModelsRuntimeReport: Runtime report for all given models and
                                 their views.
        """

        # Fetch all analytical models and create ID mapping
        # (needed for method)
        logger.debug("Loading all analytical models...")
        all_analytical_models = await self.get_all_analytical_models()
        models_mapping_id_to_name_and_space = {
            model["id"]: (model["name"], model["space_name"])
            for model in all_analytical_models
        }

        # Fetch all views
        views = self._client.views
        all_views_list = [
            (view["id"], view["space_name"])
            for view in await views.get_all_views()
        ]

        # Fetch views for all analytical models
        analytical_models_with_views = {}
        for model in models:
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
                    all_views = await self.get_views_for_analytical_model(
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
        report: ModelsRuntimeReport = {}
        for model_id, model_data in analytical_models_with_views.items():
            report[model_id] = {
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
            report[model_id]["dependencies"][view_id]["runtime"] = runtime

        # Function to notify the caller about a state change
        def notify_caller() -> None:
            if on_update is not None:
                on_update(report)

        # Function to check persistence
        async def check_if_persisted(view_name: str, view_space: str) -> bool:
            url = (
                f"{self._base_url}/dwaas-core/monitor/{view_space}/"
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
                raise UnexpectedResponse(
                    f"Failed to check persistence of view '{view_name}' in "
                    f"'{view_space}'."
                )

        # Check all views if they are already persisted
        logger.debug("Checking if views are already persisted...")
        for model_data in report.values():
            for view_data in model_data["dependencies"].values():
                if await check_if_persisted(
                    view_data["name"], view_data["space"]
                ):
                    view_data["alreadyPersisted"] = True

        # Notify caller for the first time
        logger.debug("Saving results...")
        notify_caller()

        # Function for persisting and unpersisting views if they were not
        # previously persisted
        async def persist_and_unpersist_view(
            model_id: str,
            view_id: str,
            view_space: str,
            view_name: str,
        ) -> None:
            # Persist view
            persisted, log_details = await views.persist_view(
                view_name, view_space
            )
            runtime = round(log_details.get("runTime", -1000) / 1000)

            # Save if successfully persisted
            if persisted:
                update_runtime(
                    model_id, view_id, runtime if runtime > 0 else None
                )
                notify_caller()

                # Remove persistence if not previously persisted
                if not report[model_id]["dependencies"][view_id][
                    "alreadyPersisted"
                ]:
                    logger.debug(
                        "Removing persistence for view '%s' in '%s'...",
                        view_name,
                        view_space,
                    )
                    unpersisted, _ = await views.unpersist_view(
                        view_name, view_space
                    )

                    # Save if successfully unpersisted
                    if unpersisted:
                        report[model_id]["dependencies"][view_id][
                            "removedPersistence"
                        ] = True
                        notify_caller()

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
                    notify_caller()

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
        await self._client.run_async_tasks(
            all_views_to_persist, persist_and_unpersist_view, thread_count
        )
        return report
