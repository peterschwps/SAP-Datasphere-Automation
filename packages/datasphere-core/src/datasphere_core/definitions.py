import math
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from datasphere_core.context import CommandContext

# Command name pattern: lowercase words separated by underscores, with a single
#                       dot separating the adapter and command names
_COMMAND_NAME_PATTERN = re.compile(r"[a-z]+(?:_[a-z]+)*\.[a-z]+(?:_[a-z]+)*")

# Type alias for command handler: receives RequestT and returns ResultT
type CommandHandler[RequestT, ResultT] = Callable[
    [CommandContext, RequestT],
    Awaitable[ResultT],
]


@dataclass(frozen=True, slots=True)
class CommandDefinition[RequestT, ResultT]:
    """
    Validated metadata and handler for one application command.
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

    def __post_init__(self) -> None:
        """
        Simple validation of the command definition to catch mistakes.

        Raises:
            ValueError: If the command name is invalid.
            ValueError: If the CLI description is empty.
            ValueError: If the MCP description is empty.
            ValueError: If the default timeout is not a positive number.
            ValueError: If the maximum timeout is not finite or less than the
                        default.
            ValueError: If a read-only command is marked as destructive.
        """
        # Check command name
        if _COMMAND_NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError(f"Invalid command name: {self.name!r}.")

        # Check CLI and MCP description
        if not self.cli_description.strip():
            raise ValueError("CLI description must not be empty.")
        if not self.mcp_description.strip():
            raise ValueError("MCP description must not be empty.")

        # Check default timeout
        if (
            isinstance(self.default_timeout_seconds, bool)
            or not math.isfinite(self.default_timeout_seconds)
            or self.default_timeout_seconds <= 0
        ):
            raise ValueError("Default timeout must be a positive number.")

        # Check maximum timeout
        if (
            isinstance(self.maximum_timeout_seconds, bool)
            or not math.isfinite(self.maximum_timeout_seconds)
            or self.maximum_timeout_seconds
            < self.default_timeout_seconds
        ):
            raise ValueError(
                "Maximum timeout must be finite and at least the default."
            )

        # Check read-only and destructive flags
        if self.read_only and self.destructive:
            raise ValueError(
                "A read-only command cannot be marked as destructive."
            )

# Mapping of command names to their definitions
type CommandRegistry = Mapping[str, CommandDefinition[Any, Any]]


def build_command_registry(
    definitions: Iterable[CommandDefinition[Any, Any]],
) -> CommandRegistry:
    """
    Builds an immutable command registry and rejects duplicate command names.

    Args:
        definitions (Iterable[CommandDefinition[Any, Any]]): Iterable of
                                                             command
                                                             definitions to
                                                             include in the
                                                             registry.

    Raises:
        ValueError: If a duplicate command name is found in the definitions.
                    This is done to prevent accidental overwriting of command
                    definitions.

    Returns:
        CommandRegistry: Immutable mapping of command names to their
                         definitions.
    """
    commands: dict[str, CommandDefinition[Any, Any]] = {}
    for definition in definitions:
        if definition.name in commands:
            error_msg = f"Duplicate command definition: {definition.name!r}."
            raise ValueError(error_msg)
        commands[definition.name] = definition
    return MappingProxyType(commands)
