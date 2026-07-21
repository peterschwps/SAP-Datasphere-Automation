import asyncio
from typing import Literal


class DatasphereException(Exception):
    """
    Common base class for all exceptions raised by this library.
    """


class AuthenticationFailed(DatasphereException):
    pass


class InvalidConfiguration(DatasphereException):
    pass


class MissingCredentials(DatasphereException):
    def __init__(self) -> None:
        super().__init__(
            "Client secret not found. Please provide a client secret in "
            "the configuration."
        )


class UnexpectedResponse(DatasphereException):
    pass


class TaskChainTimeout(DatasphereException):
    """
    Raised when a started task chain does not finish in time.
    """

    def __init__(self, chain: str, space: str, log_id: int) -> None:
        self.chain = chain
        self.space = space
        self.log_id = log_id
        super().__init__(
            f"Task chain '{chain}' in '{space}' exceeded its timeout "
            f"(log ID: {log_id})."
        )


class TaskChainCancelled(asyncio.CancelledError):
    """
    Raised when local polling is cancelled after a chain started.
    """

    def __init__(self, chain: str, space: str, log_id: int) -> None:
        self.chain = chain
        self.space = space
        self.log_id = log_id
        super().__init__(
            f"Local polling for task chain '{chain}' in '{space}' was "
            f"cancelled. The remote operation may continue (log ID: {log_id})."
        )


class ViewPersistenceTimeout(DatasphereException):
    """
    Raised when a started view persistence operation does not finish in time.
    """

    def __init__(
        self,
        operation: Literal["persist", "unpersist"],
        view: str,
        space: str,
        log_id: int,
    ) -> None:
        self.operation = operation
        self.view = view
        self.space = space
        self.log_id = log_id
        super().__init__(
            f"View {operation} operation for '{view}' in '{space}' exceeded "
            f"its timeout. The remote operation may continue "
            f"(log ID: {log_id})."
        )


class ViewPersistenceCancelled(asyncio.CancelledError):
    """
    Raised when local polling for a view persistence operation is cancelled.
    """

    def __init__(
        self,
        operation: Literal["persist", "unpersist"],
        view: str,
        space: str,
        log_id: int,
    ) -> None:
        self.operation = operation
        self.view = view
        self.space = space
        self.log_id = log_id
        super().__init__(
            f"Local polling for view {operation} operation '{view}' in "
            f"'{space}' was cancelled. The remote operation may continue "
            f"(log ID: {log_id})."
        )


class ViewAnalysisTimeout(DatasphereException):
    """
    Raised when a started view analysis does not finish in time.
    """

    def __init__(
        self,
        view: str,
        space: str,
        log_id: int | None,
    ) -> None:
        self.view = view
        self.space = space
        self.log_id = log_id
        log_details = f"log ID: {log_id}" if log_id is not None else ""
        super().__init__(
            f"View analysis for '{view}' in '{space}' exceeded its timeout. "
            f"The remote operation may continue ({log_details})."
        )


class ViewAnalysisCancelled(asyncio.CancelledError):
    """
    Raised when local polling for a started view analysis is cancelled.
    """

    def __init__(
        self,
        view: str,
        space: str,
        log_id: int | None,
    ) -> None:
        self.view = view
        self.space = space
        self.log_id = log_id
        log_details = f"log ID: {log_id}" if log_id is not None else ""
        super().__init__(
            f"Local polling for view analysis '{view}' in '{space}' was "
            f"cancelled. The remote operation may continue ({log_details})."
        )
