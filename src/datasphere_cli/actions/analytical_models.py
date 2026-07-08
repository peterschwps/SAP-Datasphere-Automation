from typing import cast

from datasphere_api import DatasphereClient
from datasphere_api.models import AnalyticalModelsDetailsDict

from datasphere_cli.actions.files import (
    log_results_saved,
    read_task_csv,
    write_json_export,
)
from datasphere_cli.models import (
    ModelRef,
    ModelsRuntimeReport,
    ModelsWithViews,
)
from datasphere_cli.utils.concurrency import run_async_tasks
from datasphere_cli.utils.filehandler import ALL_FILES
from datasphere_cli.utils.logging import logger


async def _collect_views_for_models(
    client: DatasphereClient,
    models: list[AnalyticalModelsDetailsDict],
    skip_duplicates: bool,
    thread_count: int,
) -> ModelsWithViews:
    """
    Collects all views for the given analytical models and maps them to
    their spaces.

    Args:
        client (DatasphereClient): Authenticated client.
        models (list[AnalyticalModelsDetailsDict]): Analytical
                                                    models to
                                                    collect the
                                                    views for.
        skip_duplicates (bool): If True, views that already occur in
                                other analytical models are filtered out.
        thread_count (int): Amount of concurrent asynchronous requests.

    Returns:
        ModelsWithViews: All given analytical models with their views.
    """
    # Fetch all views for the space mapping
    all_views_list = [
        (view["id"], view["space_name"])
        for view in await client.views.get_all_views()
    ]
    collected: ModelsWithViews = {}

    # Function to collect the views of a single model
    async def collect_views(model: dict) -> None:
        logger.debug(
            "Loading all views for analytical model '%s'...",
            model["name"],
        )
        all_views = (
            await client.analytical_models.get_views_for_analytical_model(
                model["id"]
            )
        )

        # Filter out views that already occur in other models
        # if skip_duplicates = True
        if skip_duplicates:
            for view in dict(all_views[model["id"]]):
                for saved_model in collected:
                    if view in collected[saved_model]["dependencies"]:
                        all_views[model["id"]].pop(view)
                        break

        # Map views to their spaces
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
        collected[model["id"]] = {
            "name": model["name"],
            "dependencies": dependencies,
        }

    await run_async_tasks(models, collect_views, thread_count)
    return collected


async def get_all_views_for_analytical_models(
    client: DatasphereClient,
    skip_duplicates: bool,
    thread_count: int,
) -> None:
    """
    Exports all analytical models and their associated views to a file.

    Args:
        client (DatasphereClient): Authenticated client.
        skip_duplicates (bool): If True, views that already occur in
                                other analytical models are filtered out.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    logger.debug("Loading all analytical models...")
    models = await client.analytical_models.get_all_analytical_models()
    collected = await _collect_views_for_models(
        client=client,
        models=models,
        skip_duplicates=skip_duplicates,
        thread_count=thread_count,
    )
    write_json_export("ANALYTICAL_MODELS_ALL_VIEWS", collected)
    log_results_saved("ANALYTICAL_MODELS_ALL_VIEWS")


async def get_all_views_for_analytical_models_in_space(
    client: DatasphereClient,
    space_name: str,
    skip_duplicates: bool,
    thread_count: int,
) -> None:
    """
    Exports all analytical models of a space with their associated views
    to a file. The space name becomes part of the file name.

    Args:
        client (DatasphereClient): Authenticated client.
        space_name (str): Name of the space.
        skip_duplicates (bool): If True, views that already occur in
                                other analytical models are filtered out.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    logger.debug(
        "Loading all analytical models from space '%s'...",
        space_name,
    )
    models = await client.analytical_models.get_analytical_models_in_space(
        space_name
    )
    collected = await _collect_views_for_models(
        client=client,
        models=models,
        skip_duplicates=skip_duplicates,
        thread_count=thread_count,
    )
    file_name = cast(
        str,
        ALL_FILES["ANALYTICAL_MODELS_ALL_VIEWS_IN_SPACE"]["absolute_path"],
    ).replace("space", space_name)
    write_json_export(
        "ANALYTICAL_MODELS_ALL_VIEWS_IN_SPACE", collected, file_name
    )
    logger.info("Results saved to '%s'.", file_name)


