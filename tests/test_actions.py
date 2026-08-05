import csv
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from datasphere_core import CommandContext
from datasphere_core.models.analytical_models import (
    AnalyticalModelDependenciesStatus,
    AnalyticalModelDependencyStatus,
    AnalyticalModelPersistenceStatus,
    AnalyticalModelReference,
    AnalyticalModelViewDependency,
    GetAnalyticalModelViewDependenciesBatchRequest,
    GetAnalyticalModelViewDependenciesBatchResult,
    GetAnalyticalModelViewDependenciesResult,
    MeasureAnalyticalModelViewPersistenceBatchRequest,
    MeasureAnalyticalModelViewPersistenceBatchResult,
    MeasureAnalyticalModelViewPersistenceResult,
)
from datasphere_core.models.common import BatchItemResult, BatchSummary
from datasphere_core.models.remote_tables import (
    ConfigureRemoteTableStatisticsBatchRequest,
    ConfigureRemoteTableStatisticsBatchResult,
    ConfigureRemoteTableStatisticsResult,
    ConfigureRemoteTableStatisticsStatus,
    RefreshRemoteTableStatisticsBatchRequest,
    RefreshRemoteTableStatisticsBatchResult,
    RefreshRemoteTableStatisticsResult,
    RefreshRemoteTableStatisticsStatus,
    StatisticsType,
)
from datasphere_core.models.task_chains import (
    RunTaskChainBatchRequest,
    RunTaskChainBatchResult,
    RunTaskChainRequest,
    RunTaskChainResult,
    TaskChainStatus,
)
from datasphere_core.models.views import (
    CreateViewPartitioningBatchRequest,
    CreateViewPartitioningBatchResult,
    CreateViewPartitioningRequest,
    CreateViewPartitioningResult,
    CreateViewPartitioningStatus,
    DeleteViewPartitioningBatchRequest,
    DeleteViewPartitioningBatchResult,
    DeleteViewPartitioningRequest,
    DeleteViewPartitioningResult,
    DeleteViewPartitioningStatus,
    FindViewAttributeMatchesBatchRequest,
    FindViewAttributeMatchesBatchResult,
    FindViewAttributeMatchesResult,
    FindViewAttributeMatchesStatus,
    FindViewPersistenceCandidatesBatchRequest,
    FindViewPersistenceCandidatesBatchResult,
    FindViewPersistenceCandidatesResult,
    FindViewPersistenceCandidatesStatus,
    LockViewPartitionsBatchRequest,
    LockViewPartitionsBatchResult,
    LockViewPartitionsRequest,
    LockViewPartitionsResult,
    LockViewPartitionsStatus,
    PersistViewBatchRequest,
    PersistViewBatchResult,
    PersistViewRequest,
    PersistViewResult,
    PersistViewStatus,
    UnlockViewPartitionsBatchRequest,
    UnlockViewPartitionsBatchResult,
    UnlockViewPartitionsRequest,
    UnlockViewPartitionsResult,
    UnlockViewPartitionsStatus,
    UnpersistViewBatchRequest,
    UnpersistViewBatchResult,
    UnpersistViewRequest,
    UnpersistViewResult,
    UnpersistViewStatus,
    ViewPersistenceCandidate,
)

from datasphere_cli import actions
from datasphere_cli.actions import (
    analytical_models as analytical_model_actions,
)
from datasphere_cli.actions import remote_tables as remote_table_actions
from datasphere_cli.actions import task_chains as task_chain_actions
from datasphere_cli.actions import views as view_actions
from datasphere_cli.actions.analytical_models import (
    _DEPENDENCIES_MESSAGES,
    _MEASURE_MESSAGES,
)
from datasphere_cli.actions.remote_tables import (
    _CONFIGURE_MESSAGES,
    _REFRESH_MESSAGES,
)
from datasphere_cli.actions.task_chains import _CHAIN_MESSAGES
from datasphere_cli.actions.views import (
    _ATTRIBUTES_MESSAGES,
    _CANDIDATES_MESSAGES,
    _CREATE_MESSAGES,
    _DELETE_MESSAGES,
    _LOCK_MESSAGES,
    _PERSIST_MESSAGES,
    _UNLOCK_MESSAGES,
    _UNPERSIST_MESSAGES,
)
from datasphere_cli.files.workspace import file_setup, result_path, task_path

