import json
from pathlib import Path

import pytest
from datasphere_core import (
    CommandError,
    CommandTimeoutError,
    StartTaskChainRequest,
    StartTaskChainResult,
)

from datasphere_cli import cli
from datasphere_cli import settings as settings_module
from datasphere_cli.cli import commands


def _result(status: str = "completed") -> StartTaskChainResult:
    return StartTaskChainResult(
        chain="CHAIN_A",
        space="SPACE_A",
        status=status,  # type: ignore[arg-type]
        sap_status="COMPLETED" if status == "completed" else "FAILED",
        runtime_seconds=65 if status == "completed" else None,
    )


def test_main_routes_arguments_to_direct_commands(monkeypatch) -> None:
    received: list[str] = []

    def fake_run(arguments: list[str]) -> int:
        received.extend(arguments)
        return 7

    monkeypatch.setattr("datasphere_cli.cli.commands.run", fake_run)

    result = cli.main(["taskchain", "start"])

    assert result == 7
    assert received == ["taskchain", "start"]


def test_task_chain_command_prints_json(monkeypatch, capsys) -> None:
    requests: list[StartTaskChainRequest] = []

    async def fake_execute(
        request: StartTaskChainRequest,
    ) -> StartTaskChainResult:
        requests.append(request)
        return _result()

    monkeypatch.setattr(commands, "execute_task_chain", fake_execute)

    exit_code = commands.run(
        [
            "taskchain",
            "start",
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
        StartTaskChainRequest(
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
        "runtime_seconds": 65,
    }
    assert captured.err == ""


def test_task_chain_failure_returns_exit_code_one(monkeypatch, capsys) -> None:
    async def fake_execute(
        request: StartTaskChainRequest,
    ) -> StartTaskChainResult:
        return _result("failed")

    monkeypatch.setattr(commands, "execute_task_chain", fake_execute)

    exit_code = commands.run(
        ["taskchain", "start", "CHAIN_A", "--space", "SPACE_A"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "failed" in captured.out
    assert captured.err == ""


def test_task_chain_timeout_is_written_to_stderr(monkeypatch, capsys) -> None:
    async def fake_execute(
        request: StartTaskChainRequest,
    ) -> StartTaskChainResult:
        raise CommandTimeoutError("Timed out")

    monkeypatch.setattr(commands, "execute_task_chain", fake_execute)

    exit_code = commands.run(
        ["taskchain", "start", "CHAIN_A", "--space", "SPACE_A"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "Error: Timed out\n"


def test_invalid_timeout_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as error:
        commands.run(
            [
                "taskchain",
                "start",
                "CHAIN_A",
                "--space",
                "SPACE_A",
                "--timeout",
                "90000",
            ]
        )

    assert error.value.code == 2


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
        await commands.execute_task_chain(
            StartTaskChainRequest(chain="CHAIN_A", space="SPACE_A")
        )