async def check_runtime_for_all_views_of_analytical_models(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Checks the persistence times of all views for the analytical models
    in the task file. Persists the views to check the actual runtime.
    Unpersists views unless they were previously persisted. Saves the
    results incrementally to a JSON file.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    models = cast(
        list[ModelRef],
        read_task_csv("ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME"),
    )
    result_key = "ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME_RESULT"

    # Fetch all analytical models and create ID mapping
    logger.debug("Loading all analytical models...")
    all_models = await client.analytical_models.get_all_analytical_models()
    id_to_name_and_space = {
        model["id"]: (model["name"], model["space_name"])
        for model in all_models
    }

    # Fetch all views for the space mapping
    all_views_list = [
        (view["id"], view["space_name"])
        for view in await client.views.get_all_views()
    ]

    # Fetch views for all requested analytical models
    models_with_views: dict = {}
    for model in models:
        # Resolve the analytical model ID from the name/space mapping
        found = False
        for model_id, (name, space) in id_to_name_and_space.items():
            if model["modelname"] == name and model["space"] == space:
                found = True

                # Fetch all views for the analytical model
                logger.debug(
                    "Loading all views for analytical model '%s'...",
                    model["modelname"],
                )
                all_views = await (
                    client.analytical_models.get_views_for_analytical_model(
                        model_id
                    )
                )

                # Map views to their spaces
                logger.debug("Mapping views to their spaces...")
                dependencies: dict = {}
                for view_id, view_name in all_views[model_id].items():
                    for view in all_views_list:
                        if view_id == view[0]:
                            dependencies[view_id] = (view[1], view_name)
                            break
                    else:
                        dependencies[view_id] = view_name

                # Save analytical model
                models_with_views[model_id] = {
                    "name": model["modelname"],
                    "dependencies": dependencies,
                }
                break

        # Check if analytical model was found
        if not found:
            logger.error(
                "Analytical model '%s' in space '%s' was not found.",
                model["modelname"],
                model["space"],
            )

    # Collect all views as a set
    all_views_to_persist = set()
    for model_id, model_data in models_with_views.items():
        for view_id, (view_space, view_name) in model_data[
            "dependencies"
        ].items():
            all_views_to_persist.add(
                (model_id, view_id, view_space, view_name)
            )

    # Format analytical models and set runtime=0
    report: ModelsRuntimeReport = {}
    for model_id, model_data in models_with_views.items():
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

    # Function to save the current report (crash resilience during
    # hours-long runs)
    def save_results() -> None:
        write_json_export(result_key, report)

    # Function to add runtime to view
    def update_runtime(
        model_id: str,
        view_id: str,
        runtime: int | None,
    ) -> None:
        report[model_id]["dependencies"][view_id]["runtime"] = runtime

    # Check all views if they are already persisted
    logger.debug("Checking if views are already persisted...")
    for model_data in report.values():
        for view_data in model_data["dependencies"].values():
            if await client.views.is_persisted(
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
        persisted, log_details = await client.views.persist_view(
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
            if not report[model_id]["dependencies"][view_id][
                "alreadyPersisted"
            ]:
                logger.debug(
                    "Removing persistence for view '%s' in '%s'...",
                    view_name,
                    view_space,
                )
                unpersisted, _ = await client.views.unpersist_view(
                    view_name, view_space
                )

                # Save if successfully unpersisted
                if unpersisted:
                    report[model_id]["dependencies"][view_id][
                        "removedPersistence"
                    ] = True
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
            logger.critical("Please check if the view was persisted anyway.")

    # Start tasks
    logger.debug("Starting tasks...")
    await run_async_tasks(
        all_views_to_persist, persist_and_unpersist_view, thread_count
    )
    save_results()
    log_results_saved(result_key)
