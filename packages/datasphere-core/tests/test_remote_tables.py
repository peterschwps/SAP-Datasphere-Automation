import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from datasphere_api import DatasphereClient
from datasphere_api.models import (
    StatisticsCreateOutcome,
    StatisticsDict,
    StatisticsInformationDict,
    StatisticsUpdateOutcome,
)
from datasphere_api.models import (
    StatisticsType as ApiStatisticsType,
)
from datasphere_core.commands.remote_tables import (
    CONFIGURE_REMOTE_TABLE_STATISTICS_BATCH_COMMAND,
    CONFIGURE_REMOTE_TABLE_STATISTICS_COMMAND,
    REFRESH_REMOTE_TABLE_STATISTICS_BATCH_COMMAND,
    REFRESH_REMOTE_TABLE_STATISTICS_COMMAND,
    REMOTE_TABLES_COMMAND_DEFINITIONS,
    configure_remote_table_statistics,
    configure_remote_table_statistics_batch,
    refresh_remote_table_statistics,
    refresh_remote_table_statistics_batch,
)
from datasphere_core.context import CommandContext
from datasphere_core.models.common import (
    BatchSummary,
    CommandProgress,
    CommandProgressPhase,
)
from datasphere_core.models.remote_tables import (
    ConfigureRemoteTableStatisticsBatchRequest,
    ConfigureRemoteTableStatisticsBatchResult,
    ConfigureRemoteTableStatisticsRequest,
    ConfigureRemoteTableStatisticsResult,
    ConfigureRemoteTableStatisticsStatus,
    RefreshRemoteTableStatisticsBatchRequest,
    RefreshRemoteTableStatisticsBatchResult,
    RefreshRemoteTableStatisticsRequest,
    RefreshRemoteTableStatisticsResult,
    RefreshRemoteTableStatisticsStatus,
    StatisticsType,
)


def _metadata(
    *,
    supported: bool = True,
    limited: bool = False,
    statistics_type: ApiStatisticsType | None = None,
) -> StatisticsInformationDict:
    return {
        "statisticsSupported": supported,
        "statisticsLimitedToRecordCount": limited,
        "statisticsType": statistics_type,
        "businessName": "",
        "statisticsLatestUpdate": None,
    }


class FakeRemoteTables:
    def __init__(self, tables: StatisticsDict) -> None:
        self.tables = tables
        self.create_outcomes: dict[str, StatisticsCreateOutcome] = {}
        self.update_outcomes: dict[str, StatisticsUpdateOutcome] = {}
        self.refresh_outcomes: dict[str, bool] = {}
        self.calls: list[tuple[object, ...]] = []
        self.active = 0
        self.maximum_active = 0
        self.block_mutations = False
        self.release = asyncio.Event()

    async def get_all_tables(self, space: str) -> StatisticsDict:
        self.calls.append(("get_all_tables", space))
        return self.tables

    async def create_statistics(
        self,
        table: str,
        statistics_type: ApiStatisticsType,
        space: str,
    ) -> StatisticsCreateOutcome:
        self.calls.append(("create_statistics", table, statistics_type, space))
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            if self.block_mutations:
                await self.release.wait()
            return self.create_outcomes.get(table, "created")
        finally:
            self.active -= 1

    async def update_statistics(
        self,
        table: str,
        statistics_type: ApiStatisticsType,
        space: str,
    ) -> StatisticsUpdateOutcome:
        self.calls.append(("update_statistics", table, statistics_type, space))
        return self.update_outcomes.get(table, "updated")

    async def refresh_statistics(self, table: str, space: str) -> bool:
        self.calls.append(("refresh_statistics", table, space))
        return self.refresh_outcomes.get(table, True)


def _context(
    remote_tables: FakeRemoteTables,
    progress: list[CommandProgress] | None = None,
) -> CommandContext:
    async def report(update: CommandProgress) -> None:
        assert progress is not None
        progress.append(update)

    client = cast(
        DatasphereClient,
        SimpleNamespace(remote_tables=remote_tables),
    )
    return CommandContext(
        client=client,
        progress_callback=report if progress is not None else None,
    )


