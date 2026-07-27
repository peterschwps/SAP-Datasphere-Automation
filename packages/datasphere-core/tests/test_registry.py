from dataclasses import replace

import pytest
from datasphere_core import COMMANDS
from datasphere_core.commands.task_chains import (
    TASK_CHAINS_RUN_BATCH_COMMAND,
    TASK_CHAINS_RUN_COMMAND,
    run_task_chain,
    run_task_chain_batch,
)
from datasphere_core.definitions import build_command_registry
from datasphere_core.execution import batch_result_phase
from datasphere_core.models.common import BatchSummary, CommandProgressPhase
from datasphere_core.models.task_chains import (
    RunTaskChainBatchRequest,
    RunTaskChainBatchResult,
    RunTaskChainRequest,
    RunTaskChainResult,
    TaskChainStatus,
)

EXPECTED_COMMAND_NAMES = {
    "analytical_models.measure_view_persistence",
    "analytical_models.measure_view_persistence_batch",
    "analytical_models.get_view_dependencies",
    "analytical_models.get_view_dependencies_batch",
    "remote_tables.configure_statistics",
    "remote_tables.configure_statistics_batch",
    "remote_tables.refresh_statistics",
    "remote_tables.refresh_statistics_batch",
    "task_chains.run",
    "task_chains.run_batch",
    "views.create_partitioning",
    "views.create_partitioning_batch",
    "views.delete_partitioning",
    "views.delete_partitioning_batch",
    "views.find_attribute_matches",
    "views.find_attribute_matches_batch",
    "views.find_persistence_candidates",
    "views.find_persistence_candidates_batch",
    "views.lock_partitions",
    "views.lock_partitions_batch",
    "views.persist",
    "views.persist_batch",
    "views.unlock_partitions",
    "views.unlock_partitions_batch",
    "views.unpersist",
    "views.unpersist_batch",
}


def test_all_commands_are_registered_explicitly() -> None:
    assert set(COMMANDS) == EXPECTED_COMMAND_NAMES
    assert all(command.description.strip() for command in COMMANDS.values())
    assert TASK_CHAINS_RUN_COMMAND.request_type is RunTaskChainRequest
    assert TASK_CHAINS_RUN_COMMAND.result_type is RunTaskChainResult
    assert TASK_CHAINS_RUN_COMMAND.handler is run_task_chain
    assert TASK_CHAINS_RUN_COMMAND.expose_to_mcp is True
    assert TASK_CHAINS_RUN_BATCH_COMMAND.request_type is (
        RunTaskChainBatchRequest
    )
    assert TASK_CHAINS_RUN_BATCH_COMMAND.result_type is RunTaskChainBatchResult
    assert TASK_CHAINS_RUN_BATCH_COMMAND.handler is run_task_chain_batch
    assert TASK_CHAINS_RUN_BATCH_COMMAND.expose_to_mcp is False


def test_only_reviewed_command_is_exposed_to_mcp() -> None:
    exposed = {
        name for name, command in COMMANDS.items() if command.expose_to_mcp
    }
    assert exposed == {"task_chains.run"}


def test_registered_batch_contract_has_summary_and_terminal_policy() -> None:
    result = RunTaskChainBatchResult(
        results=(
            RunTaskChainResult(
                chain="CHAIN",
                space="SPACE",
                status=TaskChainStatus.FAILED,
            ),
            RunTaskChainResult(
                chain="CHAIN",
                space="SPACE",
                status=TaskChainStatus.TIMED_OUT,
                log_id="42",
            ),
        ),
        summary=BatchSummary(2, 0, 1, 0, 1),
    )

    assert TASK_CHAINS_RUN_BATCH_COMMAND.result_type is (
        RunTaskChainBatchResult
    )
    assert result.summary == BatchSummary(2, 0, 1, 0, 1)
    assert batch_result_phase(BatchSummary(2, 2, 0, 0, 0)) is (
        CommandProgressPhase.COMPLETED
    )
    assert batch_result_phase(BatchSummary(2, 1, 1, 0, 0)) is (
        CommandProgressPhase.FAILED
    )
    assert batch_result_phase(BatchSummary(2, 1, 0, 0, 1)) is (
        CommandProgressPhase.TIMED_OUT
    )


def test_command_registry_is_immutable() -> None:
    with pytest.raises(TypeError):
        COMMANDS["other"] = TASK_CHAINS_RUN_COMMAND  # type: ignore[index]


def test_registry_rejects_duplicate_commands() -> None:
    with pytest.raises(ValueError, match="Duplicate command"):
        build_command_registry(
            [TASK_CHAINS_RUN_COMMAND, TASK_CHAINS_RUN_COMMAND]
        )


def test_command_definition_validates_metadata() -> None:
    with pytest.raises(ValueError, match="Invalid command name"):
        replace(TASK_CHAINS_RUN_COMMAND, name="Task Chains Run")
    with pytest.raises(ValueError, match="Description must not be empty"):
        replace(TASK_CHAINS_RUN_COMMAND, description=" ")
    with pytest.raises(ValueError, match="Maximum timeout"):
        replace(
            TASK_CHAINS_RUN_COMMAND,
            default_timeout_seconds=2.0,
            maximum_timeout_seconds=1.0,
        )
