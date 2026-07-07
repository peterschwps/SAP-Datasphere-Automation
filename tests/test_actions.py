import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from datasphere_api import DatasphereClient

from sap_datasphere_automation import actions
from sap_datasphere_automation.utils.filehandler import ALL_FILES


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


async def test_run_task_chains_writes_results(result_files: Path) -> None:
    _write_task_rows(
        "TASK_CHAIN_RUN",
        [
            {"entity": "CHAIN_A", "space": "SP"},
            {"entity": "CHAIN_B", "space": "SP"},
        ],
    )

    # Stub client that reports one success and one failure
    async def fake_run(chains, thread_count, on_result):
        on_result(
            {
                "entity": "CHAIN_A",
                "space": "SP",
                "isCompleted": True,
                "runtime": 65,
            }
        )
        on_result(
            {
                "entity": "CHAIN_B",
                "space": "SP",
                "isCompleted": False,
                "runtime": None,
            }
        )

    client = cast(
        DatasphereClient,
        SimpleNamespace(task_chains=SimpleNamespace(run=fake_run)),
    )
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
    async def fake_persist_views(views, thread_count, timer, on_result):
        assert views == [{"entity": "VIEW_A", "space": "SP"}]
        on_result(
            {
                "entity": "VIEW_A",
                "space": "SP",
                "isPersisted": True,
                "runtime": 12,
            }
        )

    client = cast(
        DatasphereClient,
        SimpleNamespace(
            views=SimpleNamespace(persist_views=fake_persist_views)
        ),
    )
    await actions.persist_views(client, timer=True, thread_count=1)

    assert _read_csv("VIEW_PERSIST_RESULT") == [
        {
            "entity": "VIEW_A",
            "space": "SP",
            "isPersisted": "True",
            "runtime": "12",
        }
    ]


async def test_create_view_analytics_appends_rows(
    result_files: Path,
) -> None:
    # Stub client that reports two persistence candidates
    async def fake_create_view_analytics(thread_count, on_result):
        for entity in ("VIEW_A", "VIEW_B"):
            on_result(
                {
                    "entity": entity,
                    "space": "SP",
                    "businessName": f"Business {entity}",
                    "isPersisted": False,
                }
            )

    client = cast(
        DatasphereClient,
        SimpleNamespace(
            views=SimpleNamespace(
                create_view_analytics=fake_create_view_analytics
            )
        ),
    )
    await actions.create_view_analytics(client, thread_count=1)

    rows = _read_csv("VIEW_ANALYSE")
    assert [row["entity"] for row in rows] == ["VIEW_A", "VIEW_B"]
    assert rows[0]["businessName"] == "Business VIEW_A"


async def test_export_analytical_models_writes_json(
    result_files: Path,
) -> None:
    models = {
        "m1": {
            "name": "Model1",
            "dependencies": {"v1": ["SP_V", "View1"]},
        }
    }

    # Stub client that returns the models
    async def fake_export(skip_duplicates, thread_count):
        return models

    client = cast(
        DatasphereClient,
        SimpleNamespace(
            analytical_models=SimpleNamespace(
                get_all_views_for_analytical_models=fake_export
            )
        ),
    )
    await actions.get_all_views_for_analytical_models(
        client, skip_duplicates=False, thread_count=1
    )

    file_name = ALL_FILES["ANALYTICAL_MODELS_ALL_VIEWS"]["absolute_path"]
    with open(file_name, encoding="utf-8") as file:
        assert json.load(file) == models