# Core command each action calls, so a test can replace it with a stub
_CORE_FUNCTIONS: dict[str, tuple[Any, str]] = {
    "analytical_models.get_view_dependencies_batch": (
        analytical_model_actions,
        "get_analytical_model_view_dependencies_batch",
    ),
    "analytical_models.measure_view_persistence_batch": (
        analytical_model_actions,
        "measure_analytical_model_view_persistence_batch",
    ),
    "remote_tables.configure_statistics_batch": (
        remote_table_actions,
        "configure_remote_table_statistics_batch",
    ),
    "remote_tables.refresh_statistics_batch": (
        remote_table_actions,
        "refresh_remote_table_statistics_batch",
    ),
    "task_chains.run_batch": (
        task_chain_actions,
        "run_task_chain_batch",
    ),
    "views.find_persistence_candidates_batch": (
        view_actions,
        "find_view_persistence_candidates_batch",
    ),
    "views.find_attribute_matches_batch": (
        view_actions,
        "find_view_attribute_matches_batch",
    ),
    "views.create_partitioning_batch": (
        view_actions,
        "create_view_partitioning_batch",
    ),
    "views.delete_partitioning_batch": (
        view_actions,
        "delete_view_partitioning_batch",
    ),
    "views.persist_batch": (view_actions, "persist_view_batch"),
    "views.unpersist_batch": (view_actions, "unpersist_view_batch"),
    "views.lock_partitions_batch": (
        view_actions,
        "lock_view_partitions_batch",
    ),
    "views.unlock_partitions_batch": (
        view_actions,
        "unlock_view_partitions_batch",
    ),
}


def _context() -> CommandContext:
    """
    Builds a context whose session is never reached, because the Core command
    itself is replaced in these tests.
    """
    return CommandContext(session=cast(Any, object()))


def _summary(
    *,
    succeeded: int = 0,
    failed: int = 0,
    skipped: int = 0,
    timed_out: int = 0,
) -> BatchSummary:
    """
    Builds a batch summary whose total follows from the single counts.
    """
    return BatchSummary(
        total=succeeded + failed + skipped + timed_out,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        timed_out=timed_out,
    )


def _write_task(
    command: str,
    root: Path,
    row: Mapping[str, object],
) -> None:
    """
    Appends one row to the task file of a command.
    """
    path = task_path(command, root)
    with path.open("a", newline="", encoding="utf-8") as task_file:
        writer = csv.DictWriter(task_file, fieldnames=tuple(row))
        writer.writerow(row)


def _read_csv(command: str, root: Path) -> list[dict[str, str]]:
    """
    Reads the CSV result of a command back as dictionaries.
    """
    with result_path(command, root).open(
        newline="",
        encoding="utf-8",
    ) as result_file:
        return list(csv.DictReader(result_file))


def _patch_command(monkeypatch: Any, command: str, handler: object) -> None:
    """
    Replaces the Core command an action calls with the supplied stub.
    """
    module, name = _CORE_FUNCTIONS[command]
    monkeypatch.setattr(module, name, handler)


