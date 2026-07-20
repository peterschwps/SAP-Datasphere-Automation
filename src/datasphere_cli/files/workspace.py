import csv
import json
import os
import os.path
import sys

from datasphere_cli.logging import logger

# Working directory of the program (task/export/result files)
_PROJECT_PATH = os.getcwd()

# Directories
ALL_PATHS = {
    "EXPORTS": "datasphere/exports",
    "RESULTS": "datasphere/results",
    "TASKS": "datasphere/tasks",
}

# Files
ALL_FILES = {
    "ANALYTICAL_MODELS_ALL_VIEWS": {
        "name": "analytical_models_with_all_views.json",
        "path": ALL_PATHS["EXPORTS"],
        "columns": None,
    },
    "ANALYTICAL_MODELS_ALL_VIEWS_IN_SPACE": {
        "name": "analytical_models_with_all_views_in_space.json",
        "path": ALL_PATHS["EXPORTS"],
        "columns": None,
    },
    "ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME": {
        "name": "analytical_models_to_check_view_persistence_time.csv",
        "path": ALL_PATHS["TASKS"],
        "columns": ["modelname", "space"],
    },
    "ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME_RESULT": {
        "name": "analytical_models_with_all_views_and_persistence_time.json",
        "path": ALL_PATHS["EXPORTS"],
        "columns": None,
    },
    "TASK_CHAIN_RUN": {
        "name": "task_chains_to_run.csv",
        "path": ALL_PATHS["TASKS"],
        "columns": ["entity", "space"],
    },
    "TASK_CHAIN_RUN_RESULT": {
        "name": "task_chains_completed.csv",
        "path": ALL_PATHS["RESULTS"],
        "columns": ["entity", "space", "isCompleted", "runtime"],
    },
    "VIEW_ANALYSE": {
        "name": "best_views_to_persist.csv",
        "path": ALL_PATHS["EXPORTS"],
        "columns": ["entity", "space", "businessName", "isPersisted"],
    },
    "VIEW_ATTRIBUTE": {
        "name": "view_attributes.csv",
        "path": ALL_PATHS["EXPORTS"],
        "columns": ["entity", "space", "businessName", "attribute"],
    },
    "VIEW_PARTITIONING_CREATE": {
        "name": "views_to_create_partitions.csv",
        "path": ALL_PATHS["TASKS"],
        "columns": ["entity", "space", "attribute"],
    },
    "VIEW_PARTITIONING_CREATE_RESULT": {
        "name": "views_partitions_created.csv",
        "path": ALL_PATHS["RESULTS"],
        "columns": ["entity", "space", "attribute", "createdPartition"],
    },
    "VIEW_PARTITIONING_DELETE": {
        "name": "views_to_delete_partitions.csv",
        "path": ALL_PATHS["TASKS"],
        "columns": ["entity", "space"],
    },
    "VIEW_PARTITIONING_DELETE_RESULT": {
        "name": "views_partitions_deleted.csv",
        "path": ALL_PATHS["RESULTS"],
        "columns": ["entity", "space", "removedPartition"],
    },
    "VIEW_PERSIST": {
        "name": "views_to_persist.csv",
        "path": ALL_PATHS["TASKS"],
        "columns": ["entity", "space"],
    },
    "VIEW_PERSIST_RESULT": {
        "name": "views_persisted.csv",
        "path": ALL_PATHS["RESULTS"],
        "columns": ["entity", "space", "isPersisted", "runtime"],
    },
    "VIEW_UNPERSIST": {
        "name": "views_to_unpersist.csv",
        "path": ALL_PATHS["TASKS"],
        "columns": ["entity", "space"],
    },
    "VIEW_UNPERSIST_RESULT": {
        "name": "views_unpersisted.csv",
        "path": ALL_PATHS["RESULTS"],
        "columns": ["entity", "space", "isRemoved"],
    },
    "VIEW_PARTITION_LOCK": {
        "name": "views_to_lock_partitions.csv",
        "path": ALL_PATHS["TASKS"],
        "columns": ["entity", "space"],
    },
    "VIEW_PARTITION_LOCK_RESULT": {
        "name": "views_partitions_locked.csv",
        "path": ALL_PATHS["RESULTS"],
        "columns": ["entity", "space", "lockedPartitions"],
    },
    "VIEW_PARTITION_UNLOCK": {
        "name": "views_to_unlock_partitions.csv",
        "path": ALL_PATHS["TASKS"],
        "columns": ["entity", "space"],
    },
    "VIEW_PARTITION_UNLOCK_RESULT": {
        "name": "views_partitions_unlocked.csv",
        "path": ALL_PATHS["RESULTS"],
        "columns": ["entity", "space", "unlockedPartitions"],
    },
}


def file_setup():
    """
    Creates all required directories and files for the program. If new task
    files were created, the program exits and prompts the user to restart.
    """
    # Set absolute file paths
    for name, details in ALL_FILES.items():
        ALL_FILES[name]["absolute_path"] = os.path.join(
            _PROJECT_PATH, details["path"], details["name"]
        )

    # Create missing directories
    for directory in ALL_PATHS.values():
        os.makedirs(directory, exist_ok=True)

    # Create missing task files
    new_task_files_created = False
    for file in filter(
        lambda file: file["path"] == ALL_PATHS["TASKS"],
        ALL_FILES.values(),
    ):
        if not os.path.isfile(file["absolute_path"]):
            new_task_files_created = True  # if new file was created
            with open(file["absolute_path"], "w", encoding="utf-8") as f:
                if file["columns"] is not None:
                    writer = csv.DictWriter(f, fieldnames=file["columns"])
                    writer.writeheader()

    # Check if restart is required
    if new_task_files_created:
        logger.info("New files were created. Please restart the program.")
        sys.exit()

    # Create / overwrite all export and result files
    for file in filter(
        lambda file: file["path"]
        in [
            ALL_PATHS["EXPORTS"],
            ALL_PATHS["RESULTS"],
        ],
        ALL_FILES.values(),
    ):
        if "csv" in file["name"]:
            with open(file["absolute_path"], "w", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=file["columns"])
                writer.writeheader()
        elif "json" in file["name"]:
            with open(file["absolute_path"], "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4)
