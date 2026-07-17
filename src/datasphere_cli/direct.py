import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from typing import Literal

from datasphere_core import (
    TASKCHAIN_START_COMMAND,
    CommandContext,
    CommandError,
    DatasphereSession,
    StartTaskChainRequest,
    StartTaskChainResult,
    start_task_chain,
)

# TODO: Implement commands incl. help with Typer

def _create_parser() -> argparse.ArgumentParser:
    """
    Creates an ArgumentParser for the CLI commands.

    Returns:
        argparse.ArgumentParser: ArgumentParser instance with the configured
                                 commands and options.
    """
    parser = argparse.ArgumentParser(prog="datasphere")

    # Define the 'taskchain' command and its subcommands
    domains = parser.add_subparsers(dest="domain", required=True)
    taskchain = domains.add_parser(
        "taskchain",
        help="Manage task chains.",
    )
    taskchain_actions = taskchain.add_subparsers(
        dest="action",
        required=True,
    )
    start = taskchain_actions.add_parser(
        "start",
        help=TASKCHAIN_START_COMMAND.cli_description,
    )

    # Define arguments for the 'start' subcommand
    start.add_argument(
        "chain",
        help="Technical name of the task chain."
    )
    start.add_argument(
        "--space",
        required=True,
        help="Technical name of the Datasphere space.",
    )
    start.add_argument(
        "--timeout",
        type=float,
        default=TASKCHAIN_START_COMMAND.default_timeout_seconds,
        help="Maximum runtime in seconds.",
    )
    start.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    return parser


async def execute_task_chain(
    request: StartTaskChainRequest,
) -> StartTaskChainResult:
    """
    Executes a task-chain command using the configured tenant.

    Args:
        request (StartTaskChainRequest): Object with parameters required to
                                         execute the task.

    Raises:
        CommandError: If no settings file is found.

    Returns:
        StartTaskChainResult: Object with the result of the executed task.
    """
    from datasphere_cli.utils.settings import (
        SETTINGS_FILE,
        build_session_config,
    )

    # Check if the settings file exists
    if not SETTINGS_FILE.exists():
        raise CommandError(
            "Settings are not initialized. Start 'datasphere' once to "
            "create the settings file."
        )

    # Build the session configuration and execute the task chain
    config = build_session_config()
    async with DatasphereSession(config) as session:
        await session.authenticate(interactive=True)
        return await start_task_chain(
            context=CommandContext(client=session.client),
            request=request,
        )


def _print_result(
        result: StartTaskChainResult,
        output: Literal['text', 'json']
    ) -> None:
    """
    Prints the result of an executed task. Formats JSON output (e.g. to use it
    when calling the task from an MCP) or prints a human-readable message
    otherwise.

    Args:
        result (StartTaskChainResult): Result of the executed task.
        output (Literal['text', 'json'] ): Output format. Formats JSON if
                                           specified, otherwise prints a
                                           human-readable message.
    """
    if output == "json":
        print(json.dumps(asdict(result), separators=(",", ":")))
    else:
        print(
            f"Task chain '{result.chain}' in '{result.space}': {result.status}"
        )


def run(argv: Sequence[str]) -> int:
    """
    Runs a direct command and returns its process exit code.

    Args:
        argv (Sequence[str]): Arguments provided when calling a command.

    Returns:
        int: Exit code of the executed command. 0 if successful, otherwise 1.
    """
    # Parse arguments
    parser = _create_parser()
    args = parser.parse_args(argv)

    # Create command request from parsed arguments
    try:
        request = StartTaskChainRequest(
            chain=args.chain,
            space=args.space,
            timeout_seconds=args.timeout,
        )
    except ValueError as error:
        parser.error(str(error))

    # Execute command
    try:
        result = asyncio.run(execute_task_chain(request))
    except (CommandError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Unexpected error: {error}", file=sys.stderr)
        return 1

    # Print result and return exit code
    _print_result(result, args.output)
    return 0 if result.status == "completed" else 1
