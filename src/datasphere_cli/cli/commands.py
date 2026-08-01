import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from typing import Literal

from datasphere_core import (
    COMMANDS,
    CommandContext,
    CommandError,
    DatasphereSession,
)
from datasphere_core.commands.task_chains import run_task_chain as run_command
from datasphere_core.models.task_chains import (
    RunTaskChainRequest,
    RunTaskChainResult,
)

_COMMAND = "task_chains.run"


def _create_parser() -> argparse.ArgumentParser:
    """
    Create the parser for canonical direct CLI commands.
    """
    parser = argparse.ArgumentParser(prog="datasphere")
    domains = parser.add_subparsers(dest="domain", required=True)
    task_chains = domains.add_parser(
        "task-chains",
        help="Manage task chains.",
    )
    actions = task_chains.add_subparsers(dest="action", required=True)
    run = actions.add_parser(
        "run",
        help=COMMANDS[_COMMAND].description,
    )
    run.add_argument("chain", help="Technical name of the task chain.")
    run.add_argument(
        "--space",
        required=True,
        help="Technical name of the Datasphere space.",
    )
    run.add_argument(
        "--timeout",
        type=float,
        default=COMMANDS[_COMMAND].default_timeout_seconds,
        help="Maximum runtime in seconds.",
    )
    run.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    return parser


async def run_task_chain(
    request: RunTaskChainRequest,
) -> RunTaskChainResult:
    """
    Execute the task-chain command for the configured tenant.

    Args:
        request (RunTaskChainRequest): Task-chain name, space, and timeout.

    Returns:
        RunTaskChainResult: Task-chain execution result.
    """
    from datasphere_cli.settings import SETTINGS_FILE, build_session_config

    if not SETTINGS_FILE.exists():
        raise CommandError(
            "Settings are not initialized. Start 'datasphere' once to "
            "create the settings file."
        )

    config = build_session_config()
    async with DatasphereSession(config) as session:
        await session.authenticate(interactive=True)
        return await run_command(
            CommandContext(client=session.client),
            request,
        )


def _print_result(
    result: RunTaskChainResult,
    output: Literal["text", "json"],
) -> None:
    """
    Prints one task chain result as text or JSON.

    Args:
        result (RunTaskChainResult): Result to print.
        output (Literal["text", "json"]): Requested output format.
    """
    if output == "json":
        print(json.dumps(asdict(result), separators=(",", ":")))
        return
    print(
        f"Task chain '{result.chain}' in '{result.space}': {result.status}"
    )


def run(argv: Sequence[str]) -> int:
    """
    Run a direct command and return its process exit code.

    Args:
        argv (Sequence[str]): Command-line arguments without the executable.

    Returns:
        int: Process exit code; zero indicates a completed command.
    """
    parser = _create_parser()
    args = parser.parse_args(argv)
    try:
        request = RunTaskChainRequest(
            chain=args.chain,
            space=args.space,
            timeout_seconds=args.timeout,
        )
    except ValueError as error:
        parser.error(str(error))

    try:
        result = asyncio.run(run_task_chain(request))
    except (CommandError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Unexpected error: {error}", file=sys.stderr)
        return 1

    _print_result(result, args.output)
    return 0 if result.status == "completed" else 1