@pytest.mark.parametrize(
    ("table", "metadata", "requested", "outcome", "expected", "call"),
    [
        (
            "MISSING",
            None,
            StatisticsType.HISTOGRAM,
            None,
            "failed",
            None,
        ),
        (
            "UNSUPPORTED",
            _metadata(supported=False),
            StatisticsType.HISTOGRAM,
            None,
            "unsupported",
            None,
        ),
        (
            "LIMITED",
            _metadata(limited=True),
            StatisticsType.SIMPLE,
            None,
            "unsupported_type",
            None,
        ),
        (
            "CONFIGURED",
            _metadata(statistics_type="SIMPLE"),
            StatisticsType.SIMPLE,
            None,
            "already_configured",
            None,
        ),
        (
            "CREATE",
            _metadata(),
            StatisticsType.HISTOGRAM,
            "created",
            "created",
            "create_statistics",
        ),
        (
            "CREATE_EXISTS",
            _metadata(),
            StatisticsType.HISTOGRAM,
            "already_exists",
            "already_exists",
            "create_statistics",
        ),
        (
            "CREATE_FAILED",
            _metadata(),
            StatisticsType.HISTOGRAM,
            "failed",
            "failed",
            "create_statistics",
        ),
        (
            "UPDATE",
            _metadata(statistics_type="SIMPLE"),
            StatisticsType.HISTOGRAM,
            "updated",
            "updated",
            "update_statistics",
        ),
        (
            "UPDATE_EXISTS",
            _metadata(statistics_type="SIMPLE"),
            StatisticsType.HISTOGRAM,
            "already_exists",
            "already_exists",
            "update_statistics",
        ),
        (
            "UPDATE_FAILED",
            _metadata(statistics_type="SIMPLE"),
            StatisticsType.HISTOGRAM,
            "failed",
            "failed",
            "update_statistics",
        ),
    ],
)
async def test_configure_statistics_full_decision_matrix(
    table: str,
    metadata: StatisticsInformationDict | None,
    requested: StatisticsType,
    outcome: str | None,
    expected: ConfigureRemoteTableStatisticsStatus,
    call: str | None,
) -> None:
    tables: StatisticsDict = {} if metadata is None else {table: metadata}
    remote_tables = FakeRemoteTables(tables)
    if call == "create_statistics":
        remote_tables.create_outcomes[table] = cast(
            StatisticsCreateOutcome, outcome
        )
    elif call == "update_statistics":
        remote_tables.update_outcomes[table] = cast(
            StatisticsUpdateOutcome, outcome
        )

    result = await configure_remote_table_statistics(
        _context(remote_tables),
        ConfigureRemoteTableStatisticsRequest(
            table=table,
            space="SPACE_EXPLICIT",
            statistics_type=requested,
        ),
    )

    assert result == ConfigureRemoteTableStatisticsResult(
        table=table,
        space="SPACE_EXPLICIT",
        statistics_type=requested,
        status=expected,
    )
    assert remote_tables.calls[0] == (
        "get_all_tables",
        "SPACE_EXPLICIT",
    )
    mutation_calls = remote_tables.calls[1:]
    if call is None:
        assert mutation_calls == []
    else:
        assert mutation_calls == [(call, table, requested, "SPACE_EXPLICIT")]


@pytest.mark.parametrize(
    ("table", "metadata", "api_outcome", "expected", "api_called"),
    [
        ("MISSING", None, True, "table_not_found", False),
        (
            "UNSUPPORTED",
            _metadata(supported=False),
            True,
            "unsupported",
            False,
        ),
        ("NONE", _metadata(), True, "no_statistics", False),
        (
            "REFRESHED",
            _metadata(statistics_type="SIMPLE"),
            True,
            "refreshed",
            True,
        ),
        (
            "FAILED",
            _metadata(statistics_type="HISTOGRAM"),
            False,
            "failed",
            True,
        ),
    ],
)
async def test_refresh_statistics_full_decision_matrix(
    table: str,
    metadata: StatisticsInformationDict | None,
    api_outcome: bool,
    expected: RefreshRemoteTableStatisticsStatus,
    api_called: bool,
) -> None:
    tables: StatisticsDict = {} if metadata is None else {table: metadata}
    remote_tables = FakeRemoteTables(tables)
    remote_tables.refresh_outcomes[table] = api_outcome

    result = await refresh_remote_table_statistics(
        _context(remote_tables),
        RefreshRemoteTableStatisticsRequest(
            table=table,
            space="SPACE_EXPLICIT",
        ),
    )

    assert result == RefreshRemoteTableStatisticsResult(
        table=table,
        space="SPACE_EXPLICIT",
        status=expected,
    )
    assert remote_tables.calls == [
        ("get_all_tables", "SPACE_EXPLICIT"),
        *(
            [("refresh_statistics", table, "SPACE_EXPLICIT")]
            if api_called
            else []
        ),
    ]


