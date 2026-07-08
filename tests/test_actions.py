import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from datasphere_api import DatasphereClient

from datasphere_cli import actions
from datasphere_cli.utils.filehandler import ALL_FILES


@pytest.fixture
def result_files(tmp_path: Path, monkeypatch) -> Path:
    """
    Points all task/result/export files into tmp_path and creates them
    with their headers (like file_setup() does).
    """
    for name, details in ALL_FILES.items():
        path = tmp_path / details["name"]
        monkeypatch.setitem(ALL_FILES[name], "absolute_path", str(path))
        if "csv" in details["name"]:
            with open(path, "w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=details["columns"])
                writer.writeheader()
        else:
            path.write_text("{}", encoding="utf-8")
    return tmp_path


def _write_task_rows(file_key: str, rows: list[dict]) -> None:
    with open(
        ALL_FILES[file_key]["absolute_path"],
        "a",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=ALL_FILES[file_key]["columns"]
        )
        writer.writerows(rows)


def _read_csv(file_key: str) -> list[dict]:
    with open(
        ALL_FILES[file_key]["absolute_path"], newline="", encoding="utf-8"
    ) as file:
        return list(csv.DictReader(file))


def _client(**resources) -> DatasphereClient:
    return cast(DatasphereClient, SimpleNamespace(**resources))


async def test_run_task_chains_writes_results(result_files: Path) -> None:
    _write_task_rows(
        "TASK_CHAIN_RUN",
        [
            {"entity": "CHAIN_A", "space": "SP"},
            {"entity": "CHAIN_B", "space": "SP"},
        ],
    )

    # Stub client that reports one success and one failure
    async def fake_run(chain, space):
        if chain == "CHAIN_A":
            return True, {"runTime": 65432}
        return False, {}

    client = _client(task_chains=SimpleNamespace(run=fake_run))
    await actions.run_task_chains(client, thread_count=1)

    # Check the exact rows of the result file
    assert _read_csv("TASK_CHAIN_RUN_RESULT") == [
        {
            "entity": "CHAIN_A",
            "space": "SP",
            "isCompleted": "True",
            "runtime": "65",
        },
        {
            "entity": "CHAIN_B",
            "space": "SP",
            "isCompleted": "False",
            "runtime": "",
        },
    ]


async def test_persist_views_prefills_and_updates(
    result_files: Path,
) -> None:
    _write_task_rows("VIEW_PERSIST", [{"entity": "VIEW_A", "space": "SP"}])

    # Stub client that persists the view successfully
    async def fake_persist_view(view, space):
        assert (view, space) == ("VIEW_A", "SP")
        return True, {"runTime": 12000}

    client = _client(views=SimpleNamespace(persist_view=fake_persist_view))
    await actions.persist_views(client, timer=True, thread_count=1)

    assert _read_csv("VIEW_PERSIST_RESULT") == [
        {
            "entity": "VIEW_A",
            "space": "SP",
            "isPersisted": "True",
            "runtime": "12",
        }
    ]


async def test_create_view_analytics_filters_score_10(
    result_files: Path,
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

    rows = _read_csv("VIEW_ANALYSE")
    assert rows == [
        {
            "entity": "VIEW_A",
            "space": "SP",
            "businessName": "View A",
            "isPersisted": "False",
        }
    ]


async def test_create_statistics_decision_matrix(
    result_files: Path,
) -> None:
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
    # same type and unsupported tables are skipped
    assert created == ["NEW"]
    assert updated == ["OTHER_TYPE"]


async def test_lock_partitions_skips_views_without_partitions(
    result_files: Path,
) -> None:
    _write_task_rows(
        "VIEW_PARTITION_LOCK",
        [
            {"entity": "WITH", "space": "SP"},
            {"entity": "WITHOUT", "space": "SP"},
        ],
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

    # Views without partitions produce no result row
    assert _read_csv("VIEW_PARTITION_LOCK_RESULT") == [
        {"entity": "WITH", "space": "SP", "lockedPartitions": "True"}
    ]


async def test_export_analytical_models_writes_json(
    result_files: Path,
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

    file_name = ALL_FILES["ANALYTICAL_MODELS_ALL_VIEWS"]["absolute_path"]
    with open(file_name, encoding="utf-8") as file:
        assert json.load(file) == {
            "m1": {
                "name": "Model1",
                "dependencies": {
                    "v1": ["SP_V", "View1"],
                    "v2": "View2",
                },
            }
        }
