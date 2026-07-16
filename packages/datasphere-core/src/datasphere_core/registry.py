from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from datasphere_core.commands.task_chains import start_task_chain
from datasphere_core.context import CommandContext
from datasphere_core.models import (
    DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS,
    MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS,
    StartTaskChainRequest,
    StartTaskChainResult,
)

# Signature of a command handler function:
#   - receives a command context
#   - receives a request object with the required parameters for the command
#   - returns a result object with the command's result
type CommandHandler[RequestT, ResultT] = Callable[
    [CommandContext, RequestT],
    Awaitable[ResultT],
]


@dataclass(frozen=True, slots=True)
class CommandDefinition[RequestT, ResultT]:
    """
    Metadata and handler for one application command.
    """
    name: str
    request_type: type[RequestT]
    result_type: type[ResultT]
    handler: CommandHandler[RequestT, ResultT]
    cli_description: str
    mcp_description: str
    default_timeout_seconds: float
    maximum_timeout_seconds: float
    read_only: bool
    destructive: bool
    idempotent: bool
    expose_to_mcp: bool


TASKCHAIN_START_COMMAND = CommandDefinition(
    name="taskchain.start",
    request_type=StartTaskChainRequest,
    result_type=StartTaskChainResult,
    handler=start_task_chain,
    cli_description="Start a task chain and wait for its result.",
    mcp_description=(
        "Start a SAP Datasphere task chain and wait for its terminal result."
    ),
    default_timeout_seconds=DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=False,
    expose_to_mcp=True,
)

# Mapping of all available commands
COMMANDS: dict[str, CommandDefinition[Any, Any]] ={
    TASKCHAIN_START_COMMAND.name: TASKCHAIN_START_COMMAND
}