async def test_analytical_model_adapters_map_requests_and_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that both analytical model adapters map their request and result.
    """
    file_setup(tmp_path)
    dependency_result = GetAnalyticalModelViewDependenciesBatchResult(
        results=(
            GetAnalyticalModelViewDependenciesResult(
                analytical_model_name="MODEL_A",
                space="SPACE_A",
                status=AnalyticalModelDependenciesStatus.COMPLETED,
                analytical_model_id="model-id",
                dependencies=(
                    AnalyticalModelViewDependency(
                        view_id="view-id",
                        view_name="VIEW_A",
                        space="VIEW_SPACE",
                        status=AnalyticalModelDependencyStatus.RESOLVED,
                    ),
                ),
            ),
        ),
        summary=_summary(succeeded=1),
    )
    measure_result = MeasureAnalyticalModelViewPersistenceBatchResult(
        results=(
            MeasureAnalyticalModelViewPersistenceResult(
                analytical_model_name="MODEL_B",
                space="SPACE_B",
                status=(
                    AnalyticalModelPersistenceStatus.ANALYTICAL_MODEL_NOT_FOUND
                ),
            ),
        ),
        summary=_summary(skipped=1),
    )
    requests: list[object] = []

    async def dependencies_handler(
        context: CommandContext,
        request: object,
    ) -> object:
        assert context.session is command_context.session
        requests.append(request)
        return dependency_result

    async def measure_handler(
        context: CommandContext,
        request: object,
    ) -> object:
        assert context.session is command_context.session
        requests.append(request)
        return measure_result

    _patch_command(
        monkeypatch,
        "analytical_models.get_view_dependencies_batch",
        dependencies_handler,
    )
    _patch_command(
        monkeypatch,
        "analytical_models.measure_view_persistence_batch",
        measure_handler,
    )
    _write_task(
        "analytical_models.measure_view_persistence_batch",
        tmp_path,
        {"analytical_model": "MODEL_B", "space": "SPACE_B"},
    )
    command_context = _context()

    await actions.export_analytical_model_view_dependencies(
        command_context,
        space="SPACE/A",
        deduplicate_views=True,
        max_concurrency=3,
        workspace_root=tmp_path,
    )
    await actions.measure_analytical_model_view_persistence_from_file(
        command_context,
        timeout_seconds=120,
        max_concurrency=2,
        workspace_root=tmp_path,
    )

    # Every parameter of the action reaches the Core request unchanged
    assert requests == [
        GetAnalyticalModelViewDependenciesBatchRequest(
            space="SPACE/A",
            deduplicate_views=True,
            max_concurrency=3,
        ),
        MeasureAnalyticalModelViewPersistenceBatchRequest(
            analytical_models=(
                AnalyticalModelReference(
                    name="MODEL_B",
                    space="SPACE_B",
                ),
            ),
            timeout_seconds=120,
            max_concurrency=2,
        ),
    ]
    # The slash in the space name must not turn into a directory
    dependencies_path = result_path(
        "analytical_models.get_view_dependencies_batch",
        tmp_path,
        space="SPACE/A",
    )
    assert json.loads(dependencies_path.read_text(encoding="utf-8")) == {
        "results": [
            {
                "analytical_model": "MODEL_A",
                "space": "SPACE_A",
                "status": "completed",
                "analytical_model_id": "model-id",
                "dependencies": [
                    {
                        "view_id": "view-id",
                        "view": "VIEW_A",
                        "space": "VIEW_SPACE",
                        "status": "resolved",
                    }
                ],
            }
        ],
        "summary": {
            "total": 1,
            "succeeded": 1,
            "failed": 0,
            "skipped": 0,
            "timed_out": 0,
        },
    }
    # The measurement result is written through the checkpoint callback,
    # so a model appears in the file before the batch is finished
    measure_path = result_path(
        "analytical_models.measure_view_persistence_batch",
        tmp_path,
    )
    assert json.loads(measure_path.read_text(encoding="utf-8"))["results"] == [
        {
            "analytical_model": "MODEL_B",
            "space": "SPACE_B",
            "status": "analytical_model_not_found",
            "analytical_model_id": None,
            "dependencies": [],
        }
    ]


async def test_remote_table_adapters_dispatch_batch_commands(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that both remote table adapters write their request and result.
    """
    configured = ConfigureRemoteTableStatisticsBatchResult(
        results=(
            ConfigureRemoteTableStatisticsResult(
                table="TABLE_A",
                space="SPACE_A",
                statistics_type=StatisticsType.HISTOGRAM,
                status=ConfigureRemoteTableStatisticsStatus.CREATED,
            ),
        ),
        summary=_summary(succeeded=1),
    )
    refreshed = RefreshRemoteTableStatisticsBatchResult(
        results=(
            RefreshRemoteTableStatisticsResult(
                table="TABLE_A",
                space="SPACE_A",
                status=RefreshRemoteTableStatisticsStatus.REFRESHED,
            ),
        ),
        summary=_summary(succeeded=1),
    )
    requests: list[object] = []

    async def configure_handler(
        context: CommandContext,
        request: object,
    ) -> object:
        requests.append(request)
        return configured

    async def refresh_handler(
        context: CommandContext,
        request: object,
    ) -> object:
        requests.append(request)
        return refreshed

    _patch_command(
        monkeypatch,
        "remote_tables.configure_statistics_batch",
        configure_handler,
    )
    _patch_command(
        monkeypatch,
        "remote_tables.refresh_statistics_batch",
        refresh_handler,
    )

    configure_result = await actions.configure_remote_table_statistics(
        _context(),
        space="SPACE_A",
        statistics_type=StatisticsType.HISTOGRAM,
        max_concurrency=5,
        workspace_root=tmp_path,
    )
    refresh_result = await actions.refresh_remote_table_statistics(
        _context(),
        space="SPACE_A",
        max_concurrency=6,
        workspace_root=tmp_path,
    )

    assert requests == [
        ConfigureRemoteTableStatisticsBatchRequest(
            tables=None,
            space="SPACE_A",
            statistics_type=StatisticsType.HISTOGRAM,
            max_concurrency=5,
        ),
        RefreshRemoteTableStatisticsBatchRequest(
            tables=None,
            space="SPACE_A",
            max_concurrency=6,
        ),
    ]
    assert configure_result is configured
    assert refresh_result is refreshed

    # Both commands write a result file, so the run leaves a record behind
    assert _read_csv("remote_tables.configure_statistics_batch", tmp_path) == [
        {
            "table": "TABLE_A",
            "space": "SPACE_A",
            "statistics_type": "HISTOGRAM",
            "status": "created",
        }
    ]
    assert _read_csv("remote_tables.refresh_statistics_batch", tmp_path) == [
        {
            "table": "TABLE_A",
            "space": "SPACE_A",
            "status": "refreshed",
        }
    ]


