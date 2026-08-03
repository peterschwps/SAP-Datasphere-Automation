import ast
import pathlib
from collections.abc import Iterator

import datasphere_core.commands
from datasphere_core import COMMANDS

COMMANDS_PATH = pathlib.Path(datasphere_core.commands.__file__).parent

# Decorators that turn a function into a registered command
_COMMAND_DECORATORS = {"command", "batch_command"}


def _command_handlers() -> Iterator[tuple[str, ast.AsyncFunctionDef]]:
    """
    Yields every decorated command handler with the module it lives in.
    """
    for path in sorted(COMMANDS_PATH.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            decorators = {
                decorator.func.id
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
            }
            if decorators & _COMMAND_DECORATORS:
                yield path.name, node


def _reaches_for_the_session(node: ast.AST) -> bool:
    """
    Checks whether a syntax tree touches the session of its context.
    """
    return any(
        isinstance(child, ast.Attribute)
        and child.attr == "session"
        and isinstance(child.value, ast.Name)
        and child.value.id == "context"
        for child in ast.walk(node)
    )


def test_command_handlers_do_not_send_requests_themselves() -> None:
    """
    Checks that no command handler builds a request of its own.
    """
    handlers = list(_command_handlers())

    # A guard that finds nothing to guard would pass silently forever
    assert len(handlers) == len(COMMANDS)

    # Every request belongs in its own function, so a handler stays readable
    # and each endpoint has exactly one place that knows it
    offenders = [
        f"{module}::{handler.name}"
        for module, handler in handlers
        if _reaches_for_the_session(handler)
    ]
    assert offenders == []