async def test_configure_batch_is_ordered_bounded_and_reports_summary(
) -> None:
    tables = {table: _metadata() for table in ("D", "B", "A", "C")}
    remote_tables = FakeRemoteTables(tables)
    remote_tables.block_mutations = True
    progress: list[CommandProgress] = []

    task = asyncio.create_task(
        configure_remote_table_statistics_batch(
            _context(remote_tables, progress),
            ConfigureRemoteTableStatisticsBatchRequest(
                tables=None,
                space="SPACE_ALL",
                statistics_type=StatisticsType.RECORD_COUNT,
                max_concurrency=2,
            ),
        )
    )
    while remote_tables.active < 2:
        await asyncio.sleep(0)
    assert remote_tables.maximum_active == 2
    remote_tables.release.set()
    result = await task

    assert [item.table for item in result.results] == ["A", "B", "C", "D"]
    assert result.summary == BatchSummary(4, 4, 0, 0, 0)
    assert remote_tables.maximum_active == 2
    assert remote_tables.calls[0] == ("get_all_tables", "SPACE_ALL")
    assert [update.phase for update in progress] == [
        "started",
        "advanced",
        "advanced",
        "advanced",
        "advanced",
        "completed",
    ]
    assert progress[0] == CommandProgress(
        command="remote_tables.configure_statistics_batch",
        phase=CommandProgressPhase.STARTED,
        completed_items=0,
        total_items=None,
        succeeded_items=0,
        failed_items=0,
        skipped_items=0,
        timed_out_items=0,
    )
    assert progress[-1] == CommandProgress(
        command="remote_tables.configure_statistics_batch",
        phase=CommandProgressPhase.COMPLETED,
        completed_items=4,
        total_items=4,
        succeeded_items=4,
        failed_items=0,
        skipped_items=0,
        timed_out_items=0,
    )
    assert sorted(
        cast(int, update.item_index)
        for update in progress
        if update.phase == "advanced"
    ) == [0, 1, 2, 3]


async def test_configure_batch_preserves_order_and_categories() -> None:
    tables = {
        "OK": _metadata(),
        "CONFIGURED": _metadata(statistics_type="HISTOGRAM"),
        "UNSUPPORTED": _metadata(supported=False),
        "LIMITED": _metadata(limited=True),
    }
    remote_tables = FakeRemoteTables(tables)
    remote_tables.create_outcomes["OK"] = "already_exists"

    result = await configure_remote_table_statistics_batch(
        _context(remote_tables),
        ConfigureRemoteTableStatisticsBatchRequest(
            tables=(
                "MISSING",
                "LIMITED",
                "OK",
                "UNSUPPORTED",
                "CONFIGURED",
            ),
            space="SPACE_EXPLICIT",
            statistics_type=StatisticsType.HISTOGRAM,
        ),
    )

    assert [item.table for item in result.results] == [
        "MISSING",
        "LIMITED",
        "OK",
        "UNSUPPORTED",
        "CONFIGURED",
    ]
    assert [item.status for item in result.results] == [
        "failed",
        "unsupported_type",
        "already_exists",
        "unsupported",
        "already_configured",
    ]
    assert result.summary == BatchSummary(5, 2, 1, 2, 0)
    assert remote_tables.calls[0] == (
        "get_all_tables",
        "SPACE_EXPLICIT",
    )