def test_every_remote_table_status_has_its_own_message() -> None:
    """
    Checks that both remote table commands name every status they can report.
    """
    # The two enums compare equal by value, so a shared mapping would drop
    # entries instead of failing loudly
    assert set(_CONFIGURE_MESSAGES) == set(
        ConfigureRemoteTableStatisticsStatus
    )
    assert set(_REFRESH_MESSAGES) == set(RefreshRemoteTableStatisticsStatus)


def test_every_task_chain_status_has_its_own_message() -> None:
    """
    Checks that the task chain command names every status it can report.
    """
    assert set(_CHAIN_MESSAGES) == set(TaskChainStatus)

    # A start the tenant refused stays quiet: the Core already reports why
    # the request failed
    assert _CHAIN_MESSAGES[TaskChainStatus.START_FAILED] is None


def test_every_view_status_has_its_own_message() -> None:
    """
    Checks that every view command names the statuses it reports itself.
    """
    assert set(_CANDIDATES_MESSAGES) == set(
        FindViewPersistenceCandidatesStatus
    )
    assert set(_ATTRIBUTES_MESSAGES) == set(FindViewAttributeMatchesStatus)
    assert set(_CREATE_MESSAGES) == set(CreateViewPartitioningStatus)
    assert set(_DELETE_MESSAGES) == set(DeleteViewPartitioningStatus)
    assert set(_LOCK_MESSAGES) == set(LockViewPartitionsStatus)
    assert set(_UNLOCK_MESSAGES) == set(UnlockViewPartitionsStatus)
    assert set(_PERSIST_MESSAGES) == set(PersistViewStatus)
    assert set(_UNPERSIST_MESSAGES) == set(UnpersistViewStatus)

    # A start the tenant refused stays quiet: the Core already reports why
    # the request failed
    assert _PERSIST_MESSAGES[PersistViewStatus.START_FAILED] is None
    assert _UNPERSIST_MESSAGES[UnpersistViewStatus.START_FAILED] is None


def test_every_analytical_model_status_has_its_own_message() -> None:
    """
    Checks that both analytical model commands name every status they can
    report.
    """
    assert set(_DEPENDENCIES_MESSAGES) == set(
        AnalyticalModelDependenciesStatus
    )
    assert set(_MEASURE_MESSAGES) == set(AnalyticalModelPersistenceStatus)


async def test_task_chain_adapter_writes_exact_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that the task chain adapter writes every result column.
    """
    file_setup(tmp_path)
    _write_task(
        "task_chains.run_batch",
        tmp_path,
        {"task_chain": "CHAIN_A", "space": "SPACE_A"},
    )
    result = RunTaskChainBatchResult(
        results=(
            RunTaskChainResult(
                chain="CHAIN_A",
                space="SPACE_A",
                status=TaskChainStatus.COMPLETED,
                log_status="COMPLETED",
                log_id="operation-1",
                runtime_seconds=15,
            ),
        ),
        summary=_summary(succeeded=1),
    )
    requests: list[object] = []

    async def handler(
        context: CommandContext,
        request: object,
    ) -> object:
        requests.append(request)
        return result

    _patch_command(
        monkeypatch,
        "task_chains.run_batch",
        handler,
    )

    await actions.run_task_chains_from_file(
        _context(),
        timeout_seconds=90,
        max_concurrency=2,
        workspace_root=tmp_path,
    )

    assert requests == [
        RunTaskChainBatchRequest(
            requests=(
                RunTaskChainRequest(
                    chain="CHAIN_A",
                    space="SPACE_A",
                    timeout_seconds=90,
                ),
            ),
            max_concurrency=2,
        )
    ]
    assert _read_csv("task_chains.run_batch", tmp_path) == [
        {
            "task_chain": "CHAIN_A",
            "space": "SPACE_A",
            "status": "completed",
            "log_status": "COMPLETED",
            "log_id": "operation-1",
            "runtime_seconds": "15",
        }
    ]


async def test_task_chain_failure_preserves_previous_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that a failing command leaves the previous result file intact.
    """
    file_setup(tmp_path)
    _write_task(
        "task_chains.run_batch",
        tmp_path,
        {"task_chain": "CHAIN_A", "space": "SPACE_A"},
    )
    previous_path = result_path("task_chains.run_batch", tmp_path)
    previous_path.write_text("previous result\n", encoding="utf-8")

    async def handler(context: CommandContext, request: object) -> object:
        raise RuntimeError("command failed")

    _patch_command(
        monkeypatch,
        "task_chains.run_batch",
        handler,
    )

    with pytest.raises(RuntimeError, match="command failed"):
        await actions.run_task_chains_from_file(
            _context(),
            workspace_root=tmp_path,
        )

    # The result is only written after the command returned, so a raising
    # command cannot overwrite what an earlier run produced
    assert previous_path.read_text(encoding="utf-8") == "previous result\n"


