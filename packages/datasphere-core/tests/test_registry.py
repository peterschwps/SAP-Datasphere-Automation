import pytest
from datasphere_core import (
    COMMANDS,
    TASKCHAIN_START_COMMAND,
    StartTaskChainRequest,
    StartTaskChainResult,
    start_task_chain,
)


def test_task_chain_command_is_registered_explicitly() -> None:
    assert dict(COMMANDS) == {
        "taskchain.start": TASKCHAIN_START_COMMAND,
    }
    assert TASKCHAIN_START_COMMAND.request_type is StartTaskChainRequest
    assert TASKCHAIN_START_COMMAND.result_type is StartTaskChainResult
    assert TASKCHAIN_START_COMMAND.handler is start_task_chain
    assert TASKCHAIN_START_COMMAND.read_only is False
    assert TASKCHAIN_START_COMMAND.destructive is True
    assert TASKCHAIN_START_COMMAND.idempotent is False
    assert TASKCHAIN_START_COMMAND.expose_to_mcp is True


def test_command_registry_is_immutable() -> None:
    with pytest.raises(TypeError):
        COMMANDS["other"] = TASKCHAIN_START_COMMAND  # type: ignore[index]
