import csv
import hashlib
import json
from pathlib import Path

import pytest

from datasphere_cli.files.storage import (
    CsvRowValidationError,
    initialize_result,
    read_task_csv,
    write_result_csv,
    write_result_json,
)
from datasphere_cli.files.workspace import (
    RESULT_FILES,
    TASK_FILES,
    file_setup,
    result_path,
    safe_space_slug,
    task_path,
)


def test_file_setup_is_non_destructive(tmp_path: Path) -> None:
    """
    Checks that the setup keeps existing task and result files untouched.
    """
    old_result = tmp_path / "datasphere" / "results" / "old.csv"
    old_result.parent.mkdir(parents=True)
    old_result.write_text("keep me", encoding="utf-8")
    existing_task = task_path("task_chains.run_batch", tmp_path)
    existing_task.parent.mkdir(parents=True)
    existing_task.write_text("custom\n", encoding="utf-8")

    file_setup(tmp_path)

    assert old_result.read_text(encoding="utf-8") == "keep me"
    assert existing_task.read_text(encoding="utf-8") == "custom\n"
    # A directory the user removed must not reappear on the next start
    assert not (tmp_path / "datasphere" / "exports").exists()
    assert {
        path.name
        for path in (tmp_path / "datasphere" / "tasks").iterdir()
    } == {definition.filename for definition in TASK_FILES.values()}
    assert list((tmp_path / "datasphere" / "results").iterdir()) == [
        old_result
    ]


def test_safe_space_result_filename_stays_in_results(tmp_path: Path) -> None:
    """
    Checks that a space name cannot escape the results directory.
    """
    command = "analytical_models.get_view_dependencies_batch"
    space = "../../North Europe"
    digest = hashlib.sha256(space.encode("utf-8")).hexdigest()[:10]

    path = result_path(command, tmp_path, space=space)

    # The traversal segments are stripped, so the path stays where it belongs
    assert safe_space_slug(space) == f"North_Europe_{digest}"
    assert path == (
        tmp_path
        / "datasphere"
        / "results"
        / (
            "analytical_models_get_view_dependencies_"
            f"North_Europe_{digest}.json"
        )
    )


def test_safe_space_slug_is_bounded_and_case_collision_resistant() -> None:
    """
    Checks that a slug stays bounded and keeps similar names apart.
    """
    long_space = "A" * 500

    slug = safe_space_slug(long_space)

    assert len(slug) == 80

    # Stripping makes different names look alike, the hash keeps them apart
    assert safe_space_slug("Space A") != safe_space_slug("space a")
    assert safe_space_slug(long_space) == slug


def test_storage_reads_and_writes_exact_schemas(tmp_path: Path) -> None:
    """
    Checks that task rows and both result formats keep their exact schema.
    """
    file_setup(tmp_path)
    task = task_path("task_chains.run_batch", tmp_path)
    with task.open("a", newline="", encoding="utf-8") as task_file:
        csv.DictWriter(
            task_file,
            fieldnames=("task_chain", "space"),
        ).writerow({"task_chain": "CHAIN_A", "space": "SPACE_A"})

    # A task row becomes a dictionary keyed by the declared columns
    assert read_task_csv("task_chains.run_batch", tmp_path) == [
        {"task_chain": "CHAIN_A", "space": "SPACE_A"}
    ]

    # A CSV result keeps its column order, numbers become plain text
    command = "task_chains.run_batch"
    initialize_result(command, tmp_path)
    path = write_result_csv(
        command,
        [
            {
                "task_chain": "CHAIN_A",
                "space": "SPACE_A",
                "status": "completed",
                "log_status": "COMPLETED",
                "log_id": "42",
                "runtime_seconds": 12,
            }
        ],
        tmp_path,
    )
    with path.open(newline="", encoding="utf-8") as result_file:
        assert list(csv.DictReader(result_file)) == [
            {
                "task_chain": "CHAIN_A",
                "space": "SPACE_A",
                "status": "completed",
                "log_status": "COMPLETED",
                "log_id": "42",
                "runtime_seconds": "12",
            }
        ]

    # A JSON result is written space-scoped and survives the round trip
    json_command = "analytical_models.get_view_dependencies_batch"
    initialize_result(json_command, tmp_path, space="SPACE_A")
    json_path = write_result_json(
        json_command,
        {"results": [], "summary": {"total": 0}},
        tmp_path,
        space="SPACE_A",
    )
    assert json.loads(json_path.read_text(encoding="utf-8")) == {
        "results": [],
        "summary": {"total": 0},
    }


