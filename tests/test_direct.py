import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from datasphere_core import CommandContext, CommandError, CommandTimeoutError
from datasphere_core.models.task_chains import (
    RunTaskChainRequest,
    RunTaskChainResult,
    TaskChainStatus,
)

from datasphere_cli import cli
from datasphere_cli import settings as settings_module
from datasphere_cli.actions import dispatch as dispatch_module
from datasphere_cli.cli import commands


def _result(status: str = "completed") -> RunTaskChainResult:
    if status == "completed":
        return RunTaskChainResult(
            chain="CHAIN_A",
            space="SPACE_A",
            status=TaskChainStatus.COMPLETED,
            sap_status="COMPLETED",
            log_id="operation-1",
            runtime_seconds=65,
        )
    return RunTaskChainResult(
        chain="CHAIN_A",
        space="SPACE_A",
        status=TaskChainStatus.FAILED,
        log_id="FAILED",
    )


def test_main_routes_canonical_arguments(monkeypatch) -> None:
    received: list[str] = []

    def fake_run(arguments: list[str]) -> int:
        received.extend(arguments)
        return 7

    monkeypatch.setattr("datasphere_cli.cli.commands.run", fake_run)

    result = cli.main(["task-chains", "run"])

    assert result == 7
    assert received == ["task-chains", "run"]


def test_task_chain_command_prints_json(monkeypatch, capsys) -> None:
    requests: list[RunTaskChainRequest] = []

    async def fake_execute(
        request: RunTaskChainRequest,
    ) -> RunTaskChainResult:
        requests.append(request)
        return _result()

    monkeypatch.setattr(commands, "run_task_chain", fake_execute)

    exit_code = commands.run(
        [
            "task-chains",
            "run",
            "CHAIN_A",
            "--space",
            "SPACE_A",
            "--timeout",
            "600",
            "--output",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert requests == [
        RunTaskChainRequest(
            chain="CHAIN_A",
            space="SPACE_A",
            timeout_seconds=600,
        )
    ]
    assert json.loads(captured.out) == {
        "chain": "CHAIN_A",
        "space": "SPACE_A",
        "status": "completed",
        "sap_status": "COMPLETED",
        "log_id": "operation-1",
        "runtime_seconds": 65,
    }
    assert captured.err == ""


def test_no_old_taskchain_route() -> None:
    with pytest.raises(SystemExit) as error:
        commands.run(["taskchain", "start", "CHAIN_A", "--space", "SPACE_A"])

    assert error.value.code == 2


def test_task_chain_failure_returns_exit_code_one(monkeypatch, capsys) -> None:
    async def fake_execute(
        request: RunTaskChainRequest,
    ) -> RunTaskChainResult:
        return _result("failed")

    monkeypatch.setattr(commands, "run_task_chain", fake_execute)

    exit_code = commands.run(
        ["task-chains", "run", "CHAIN_A", "--space", "SPACE_A"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "failed" in captured.out
    assert captured.err == ""


def test_task_chain_timeout_is_written_to_stderr(monkeypatch, capsys) -> None:
    async def fake_execute(
        request: RunTaskChainRequest,
    ) -> RunTaskChainResult:
        raise CommandTimeoutError("Timed out")

    monkeypatch.setattr(commands, "run_task_chain", fake_execute)

    exit_code = commands.run(
        ["task-chains", "run", "CHAIN_A", "--space", "SPACE_A"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Error: Timed out\n"


async def test_execute_dispatches_through_registry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings_file = tmp_path / "settings.toml"
    settings_file.touch()
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(settings_module, "build_session_config", object)
    requests: list[RunTaskChainRequest] = []

    async def handler(
        context: CommandContext,
        request: RunTaskChainRequest,
    ) -> RunTaskChainResult:
        assert context.client is FakeSession.client
        requests.append(request)
        return _result()

    class FakeSession:
        client = object()

        def __init__(self, config: object) -> None:
            self.config = config

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(
            self,
            exc_type: object,
            exc_value: object,
            traceback: object,
        ) -> None:
            return None

        async def authenticate(self, *, interactive: bool) -> None:
            assert interactive is True

    monkeypatch.setattr(commands, "DatasphereSession", FakeSession)
    monkeypatch.setattr(
        dispatch_module,
        "COMMANDS",
        {
            "task_chains.run": SimpleNamespace(
                handler=handler,
                request_type=RunTaskChainRequest,
                result_type=RunTaskChainResult,
            )
        },
    )
    request = RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A")

    result = await commands.run_task_chain(request)

    assert result == _result()
    assert requests == [request]


async def test_execute_requires_initialized_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        settings_module,
        "SETTINGS_FILE",
        tmp_path / "missing.toml",
    )

    with pytest.raises(CommandError, match="Settings are not initialized"):
        await commands.run_task_chain(
            RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A")
        )
