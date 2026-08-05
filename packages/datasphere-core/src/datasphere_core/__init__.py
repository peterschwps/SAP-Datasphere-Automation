# ruff: noqa: F401

# Imported by name, because importing the module would bind 'logging' to the
# submodule of this package instead of the standard library one
from logging import NullHandler, getLogger

from datasphere_core.errors import (
    AuthenticationError,
    CommandCancelledError,
    CommandError,
    CommandTimeoutError,
    InvalidConfigurationError,
    SessionNotAuthenticatedError,
    TokenStoreError,
    UnexpectedResponseError,
)
from datasphere_core.http_logging import (
    http_logging_hooks,
    is_http_logging,
    start_http_logging,
    stop_http_logging,
)
from datasphere_core.logging import SUCCESS
from datasphere_core.runtime.context import (
    BatchItemResultCallback,
    CommandContext,
    ProgressCallback,
)
from datasphere_core.runtime.definitions import (
    CommandDefinition,
    CommandRegistry,
)
from datasphere_core.runtime.execution import (
    BatchReporter,
    CommandHandler,
    batch_command,
    command,
    execute_with_concurrency_limit,
    run_batch,
)
from datasphere_core.runtime.registry import COMMANDS
from datasphere_core.session.auth import DatasphereSession
from datasphere_core.session.config import Browser, SessionConfig
from datasphere_core.session.credentials import (
    KeyringTokenStore,
    TokenDict,
    TokenStore,
)

# Library logger stays silent unless the consumer adds handlers
getLogger(__name__).addHandler(NullHandler())

# Only for type checking
__all__ = [
    "AuthenticationError",
    "CommandCancelledError",
    "CommandError",
    "CommandTimeoutError",
    "InvalidConfigurationError",
    "SessionNotAuthenticatedError",
    "TokenStoreError",
    "UnexpectedResponseError",

    "SUCCESS",

    "BatchItemResultCallback",
    "CommandContext",
    "ProgressCallback",

    "CommandDefinition",
    "CommandRegistry",

    "BatchReporter",
    "CommandHandler",
    "batch_command",
    "command",
    "execute_with_concurrency_limit",
    "run_batch",

    "COMMANDS",

    "DatasphereSession",

    "Browser",
    "SessionConfig",

    "KeyringTokenStore",
    "TokenDict",
    "TokenStore",

    "http_logging_hooks",
    "is_http_logging",
    "start_http_logging",
    "stop_http_logging",
]
