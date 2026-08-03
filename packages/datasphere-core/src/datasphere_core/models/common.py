from dataclasses import dataclass
from enum import StrEnum
from typing import Self

MAXIMUM_BATCH_CONCURRENCY = 10


class CommandProgressPhase(StrEnum):
    """
    Lifecycle phases of a command execution.
    """
    STARTED = "started"
    ADVANCED = "advanced"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class Outcome(StrEnum):
    """
    Final outcome of one command execution or one completed batch item.
    """
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class CommandStatus(StrEnum):
    """
    Base class for the result statuses of all commands. Every member pairs its
    own value with the outcome used for progress reporting and batch
    accounting, so that no command needs its own classification function.

    Example::

        class PersistViewStatus(CommandStatus):
            COMPLETED = "completed", Outcome.SUCCEEDED
            FAILED = "failed", Outcome.FAILED
    """
    # Only for the type checker to signalize that every member of this StrEnum
    # has an attribute 'outcome'.
    outcome: Outcome

    def __new__(cls, value: str, outcome: Outcome) -> Self:
        """
        Creates one status member from its value and its outcome. Gets
        automatically called when the inheriting class is created at import
        time.

        Example: When the ``ConfigureRemoteTableStatisticsStatus`` class is
        initiated during import time, each attribute of the class will trigger
        a call to ``__new__``. For ``CREATED`` the call would be:
        ``__new__(cls=ConfigureRemoteTableStatisticsStatus, value="created",
        outcome=Outcome.SUCCEEDED)``. This will assign the value ``created``
        and add the additional attribute ``outcome`` to ``CREATED``.

        See: https://docs.python.org/3/library/enum.html#enum.Enum.__new__.

        Args:
            value (str): Value of the status member.
            outcome (Outcome): Outcome the status belongs to.

        Returns:
            Self: Created status member.
        """
        # Create new string object with 'value' of type cls (the class that
        # inherits from CommandStatus)
        member = str.__new__(cls, value)

        # Assign value
        member._value_ = value

        # Assign additional 'outcome' attribute
        member.outcome = outcome
        return member


def validate_max_concurrency(max_concurrency: int) -> None:
    """
    Validates that a concurrency setting is within the supported limit. This
    is done to prevent rate limits when calling the internal Datasphere API.

    Args:
        max_concurrency (int): Number of operations allowed to run at once.

    Raises:
        ValueError: If the value is not in between the valid range.
    """
    if not 0 < max_concurrency <= MAXIMUM_BATCH_CONCURRENCY:
        raise ValueError(
            "Maximum concurrency must be an integer between 1 and "
            f"{MAXIMUM_BATCH_CONCURRENCY}."
        )


def validate_timeout(timeout_seconds: float, maximum: float) -> None:
    """
    Validates that a timeout is within the range its command supports. An
    invalid timeout would either fail immediately or keep the caller waiting
    far longer than intended.

    Args:
        timeout_seconds (float): Timeout of one operation in seconds.
        maximum (float): Longest timeout the command accepts.

    Raises:
        ValueError: If the timeout is not within the supported range.
    """
    if not 0 < timeout_seconds <= maximum:
        raise ValueError(
            "Timeout must be greater than zero and at most "
            f"{maximum} seconds."
        )


@dataclass(frozen=True, slots=True)
class BatchItemResult:
    """
    Result of a completed task inside a batch. Can be used to persist results
    while the batch execution is still running.

    The structure of the result object depends on the command that was called.
    """
    command: str
    item_index: int
    total_items: int
    result: object


@dataclass(frozen=True, slots=True)
class BatchSummary:
    """
    Results of a batch execution. Only created after the batch is completed.
    """
    total: int
    succeeded: int
    failed: int
    skipped: int
    timed_out: int


@dataclass(frozen=True, slots=True)
class CommandProgress:
    """
    Progress of a command execution. Contains metadata information about the
    batch if the command is executing a batch operation.
    """
    command: str
    phase: CommandProgressPhase
    message: str | None = None
    completed_items: int | None = None
    total_items: int | None = None
    succeeded_items: int | None = None
    failed_items: int | None = None
    skipped_items: int | None = None
    timed_out_items: int | None = None
    item_index: int | None = None
