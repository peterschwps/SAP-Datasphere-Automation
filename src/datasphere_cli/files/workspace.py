import csv
import hashlib
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class FileDefinition:
    """
    Definition of one command-owned workspace file. The columns decide the
    file format: a tuple describes a CSV header, None marks a JSON file whose
    structure is too nested for columns.
    """
    filename: str
    columns: tuple[str, ...] | None = None


# Only commands that read their input from a file appear here. Commands
# discovering their own input have a result file without a task file.
TASK_FILES: Mapping[str, FileDefinition] = MappingProxyType(
    {
        "analytical_models.measure_view_persistence_batch": FileDefinition(
            "analytical_models_measure_view_persistence.csv",
            ("analytical_model", "space"),
        ),
        "task_chains.run_batch": FileDefinition(
            "task_chains_run.csv",
            ("task_chain", "space"),
        ),
        "views.create_partitioning_batch": FileDefinition(
            "views_create_partitioning.csv",
            ("view", "space", "attribute"),
        ),
        "views.delete_partitioning_batch": FileDefinition(
            "views_delete_partitioning.csv",
            ("view", "space"),
        ),
        "views.persist_batch": FileDefinition(
            "views_persist.csv",
            ("view", "space"),
        ),
        "views.unpersist_batch": FileDefinition(
            "views_unpersist.csv",
            ("view", "space"),
        ),
        "views.lock_partitions_batch": FileDefinition(
            "views_lock_partitions.csv",
            ("view", "space"),
        ),
        "views.unlock_partitions_batch": FileDefinition(
            "views_unlock_partitions.csv",
            ("view", "space"),
        ),
    }
)

RESULT_FILES: Mapping[str, FileDefinition] = MappingProxyType(
    {
        "analytical_models.get_view_dependencies_batch": FileDefinition(
            "analytical_models_get_view_dependencies.json"
        ),
        "analytical_models.measure_view_persistence_batch": FileDefinition(
            "analytical_models_measure_view_persistence.json"
        ),
        "task_chains.run_batch": FileDefinition(
            "task_chains_run.csv",
            (
                "task_chain",
                "space",
                "status",
                "log_status",
                "log_id",
                "runtime_seconds",
            ),
        ),
        "views.find_persistence_candidates_batch": FileDefinition(
            "views_find_persistence_candidates.csv",
            (
                "source_view",
                "source_space",
                "view",
                "space",
                "business_name",
                "score",
                "is_persisted",
                "status",
                "log_id",
            ),
        ),
        "views.find_attribute_matches_batch": FileDefinition(
            "views_find_attribute_matches.csv",
            ("view", "space", "business_name", "attribute", "status"),
        ),
        "views.create_partitioning_batch": FileDefinition(
            "views_create_partitioning.csv",
            ("view", "space", "attribute", "status"),
        ),
        "views.delete_partitioning_batch": FileDefinition(
            "views_delete_partitioning.csv",
            ("view", "space", "status"),
        ),
        "views.persist_batch": FileDefinition(
            "views_persist.csv",
            (
                "view",
                "space",
                "status",
                "log_status",
                "log_id",
                "runtime_seconds",
            ),
        ),
        "views.unpersist_batch": FileDefinition(
            "views_unpersist.csv",
            (
                "view",
                "space",
                "status",
                "log_status",
                "log_id",
                "runtime_seconds",
            ),
        ),
        "views.lock_partitions_batch": FileDefinition(
            "views_lock_partitions.csv",
            ("view", "space", "status"),
        ),
        "views.unlock_partitions_batch": FileDefinition(
            "views_unlock_partitions.csv",
            ("view", "space", "status"),
        ),
    }
)


def workspace_root(root: str | Path | None = None) -> Path:
    """
    Resolves the workspace root for one operation.

    Args:
        root (str | Path | None, optional): Explicit workspace root.
                                            Uses the current working
                                            directory when None.
                                            Defaults to None.

    Returns:
        Path: Root directory of the workspace.
    """
    return Path.cwd() if root is None else Path(root)


def tasks_path(root: str | Path | None = None) -> Path:
    """
    Returns the directory holding the task files.

    Args:
        root (str | Path | None, optional): Explicit workspace root.
                                            Defaults to None.

    Returns:
        Path: Directory of the task files.
    """
    return workspace_root(root) / "datasphere" / "tasks"


def results_path(root: str | Path | None = None) -> Path:
    """
    Returns the directory holding the result files.

    Args:
        root (str | Path | None, optional): Explicit workspace root.
                                            Defaults to None.

    Returns:
        Path: Directory of the result files.
    """
    return workspace_root(root) / "datasphere" / "results"


def task_path(command: str, root: str | Path | None = None) -> Path:
    """
    Returns the task file of one command.

    Args:
        command (str): Command the task file belongs to.
        root (str | Path | None, optional): Explicit workspace root.
                                            Defaults to None.

    Returns:
        Path: Path of the task file.
    """
    return tasks_path(root) / TASK_FILES[command].filename


_MAX_SPACE_SLUG_LENGTH = 80
_SPACE_HASH_LENGTH = 10


def safe_space_slug(space: str) -> str:
    """
    Builds a bounded, traversal-safe filename component for a space. A
    hash suffix keeps the name unique after the readable part was
    stripped of non-ASCII characters and truncated.

    Args:
        space (str): Technical name of the Datasphere space.

    Returns:
        str: Filename component for the space.
    """
    # Strip everything a path separator could hide in
    normalized = unicodedata.normalize("NFKD", space)
    ascii_space = normalized.encode("ascii", "ignore").decode("ascii")
    readable = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_space).strip("_-")

    # Append a hash, minus one character for the joining underscore
    # Keeps spaces apart that the stripping made identical
    digest = hashlib.sha256(space.encode("utf-8")).hexdigest()
    hash_suffix = digest[:_SPACE_HASH_LENGTH]
    readable_length = _MAX_SPACE_SLUG_LENGTH - len(hash_suffix) - 1
    readable = readable[:readable_length].rstrip("_-") or "space"
    return f"{readable}_{hash_suffix}"


def result_path(
    command: str,
    root: str | Path | None = None,
    *,
    space: str | None = None,
) -> Path:
    """
    Returns the result file of one command. Results of space-scoped
    commands get their own file per space.

    Args:
        command (str): Command the result file belongs to.
        root (str | Path | None, optional): Explicit workspace root.
                                            Defaults to None.
        space (str | None, optional): Space to scope the result file to.
                                      Defaults to None.

    Returns:
        Path: Path of the result file.
    """
    definition = RESULT_FILES[command]
    filename = definition.filename

    # Scope the filename to the space to keep results apart
    if space is not None:
        file_path = Path(filename)
        filename = (
            f"{file_path.stem}_{safe_space_slug(space)}{file_path.suffix}"
        )
    return results_path(root) / filename


def file_setup(root: str | Path | None = None) -> None:
    """
    Creates the workspace directories and any missing task templates.

    Args:
        root (str | Path | None, optional): Explicit workspace root.
                                            Defaults to None.
    """
    task_directory = tasks_path(root)
    results_path(root).mkdir(parents=True, exist_ok=True)
    task_directory.mkdir(parents=True, exist_ok=True)
    for command, definition in TASK_FILES.items():
        path = task_path(command, root)
        if path.exists():
            continue
        with path.open("w", newline="", encoding="utf-8") as task_file:
            writer = csv.DictWriter(
                task_file,
                fieldnames=definition.columns or (),
            )
            writer.writeheader()