async def test_view_export_adapters_preserve_boundary_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that the two view export adapters keep their edge cases in the CSV.
    """
    file_setup(tmp_path)
    candidates = FindViewPersistenceCandidatesBatchResult(
        results=(
            FindViewPersistenceCandidatesResult(
                view="SOURCE_A",
                space="SPACE_A",
                status=FindViewPersistenceCandidatesStatus.COMPLETED,
                candidates=(
                    ViewPersistenceCandidate(
                        view="CANDIDATE_A",
                        space="SPACE_B",
                        score=10,
                        business_name="Candidate A",
                        is_persisted=False,
                    ),
                ),
                log_id="analysis-1",
            ),
            FindViewPersistenceCandidatesResult(
                view="SOURCE_B",
                space="SPACE_A",
                status=FindViewPersistenceCandidatesStatus.TIMED_OUT,
                candidates=(),
                log_id="analysis-2",
            ),
        ),
        summary=_summary(succeeded=1, timed_out=1),
    )
    attributes = FindViewAttributeMatchesBatchResult(
        results=(
            FindViewAttributeMatchesResult(
                view="VIEW_A",
                space="SPACE_A",
                business_name="View A",
                status=FindViewAttributeMatchesStatus.COMPLETED,
                attributes=("VALID_FROM",),
            ),
        ),
        summary=_summary(succeeded=1),
    )
    requests: list[object] = []

    async def candidate_handler(
        context: CommandContext,
        request: object,
    ) -> object:
        requests.append(request)
        return candidates

    async def attribute_handler(
        context: CommandContext,
        request: object,
    ) -> object:
        requests.append(request)
        return attributes

    _patch_command(
        monkeypatch,
        "views.find_persistence_candidates_batch",
        candidate_handler,
    )
    _patch_command(
        monkeypatch,
        "views.find_attribute_matches_batch",
        attribute_handler,
    )

    await actions.export_view_persistence_candidates(
        _context(),
        minimum_candidate_score=10,
        timeout_seconds=45,
        max_concurrency=2,
        workspace_root=tmp_path,
    )
    await actions.export_view_attribute_matches(
        _context(),
        attribute_substring="valid",
        case_sensitive=True,
        max_concurrency=3,
        workspace_root=tmp_path,
    )

    assert requests == [
        FindViewPersistenceCandidatesBatchRequest(
            minimum_candidate_score=10,
            timeout_seconds=45,
            max_concurrency=2,
        ),
        FindViewAttributeMatchesBatchRequest(
            substring="valid",
            case_sensitive=True,
            max_concurrency=3,
        ),
    ]
    assert _read_csv("views.find_persistence_candidates_batch", tmp_path) == [
        {
            "source_view": "SOURCE_A",
            "source_space": "SPACE_A",
            "view": "CANDIDATE_A",
            "space": "SPACE_B",
            "business_name": "Candidate A",
            "score": "10",
            "is_persisted": "False",
            "status": "completed",
            "log_id": "analysis-1",
        },
        {
            "source_view": "SOURCE_B",
            "source_space": "SPACE_A",
            "view": "",
            "space": "",
            "business_name": "",
            "score": "",
            "is_persisted": "",
            "status": "timed_out",
            "log_id": "analysis-2",
        },
    ]
    assert _read_csv("views.find_attribute_matches_batch", tmp_path) == [
        {
            "view": "VIEW_A",
            "space": "SPACE_A",
            "business_name": "View A",
            "attribute": "VALID_FROM",
            "status": "completed",
        }
    ]


async def test_view_file_adapters_map_every_batch_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that every file-driven view adapter maps its request and result.
    """
    file_setup(tmp_path)
    commands_and_rows = {
        "views.create_partitioning_batch": {
            "view": "VIEW_A",
            "space": "SPACE_A",
            "attribute": "DATE_A",
        },
        "views.delete_partitioning_batch": {
            "view": "VIEW_B",
            "space": "SPACE_B",
        },
        "views.persist_batch": {"view": "VIEW_C", "space": "SPACE_C"},
        "views.unpersist_batch": {"view": "VIEW_D", "space": "SPACE_D"},
        "views.lock_partitions_batch": {
            "view": "VIEW_E",
            "space": "SPACE_E",
        },
        "views.unlock_partitions_batch": {
            "view": "VIEW_F",
            "space": "SPACE_F",
        },
    }
    for command, row in commands_and_rows.items():
        _write_task(command, tmp_path, row)

    results: dict[str, object] = {
        "views.create_partitioning_batch": (
            CreateViewPartitioningBatchResult(
                results=(
                    CreateViewPartitioningResult(
                        view="VIEW_A",
                        space="SPACE_A",
                        status=CreateViewPartitioningStatus.CREATED,
                    ),
                ),
                summary=_summary(succeeded=1),
            )
        ),
        "views.delete_partitioning_batch": DeleteViewPartitioningBatchResult(
            results=(
                DeleteViewPartitioningResult(
                    view="VIEW_B",
                    space="SPACE_B",
                    status=DeleteViewPartitioningStatus.DELETED,
                ),
            ),
            summary=_summary(succeeded=1),
        ),
        "views.persist_batch": PersistViewBatchResult(
            results=(
                PersistViewResult(
                    view="VIEW_C",
                    space="SPACE_C",
                    status=PersistViewStatus.COMPLETED,
                    log_status="COMPLETED",
                    log_id="persist-1",
                    runtime_seconds=20,
                ),
            ),
            summary=_summary(succeeded=1),
        ),
        "views.unpersist_batch": UnpersistViewBatchResult(
            results=(
                UnpersistViewResult(
                    view="VIEW_D",
                    space="SPACE_D",
                    status=UnpersistViewStatus.ALREADY_ABSENT,
                ),
            ),
            summary=_summary(skipped=1),
        ),
        "views.lock_partitions_batch": LockViewPartitionsBatchResult(
            results=(
                LockViewPartitionsResult(
                    view="VIEW_E",
                    space="SPACE_E",
                    status=LockViewPartitionsStatus.NO_PARTITIONS,
                ),
            ),
            summary=_summary(skipped=1),
        ),
        "views.unlock_partitions_batch": UnlockViewPartitionsBatchResult(
            results=(
                UnlockViewPartitionsResult(
                    view="VIEW_F",
                    space="SPACE_F",
                    status=UnlockViewPartitionsStatus.UNLOCKED,
                ),
            ),
            summary=_summary(succeeded=1),
        ),
    }
    requests: dict[str, object] = {}
    for command, result in results.items():

        async def handler(
            context: CommandContext,
            request: object,
            *,
            command: str = command,
            result: object = result,
        ) -> object:
            requests[command] = request
            return result

        _patch_command(monkeypatch, command, handler)

    await actions.create_view_partitioning_from_file(
        _context(),
        start_year=2020,
        end_year=2025,
        overwrite_existing=True,
        max_concurrency=2,
        workspace_root=tmp_path,
    )
    await actions.delete_view_partitioning_from_file(
        _context(), max_concurrency=3, workspace_root=tmp_path
    )
    await actions.persist_views_from_file(
        _context(),
        timeout_seconds=100,
        max_concurrency=4,
        workspace_root=tmp_path,
    )
    await actions.unpersist_views_from_file(
        _context(),
        timeout_seconds=200,
        max_concurrency=5,
        workspace_root=tmp_path,
    )
    await actions.lock_view_partitions_from_file(
        _context(),
        until_year=2023,
        max_concurrency=6,
        workspace_root=tmp_path,
    )
    await actions.unlock_view_partitions_from_file(
        _context(), max_concurrency=7, workspace_root=tmp_path
    )

    assert requests == {
        "views.create_partitioning_batch": (
            CreateViewPartitioningBatchRequest(
                requests=(
                    CreateViewPartitioningRequest(
                        view="VIEW_A",
                        space="SPACE_A",
                        attribute="DATE_A",
                        start_year=2020,
                        end_year=2025,
                        overwrite_existing=True,
                    ),
                ),
                max_concurrency=2,
            )
        ),
        "views.delete_partitioning_batch": DeleteViewPartitioningBatchRequest(
            requests=(
                DeleteViewPartitioningRequest(view="VIEW_B", space="SPACE_B"),
            ),
            max_concurrency=3,
        ),
        "views.persist_batch": PersistViewBatchRequest(
            requests=(
                PersistViewRequest(
                    view="VIEW_C",
                    space="SPACE_C",
                    timeout_seconds=100,
                ),
            ),
            max_concurrency=4,
        ),
        "views.unpersist_batch": UnpersistViewBatchRequest(
            requests=(
                UnpersistViewRequest(
                    view="VIEW_D",
                    space="SPACE_D",
                    timeout_seconds=200,
                ),
            ),
            max_concurrency=5,
        ),
        "views.lock_partitions_batch": LockViewPartitionsBatchRequest(
            requests=(
                LockViewPartitionsRequest(
                    view="VIEW_E",
                    space="SPACE_E",
                    until_year=2023,
                ),
            ),
            max_concurrency=6,
        ),
        "views.unlock_partitions_batch": UnlockViewPartitionsBatchRequest(
            requests=(
                UnlockViewPartitionsRequest(view="VIEW_F", space="SPACE_F"),
            ),
            max_concurrency=7,
        ),
    }
    assert _read_csv("views.create_partitioning_batch", tmp_path) == [
        {
            "view": "VIEW_A",
            "space": "SPACE_A",
            "attribute": "DATE_A",
            "status": "created",
        }
    ]
    assert _read_csv("views.persist_batch", tmp_path) == [
        {
            "view": "VIEW_C",
            "space": "SPACE_C",
            "status": "completed",
            "log_status": "COMPLETED",
            "log_id": "persist-1",
            "runtime_seconds": "20",
        }
    ]
    assert _read_csv("views.delete_partitioning_batch", tmp_path) == [
        {"view": "VIEW_B", "space": "SPACE_B", "status": "deleted"}
    ]
    assert _read_csv("views.unpersist_batch", tmp_path) == [
        {
            "view": "VIEW_D",
            "space": "SPACE_D",
            "status": "already_absent",
            "log_status": "",
            "log_id": "",
            "runtime_seconds": "",
        }
    ]
    assert _read_csv("views.lock_partitions_batch", tmp_path) == [
        {
            "view": "VIEW_E",
            "space": "SPACE_E",
            "status": "no_partitions",
        }
    ]
    assert _read_csv("views.unlock_partitions_batch", tmp_path) == [
        {"view": "VIEW_F", "space": "SPACE_F", "status": "unlocked"}
    ]


