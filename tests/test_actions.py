import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from datasphere_api import DatasphereClient

from datasphere_cli import actions
from datasphere_cli.utils import runs


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    """
    Points the task file and the runs directory into tmp_path.
    """
    monkeypatch.setattr(runs, "TASKS_FILE", tmp_path / "tasks.csv")
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    return tmp_path


def _write_tasks(rows: list[dict]) -> None:
    with open(
        runs.TASKS_FILE, "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=runs.TASK_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _run_dir() -> Path:
    run_dirs = list(runs.RUNS_DIR.iterdir())
    assert len(run_dirs) == 1
    return run_dirs[0]


def _read_csv(file_name: str) -> list[dict]:
    with open(
        _run_dir() / file_name, newline="", encoding="utf-8"
    ) as file:
        return list(csv.DictReader(file))


def _client(**resources) -> DatasphereClient:
    return cast(DatasphereClient, SimpleNamespace(**resources))


def test_read_tasks_creates_template(data_dir: Path) -> None:
    # First call creates the file and returns no tasks
    assert runs.read_tasks() == []
    with open(runs.TASKS_FILE, newline="", encoding="utf-8") as file:
        assert file.read() == "entity,space,attribute\r\n"

    # Filled rows are returned including the optional attribute
    _write_tasks(
        [{"entity": "VIEW_A", "space": "SP", "attribute": "YEAR"}]
    )
    assert runs.read_tasks() == [
        {"entity": "VIEW_A", "space": "SP", "attribute": "YEAR"}
    ]


async def test_run_task_chains_writes_results(data_dir: Path) -> None:
    _write_tasks(
        [
            {"entity": "CHAIN_A", "space": "SP"},
            {"entity": "CHAIN_B", "space": "SP"},
        ]
    )

    # Stub client that reports one success and one failure
    async def fake_run(chain, space, *, timeout_seconds):
        assert timeout_seconds is None
        if chain == "CHAIN_A":
            return True, {"runTime": 65432}
        return False, {}

    client = _client(task_chains=SimpleNamespace(run=fake_run))
    await actions.run_task_chains(client, thread_count=1)

    # Check the exact rows of the uniform result file
    assert _read_csv("results.csv") == [
        {
            "entity": "CHAIN_A",
            "space": "SP",
            "success": "True",
            "detail": "",
            "runtime": "65",
        },
        {
            "entity": "CHAIN_B",
            "space": "SP",
            "success": "False",
            "detail": "",
            "runtime": "",
        },
    ]


async def test_persist_views_prefills_and_updates(data_dir: Path) -> None:
    _write_tasks([{"entity": "VIEW_A", "space": "SP"}])

    # Stub client that persists the view successfully
    async def fake_persist_view(view, space):
        assert (view, space) == ("VIEW_A", "SP")
        return True, {"runTime": 12000}

    client = _client(views=SimpleNamespace(persist_view=fake_persist_view))
    await actions.persist_views(client, timer=True, thread_count=1)

    assert _read_csv("results.csv") == [
        {
            "entity": "VIEW_A",
            "space": "SP",
            "success": "True",
            "detail": "",
            "runtime": "12",
        }
    ]


async def test_no_run_folder_without_tasks(data_dir: Path) -> None:
    # Task file doesn't exist yet: action creates the template and
    # returns without creating a run folder
    client = _client(views=SimpleNamespace())
    await actions.persist_views(client, timer=False, thread_count=1)
    assert runs.TASKS_FILE.is_file()
    assert not runs.RUNS_DIR.exists()


async def test_create_view_analytics_filters_score_10(
    data_dir: Path,
) -> None:
    all_views = [
        {"id": "v1", "name": "VIEW_A", "space_name": "SP"},
        {"id": "v2", "name": "VIEW_B", "space_name": "SP"},
    ]

    # Stub client where only VIEW_A yields a score-10 candidate
    async def fake_get_all_views():
        return all_views

    async def fake_analyze_view(view, space):
        if view == "VIEW_A":
            return [
                {
                    "entity": "VIEW_A",
                    "space": "SP",
                    "businessName": "View A",
                    "isPersisted": False,
                    "persistencyCandidateScore": 10,
                },
                {"entity": "OTHER", "persistencyCandidateScore": 5},
            ]
        return [{"entity": "VIEW_B", "persistencyCandidateScore": 3}]

    client = _client(
        views=SimpleNamespace(
            get_all_views=fake_get_all_views,
            analyze_view=fake_analyze_view,
        )
    )
    await actions.create_view_analytics(client, thread_count=1)

    assert _read_csv("export.csv") == [
        {
            "entity": "VIEW_A",
            "space": "SP",
            "businessName": "View A",
            "isPersisted": "False",
        }
    ]


async def test_create_partitioning_requires_attribute(
    data_dir: Path,
) -> None:
    _write_tasks(
        [
            {"entity": "VIEW_A", "space": "SP", "attribute": "YEAR"},
            {"entity": "VIEW_B", "space": "SP", "attribute": ""},
        ]
    )

    # Stub client that accepts the partitioning
    async def fake_create_partitioning(
        view, space, attribute, partitions, overwrite_existing
    ):
        assert (view, attribute) == ("VIEW_A", "YEAR")
        assert partitions == ["2023", "2024"]
        return "created"

    client = _client(
        views=SimpleNamespace(
            create_partitioning=fake_create_partitioning
        )
    )
    await actions.create_partitioning_for_views(
        client,
        partitions=["2023", "2024"],
        overwrite_existing_partitions=False,
        thread_count=1,
    )

    # Rows without an attribute produce a missing_attribute result
    assert _read_csv("results.csv") == [
        {
            "entity": "VIEW_A",
            "space": "SP",
            "success": "True",
            "detail": "created",
            "runtime": "",
        },
        {
            "entity": "VIEW_B",
            "space": "SP",
            "success": "False",
            "detail": "missing_attribute",
            "runtime": "",
        },
    ]


async def test_lock_partitions_reports_views_without_partitions(
    data_dir: Path,
) -> None:
    _write_tasks(
        [
            {"entity": "WITH", "space": "SP"},
            {"entity": "WITHOUT", "space": "SP"},
        ]
    )

    # Stub client where one view has no partitions
    async def fake_lock_partitions(view, space, until_year):
        assert until_year == 2023
        return "locked" if view == "WITH" else "no_partitions"

    client = _client(
        views=SimpleNamespace(lock_partitions=fake_lock_partitions)
    )
    await actions.lock_partitions_until_year(
        client, year=2023, thread_count=1
    )

    # Views without partitions get a result row with the outcome
    assert _read_csv("results.csv") == [
        {
            "entity": "WITH",
            "space": "SP",
            "success": "True",
            "detail": "locked",
            "runtime": "",
        },
        {
            "entity": "WITHOUT",
            "space": "SP",
            "success": "False",
            "detail": "no_partitions",
            "runtime": "",
        },
    ]


async def test_create_statistics_decision_matrix(data_dir: Path) -> None:
    all_tables = {
        "NEW": {"statisticsSupported": True, "statisticsType": None},
        "OTHER_TYPE": {
            "statisticsSupported": True,
            "statisticsType": "SIMPLE",
        },
        "SAME_TYPE": {
            "statisticsSupported": True,
            "statisticsType": "HISTOGRAM",
        },
        "UNSUPPORTED": {
            "statisticsSupported": False,
            "statisticsType": None,
        },
    }
    created: list[str] = []
    updated: list[str] = []

    # Stub client that records which endpoint gets called per table
    async def fake_get_all_tables():
        return all_tables

    async def fake_create(table, statistics_type):
        created.append(table)
        return "created"

    async def fake_update(table, statistics_type):
        updated.append(table)
        return "updated"

    client = _client(
        remote_tables=SimpleNamespace(
            get_all_tables=fake_get_all_tables,
            create_statistics=fake_create,
            update_statistics=fake_update,
        )
    )
    await actions.create_statistics(
        client, statistics_type="HISTOGRAM", thread_count=1
    )

    # Tables without statistics are created, different types updated,
    # same type and unsupported tables are only reported
    assert created == ["NEW"]
    assert updated == ["OTHER_TYPE"]
    assert _read_csv("results.csv") == [
        {
            "entity": "NEW",
            "space": "",
            "success": "True",
            "detail": "created",
            "runtime": "",
        },
        {
            "entity": "OTHER_TYPE",
            "space": "",
            "success": "True",
            "detail": "updated",
            "runtime": "",
        },
        {
            "entity": "SAME_TYPE",
            "space": "",
            "success": "True",
            "detail": "skipped_same_type",
            "runtime": "",
        },
        {
            "entity": "UNSUPPORTED",
            "space": "",
            "success": "False",
            "detail": "skipped_unsupported",
            "runtime": "",
        },
    ]


async def test_export_analytical_models_writes_json(
    data_dir: Path,
) -> None:
    # Stub client with one model whose views partially resolve to spaces
    async def fake_get_all_analytical_models():
        return [{"id": "m1", "name": "Model1", "space_name": "SP"}]

    async def fake_get_views_for_analytical_model(model_id):
        return {"m1": {"v1": "View1", "v2": "View2"}}

    async def fake_get_all_views():
        return [{"id": "v1", "space_name": "SP_V"}]

    client = _client(
        analytical_models=SimpleNamespace(
            get_all_analytical_models=fake_get_all_analytical_models,
            get_views_for_analytical_model=(
                fake_get_views_for_analytical_model
            ),
        ),
        views=SimpleNamespace(get_all_views=fake_get_all_views),
    )
    await actions.get_all_views_for_analytical_models(
        client, skip_duplicates=False, thread_count=1
    )

    with open(_run_dir() / "export.json", encoding="utf-8") as file:
        assert json.load(file) == {
            "m1": {
                "name": "Model1",
                "dependencies": {
                    "v1": ["SP_V", "View1"],
                    "v2": "View2",
                },
            }
        }
