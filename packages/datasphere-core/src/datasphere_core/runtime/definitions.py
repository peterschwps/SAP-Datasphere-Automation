import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from datasphere_core.runtime.execution import CommandHandler

# Command name pattern: lowercase words separated by underscores, with a single
#                       dot separating the adapter and command names
_COMMAND_NAME_PATTERN = re.compile(r"[a-z]+(?:_[a-z]+)*\.[a-z]+(?:_[a-z]+)*")


@dataclass(frozen=True, slots=True)
class CommandDefinition[RequestT, ResultT]:
    """
    Validated metadata and handler for one application command.
    """
    name: str
    request_type: type[RequestT]
    result_type: type[ResultT]
    handler: CommandHandler[RequestT, ResultT]
    description: str
    default_timeout_seconds: float
    maximum_timeout_seconds: float
    read_only: bool
    destructive: bool
    idempotent: bool
    expose_to_mcp: bool

    def __post_init__(self) -> None:
        """
        Validates the command name to catch typos in the registry at import
        time.

        Raises:
            ValueError: If the command name is invalid.
        """
        if _COMMAND_NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError(f"Invalid command name: {self.name!r}.")


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