@pytest.mark.parametrize(
    "content, reason",
    [
        ("task_chain,space\nCHAIN_A\n", "missing cells"),
        ("task_chain,space\nCHAIN_A,SPACE_A,EXTRA\n", "got 3"),
        ("task_chain,space\nCHAIN_A,   \n", "blank required values"),
    ],
)
def test_read_task_csv_rejects_invalid_row_shapes(
    tmp_path: Path,
    content: str,
    reason: str,
) -> None:
    """
    Checks that a malformed task row is rejected with its row number.

    Args:
        content (str): Task file content holding the invalid row.
        reason (str): Text the error message has to contain.
    """
    file_setup(tmp_path)
    path = task_path("task_chains.run_batch", tmp_path)
    path.write_text(content, encoding="utf-8")

    with pytest.raises(CsvRowValidationError) as error:
        read_task_csv("task_chains.run_batch", tmp_path)

    assert error.value.path == path
    assert error.value.row_number == 2
    assert reason in str(error.value)


def test_initialize_result_preserves_existing_output(tmp_path: Path) -> None:
    """
    Checks that an existing result is not replaced by an empty schema.
    """
    command = "task_chains.run_batch"
    path = result_path(command, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("previous result\n", encoding="utf-8")

    initialize_result(command, tmp_path)

    assert path.read_text(encoding="utf-8") == "previous result\n"


def test_result_write_failure_preserves_existing_output(
    tmp_path: Path,
) -> None:
    """
    Checks that a failed CSV write leaves the previous result in place.
    """
    command = "task_chains.run_batch"
    path = result_path(command, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("previous result\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fieldnames"):
        write_result_csv(
            command,
            [{"unexpected": "value"}],
            tmp_path,
        )

    # The temporary file never replaces the real one, so a failed write
    # cannot leave a half-written result behind
    assert path.read_text(encoding="utf-8") == "previous result\n"


def test_json_result_write_failure_preserves_existing_output(
    tmp_path: Path,
) -> None:
    """
    Checks that a failed JSON write leaves the previous result in place.
    """
    command = "analytical_models.get_view_dependencies_batch"
    path = result_path(command, tmp_path, space="SPACE_A")
    path.parent.mkdir(parents=True)
    path.write_text("previous result\n", encoding="utf-8")

    with pytest.raises(TypeError):
        write_result_json(
            command,
            object(),
            tmp_path,
            space="SPACE_A",
        )

    # Serialization fails inside the temporary file, the old result stays
    assert path.read_text(encoding="utf-8") == "previous result\n"


def test_definitions_use_exact_result_filenames() -> None:
    """
    Checks that every task and result file keeps its documented name.
    """
    # The filenames are part of the interface, a typo would silently move
    # a user's file somewhere else
    assert {definition.filename for definition in TASK_FILES.values()} == {
        "analytical_models_measure_view_persistence.csv",
        "task_chains_run.csv",
        "views_create_partitioning.csv",
        "views_delete_partitioning.csv",
        "views_persist.csv",
        "views_unpersist.csv",
        "views_lock_partitions.csv",
        "views_unlock_partitions.csv",
    }
    assert {definition.filename for definition in RESULT_FILES.values()} == {
        "analytical_models_get_view_dependencies.json",
        "analytical_models_measure_view_persistence.json",
        "task_chains_run.csv",
        "remote_tables_configure_statistics.csv",
        "remote_tables_refresh_statistics.csv",
        "views_find_persistence_candidates.csv",
        "views_find_attribute_matches.csv",
        "views_create_partitioning.csv",
        "views_delete_partitioning.csv",
        "views_persist.csv",
        "views_unpersist.csv",
        "views_lock_partitions.csv",
        "views_unlock_partitions.csv",
    }
