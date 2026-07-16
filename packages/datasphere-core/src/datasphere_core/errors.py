import asyncio


class CommandError(Exception):
    """
    Common base class for command-layer failures.
    """


class CommandTimeoutError(CommandError):
    """
    Raised when a command exceeds its configured timeout.
    """

    def __init__(self, message: str, operation_id: str | None = None) -> None:
        self.operation_id = operation_id
        super().__init__(message)


class TokenStoreError(CommandError):
    """
    Raised when local OAuth tokens cannot be read or written.
    """


class SessionNotAuthenticatedError(CommandError):
    """
    Raised when a command requests an unauthenticated client.
    """


class CommandCancelledError(asyncio.CancelledError):
    """
    Raised when local command work is cancelled after a remote start.
    Example: Task chain was started but the user cancelled the command before
    it completed.
    """

    def __init__(self, message: str, operation_id: str | None = None) -> None:
        self.operation_id = operation_id
        super().__init__(message)
