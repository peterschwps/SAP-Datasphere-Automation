from types import SimpleNamespace
from typing import Any, cast

import pytest
from datasphere_core import CommandContext
from datasphere_core.models.task_chains import (
    RunTaskChainRequest,
    RunTaskChainResult,
    TaskChainStatus,
)

from datasphere_cli.actions import dispatch as dispatch_module


def _context() -> CommandContext:
    return CommandContext(client=cast(Any, object()))


def _entry(handler: object) -> SimpleNamespace:
    return SimpleNamespace(
        handler=handler,
        request_type=RunTaskChainRequest,
        result_type=RunTaskChainResult,
    )


def _result() -> RunTaskChainResult:
    return RunTaskChainResult(
        chain="CHAIN_A",
        space="SPACE_A",
        status=TaskChainStatus.COMPLETED,
    )


async def test_dispatch_validates_request_and_result_types(
    monkeypatch,
) -> None:
    async def handler(
        context: CommandContext,
        request: RunTaskChainRequest,
    ) -> RunTaskChainResult:
        return _result()

    monkeypatch.setattr(
        dispatch_module,
        "COMMANDS",
        {"task_chains.run": _entry(handler)},
    )

    result = await dispatch_module.dispatch_command(
        "task_chains.run",
        _context(),
        RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
        RunTaskChainRequest,
        RunTaskChainResult,
    )

    assert result == _result()

    with pytest.raises(TypeError, match="requires a RunTaskChainRequest"):
        await dispatch_module.dispatch_command(
            "task_chains.run",
            _context(),
            object(),
            RunTaskChainRequest,
            RunTaskChainResult,
        )


async def test_dispatch_rejects_handler_result_type(monkeypatch) -> None:
    async def handler(
        context: CommandContext,
        request: RunTaskChainRequest,
    ) -> object:
        return object()

    monkeypatch.setattr(
        dispatch_module,
        "COMMANDS",
        {"task_chains.run": _entry(handler)},
    )

    with pytest.raises(TypeError, match="expected RunTaskChainResult"):
        await dispatch_module.dispatch_command(
            "task_chains.run",
            _context(),
            RunTaskChainRequest(chain="CHAIN_A", space="SPACE_A"),
            RunTaskChainRequest,
            RunTaskChainResult,
        )
