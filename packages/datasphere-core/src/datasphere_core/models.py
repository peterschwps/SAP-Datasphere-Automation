from dataclasses import dataclass
from typing import Literal

DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS = 3600.0
MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS = 86400.0

# Different phases of a command's execution
# (used to report progress to the caller)
type CommandProgressPhase = Literal[
    "started",
    "completed",
    "failed",
    "timed_out",
    "cancelled",
]

# Different statuses of a completed task chain execution
# (used to report the result to the caller)
type TaskChainStatus = Literal[
    "completed",
    "failed",
    "start_failed",
]


@dataclass(frozen=True, slots=True)
class CommandProgress:
    """
    Progress update emitted by a command.
    """
    command: str
    phase: CommandProgressPhase
    message: str | None = None


@dataclass(frozen=True, slots=True)
class StartTaskChainRequest:
    """
    Input for starting and awaiting one task chain.
    """
    chain: str
    space: str
    timeout_seconds: float | None = DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """
        Simple validation of the attributes.
        """
        if not self.chain.strip():
            raise ValueError("Task chain must not be empty.")
        if not self.space.strip():
            raise ValueError("Space must not be empty.")
        if self.timeout_seconds is None:
            return
        if not 0 < self.timeout_seconds <= MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS:
            raise ValueError(
                "Timeout must be greater than zero and at most "
                f"{MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS} seconds."
            )


@dataclass(frozen=True, slots=True)
class StartTaskChainResult:
    """
    Result of one task-chain execution.
    """
    chain: str
    space: str
    status: TaskChainStatus
    sap_status: str | None
    runtime_seconds: int | None