async def test_task_chain_adapter_reports_every_chain_while_it_runs(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    """
    Checks that a finished chain is logged before the batch is done.
    """
    file_setup(tmp_path)
    _write_task(
        "task_chains.run_batch",
        tmp_path,
        {"task_chain": "CHAIN_A", "space": "SPACE_A"},
    )

    def _chain(chain: str, status: TaskChainStatus) -> RunTaskChainResult:
        return RunTaskChainResult(
            chain=chain, space="SPACE_A", status=status
        )

    reported: list[str] = []

    async def handler(context: CommandContext, request: object) -> object:
        # The Core hands every completed item to the adapter, so the log has
        # to fill up while the batch is still running
        for index, (chain, status) in enumerate(
            (
                ("CHAIN_A", TaskChainStatus.COMPLETED),
                ("CHAIN_B", TaskChainStatus.FAILED),
                ("CHAIN_C", TaskChainStatus.TIMED_OUT),
                ("CHAIN_D", TaskChainStatus.START_FAILED),
            )
        ):
            await context.report_batch_item_result(
                BatchItemResult(
                    command="task_chains.run_batch",
                    item_index=index,
                    total_items=4,
                    result=_chain(chain, status),
                )
            )
            reported.append(chain)
        return RunTaskChainBatchResult(
            results=(_chain("CHAIN_A", TaskChainStatus.COMPLETED),),
            summary=_summary(succeeded=1),
        )

    _patch_command(monkeypatch, "task_chains.run_batch", handler)

    with caplog.at_level(logging.DEBUG, logger="datasphere_cli.logging"):
        await task_chain_actions.run_task_chains_from_file(
            _context(), workspace_root=tmp_path
        )

    assert reported == ["CHAIN_A", "CHAIN_B", "CHAIN_C", "CHAIN_D"]

    messages = [record.getMessage() for record in caplog.records]
    assert "Successfully completed task chain 'CHAIN_A'." in messages
    assert "Task chain 'CHAIN_B' failed." in messages
    assert any("CHAIN_C" in m and "timed out" in m for m in messages)

    # A refused start is already reported by the Core, so the adapter is quiet
    assert not any("CHAIN_D" in m for m in messages)


async def test_view_adapter_reports_every_view_while_it_runs(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    """
    Checks that a finished view is logged before the batch is done.
    """
    file_setup(tmp_path)
    _write_task(
        "views.persist_batch",
        tmp_path,
        {"view": "VIEW_A", "space": "SPACE_A"},
    )

    def _view(view: str, status: PersistViewStatus) -> PersistViewResult:
        return PersistViewResult(view=view, space="SPACE_A", status=status)

    async def handler(context: CommandContext, request: object) -> object:
        # The Core hands every completed item to the adapter, so the log has
        # to fill up while the batch is still running
        for index, (view, status) in enumerate(
            (
                ("VIEW_A", PersistViewStatus.COMPLETED),
                ("VIEW_B", PersistViewStatus.FAILED),
                ("VIEW_C", PersistViewStatus.TIMED_OUT),
                ("VIEW_D", PersistViewStatus.START_FAILED),
            )
        ):
            await context.report_batch_item_result(
                BatchItemResult(
                    command="views.persist_batch",
                    item_index=index,
                    total_items=4,
                    result=_view(view, status),
                )
            )
        return PersistViewBatchResult(
            results=(_view("VIEW_A", PersistViewStatus.COMPLETED),),
            summary=_summary(succeeded=1),
        )

    _patch_command(monkeypatch, "views.persist_batch", handler)

    with caplog.at_level(logging.DEBUG, logger="datasphere_cli.logging"):
        await view_actions.persist_views_from_file(
            _context(), workspace_root=tmp_path
        )

    messages = [record.getMessage() for record in caplog.records]
    assert "Successfully persisted view 'VIEW_A'." in messages
    assert "Persisting view 'VIEW_B' failed." in messages
    assert any("VIEW_C" in m and "timed out" in m for m in messages)

    # A refused start is already reported by the Core, so the adapter is quiet
    assert not any("VIEW_D" in m for m in messages)


async def test_analytical_model_adapter_reports_every_measurement(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    """
    Checks that a measured analytical model is logged with its checkpoint.
    """
    file_setup(tmp_path)
    _write_task(
        "analytical_models.measure_view_persistence_batch",
        tmp_path,
        {"analytical_model": "MODEL_A", "space": "SPACE_A"},
    )

    def _model(
        name: str,
        status: AnalyticalModelPersistenceStatus,
    ) -> MeasureAnalyticalModelViewPersistenceResult:
        return MeasureAnalyticalModelViewPersistenceResult(
            analytical_model_name=name,
            space="SPACE_A",
            status=status,
        )

    async def handler(context: CommandContext, request: object) -> object:
        for index, (model, status) in enumerate(
            (
                ("MODEL_A", AnalyticalModelPersistenceStatus.COMPLETED),
                ("MODEL_B", AnalyticalModelPersistenceStatus.FAILED),
            )
        ):
            await context.report_batch_item_result(
                BatchItemResult(
                    command="analytical_models.measure_view_persistence_batch",
                    item_index=index,
                    total_items=2,
                    result=_model(model, status),
                )
            )
        return MeasureAnalyticalModelViewPersistenceBatchResult(
            results=(
                _model("MODEL_A", AnalyticalModelPersistenceStatus.COMPLETED),
            ),
            summary=_summary(succeeded=1),
        )

    _patch_command(
        monkeypatch,
        "analytical_models.measure_view_persistence_batch",
        handler,
    )

    with caplog.at_level(logging.DEBUG, logger="datasphere_cli.logging"):
        await (
            analytical_model_actions
            .measure_analytical_model_view_persistence_from_file(
                _context(), workspace_root=tmp_path
            )
        )

    messages = [record.getMessage() for record in caplog.records]
    assert "Successfully measured analytical model 'MODEL_A'." in messages
    assert "Measuring analytical model 'MODEL_B' failed." in messages
