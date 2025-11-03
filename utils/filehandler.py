import configparser
import contextlib
import csv
import json
import os.path
import sys
import webbrowser
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

from utils.logging import logger

# Paths
_PROJECT_NAME = "Datasphere"
_PROJECT_PATH = os.getcwd()
DATA_DIR = Path(user_data_dir(_PROJECT_NAME))
_CONFIG_DIR = Path(user_config_dir(_PROJECT_NAME))
COOKIES_FILE = os.path.join(_CONFIG_DIR, ".cookies.json")
_SETTINGS_FILE = os.path.join(_CONFIG_DIR, "settings.ini")

# Create directories if they don't exist
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Settings file
settings = configparser.ConfigParser()
settings.optionxform = str  # pyright: ignore[reportAttributeAccessIssue]


def create_settings_file(is_wrong: bool = False) -> None:
    """
    Creates a new settings file and fills it with example values.
    Provides additional information to the user. Exits the program afterwards.

    Args:
        is_wrong (bool, optional): True if the file already exists but doesn't
                                   match the required format (e.g. a key is
                                   missing). Default is False.
    """
    if is_wrong:
        logger.error("Corrupt settings file. Generating a new file...")
    settings["URLs"] = {
        # System > Administration > Tenant Links: SAP Datasphere URL
        "DATASPHERE_TEST_URL": "https://example-test.eu10.hcs.cloud.sap",
        # System > Administration > Tenant Links: SAP Datasphere URL
        "DATASPHERE_PROD_URL": "https://example-prod.eu10.hcs.cloud.sap",
    }
    settings["Setup"] = {
        # DATASPHERE_TEST_URL or DATASPHERE_PROD_URL
        "URL_TO_USE": "DATASPHERE_PROD_URL",
        # REQUESTS or BROWSER
        "AUTHENTICATION_METHOD": "REQUESTS",
        # CHROME, EDGE or PLAYWRIGHT
        "BROWSER_TO_USE": "CHROME",
    }
    with open(_SETTINGS_FILE, "w") as settings_file:
        settings.write(settings_file)
    logger.info("Created new settings file at '%s'.", _SETTINGS_FILE)
    logger.debug("Opening file...")
    logger.debug("Please fill it and restart the program.")
    with contextlib.suppress(Exception):
        webbrowser.open(f"file://{_SETTINGS_FILE}")
    sys.exit()


# Create settings if file doesn't exist
if not os.path.isfile(_SETTINGS_FILE):
    create_settings_file()

# Otherwise load settings
else:
    settings.read(_SETTINGS_FILE)

# Check required values in settings file
try:
    # Categories
    _ = settings["URLs"]
    _ = settings["Setup"]

    # Keys
    url = settings["Setup"]["URL_TO_USE"]
    _ = settings["URLs"][url]
    auth_method = settings["Setup"]["AUTHENTICATION_METHOD"]
    if auth_method.upper() not in ["REQUESTS", "BROWSER"]:
        raise KeyError
    browser = settings["Setup"]["BROWSER_TO_USE"]
    if browser.upper() not in ["CHROME", "EDGE", "PLAYWRIGHT"]:
        raise KeyError

except KeyError:
    settings.clear()  # to delete invalid entries
    create_settings_file(is_wrong=True)


# Directories
ALL_PATHS = {
    "EXPORTS": "datasphere/exports",
    "RESULTS": "datasphere/results",
    "TASKS": "datasphere/tasks",
}

# Files
ALL_FILES = {
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