async def test_refresh_batch_continues_expected_outcomes_and_progress() -> (
    None
):
    tables = {
        "REFRESHED": _metadata(statistics_type="SIMPLE"),
        "FAILED": _metadata(statistics_type="HISTOGRAM"),
        "NONE": _metadata(),
        "UNSUPPORTED": _metadata(supported=False),
    }
    remote_tables = FakeRemoteTables(tables)
    remote_tables.refresh_outcomes["FAILED"] = False
    progress: list[CommandProgress] = []

    result = await refresh_remote_table_statistics_batch(
        _context(remote_tables, progress),
        RefreshRemoteTableStatisticsBatchRequest(
            tables=(
                "MISSING",
                "UNSUPPORTED",
                "REFRESHED",
                "NONE",
                "FAILED",
            ),
            space="SPACE_EXPLICIT",
            max_concurrency=3,
        ),
    )

    assert result == RefreshRemoteTableStatisticsBatchResult(
        results=(
            RefreshRemoteTableStatisticsResult(
                "MISSING",
                "SPACE_EXPLICIT",
                RefreshRemoteTableStatisticsStatus.TABLE_NOT_FOUND,
            ),
            RefreshRemoteTableStatisticsResult(
                "UNSUPPORTED",
                "SPACE_EXPLICIT",
                RefreshRemoteTableStatisticsStatus.UNSUPPORTED,
            ),
            RefreshRemoteTableStatisticsResult(
                "REFRESHED",
                "SPACE_EXPLICIT",
                RefreshRemoteTableStatisticsStatus.REFRESHED,
            ),
            RefreshRemoteTableStatisticsResult(
                "NONE",
                "SPACE_EXPLICIT",
                RefreshRemoteTableStatisticsStatus.NO_STATISTICS,
            ),
            RefreshRemoteTableStatisticsResult(
                "FAILED",
                "SPACE_EXPLICIT",
                RefreshRemoteTableStatisticsStatus.FAILED,
            ),
        ),
        summary=BatchSummary(5, 1, 2, 2, 0),
    )
    assert len(progress) == 7
    assert progress[0].phase == "started"
    assert all(update.phase == "advanced" for update in progress[1:-1])
    assert progress[-1] == CommandProgress(
        command="remote_tables.refresh_statistics_batch",
        phase=CommandProgressPhase.FAILED,
        completed_items=5,
        total_items=5,
        succeeded_items=1,
        failed_items=2,
        skipped_items=2,
        timed_out_items=0,
    )


async def test_single_commands_report_one_started_and_terminal_update() -> (
    None
):
    configure_progress: list[CommandProgress] = []
    configure_tables = FakeRemoteTables({"TABLE": _metadata()})
    configure_tables.create_outcomes["TABLE"] = "failed"
    await configure_remote_table_statistics(
        _context(configure_tables, configure_progress),
        ConfigureRemoteTableStatisticsRequest(
            table="TABLE",
            space="SPACE",
            statistics_type=StatisticsType.SIMPLE,
        ),
    )
    assert configure_progress == [
        CommandProgress(
            command="remote_tables.configure_statistics",
            phase=CommandProgressPhase.STARTED,
        ),
        CommandProgress(
            command="remote_tables.configure_statistics",
            phase=CommandProgressPhase.FAILED,
        ),
    ]

    refresh_progress: list[CommandProgress] = []
    await refresh_remote_table_statistics(
        _context(FakeRemoteTables({}), refresh_progress),
        RefreshRemoteTableStatisticsRequest(
            table="MISSING",
            space="SPACE",
        ),
    )
    assert refresh_progress == [
        CommandProgress(
            command="remote_tables.refresh_statistics",
            phase=CommandProgressPhase.STARTED,
        ),
        CommandProgress(
            command="remote_tables.refresh_statistics",
            phase=CommandProgressPhase.FAILED,
        ),
    ]


def test_batch_request_validates_max_concurrency() -> None:
    with pytest.raises(ValueError):
        ConfigureRemoteTableStatisticsBatchRequest(
            (), "SPACE", StatisticsType.SIMPLE, 0
        )


def test_batch_results_reject_inexact_summary() -> None:
    configure_result = ConfigureRemoteTableStatisticsResult(
        "TABLE",
        "SPACE",
        StatisticsType.SIMPLE,
        ConfigureRemoteTableStatisticsStatus.CREATED,
    )
    with pytest.raises(ValueError, match="does not match"):
        ConfigureRemoteTableStatisticsBatchResult(
            (configure_result,), BatchSummary(1, 0, 1, 0, 0)
        )


def test_command_definitions_are_canonical_and_not_exposed_to_mcp() -> None:
    assert REMOTE_TABLES_COMMAND_DEFINITIONS == (
        CONFIGURE_REMOTE_TABLE_STATISTICS_COMMAND,
        CONFIGURE_REMOTE_TABLE_STATISTICS_BATCH_COMMAND,
        REFRESH_REMOTE_TABLE_STATISTICS_COMMAND,
        REFRESH_REMOTE_TABLE_STATISTICS_BATCH_COMMAND,
    )
    command_names = [
        definition.name for definition in REMOTE_TABLES_COMMAND_DEFINITIONS
    ]
    assert command_names == [
        "remote_tables.configure_statistics",
        "remote_tables.configure_statistics_batch",
        "remote_tables.refresh_statistics",
        "remote_tables.refresh_statistics_batch",
    ]
    assert all(
        not definition.expose_to_mcp
        for definition in REMOTE_TABLES_COMMAND_DEFINITIONS
    )
