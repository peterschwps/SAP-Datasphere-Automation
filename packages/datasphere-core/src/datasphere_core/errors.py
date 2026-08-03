import asyncio


class CommandError(Exception):
    """
    Common base class for command-layer failures.
    """


class CommandTimeoutError(CommandError):
    """
    Raised when a command exceeds its configured timeout.
    """

    def __init__(self, message: str, log_id: str | None = None) -> None:
        """
        Initializes the error with the log ID of the timed-out run.

        Args:
            message (str): Message describing the timeout.
            log_id (str | None, optional): Log ID of the remote run.
                                           Defaults to None.
        """
        self.log_id = log_id
        super().__init__(message)


class TokenStoreError(CommandError):
    """
    Raised when local OAuth tokens cannot be read or written.
    """


class AuthenticationError(CommandError):
    """
    Raised when a session cannot be authenticated against its tenant.
    """


class InvalidConfigurationError(CommandError):
    """
    Raised when a session configuration cannot be used as given.
    """


class SessionNotAuthenticatedError(CommandError):
    """
    Raised when a command requests an unauthenticated client.
    """


class UnexpectedResponseError(CommandError):
    """
    Raised when the tenant answers in a way a command cannot work with.
    """


class CommandCancelledError(asyncio.CancelledError):
    """
    Raised when local command work is cancelled after a remote start.
    Example: Task chain was started but the user cancelled the command before
    it completed.
    """

    def __init__(self, message: str, log_id: str | None = None) -> None:
        """
        Initializes the error with the log ID of the started run.

        Args:
            message (str): Message describing the cancellation.
            log_id (str | None, optional): Log ID of the remote run
                                           that may still continue.
                                           Defaults to None.
        """
        self.log_id = log_id
        super().__init__(message)
