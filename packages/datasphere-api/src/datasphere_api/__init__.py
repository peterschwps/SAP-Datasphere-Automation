import logging

from datasphere_api.auth import TokenDict
from datasphere_api.client import DatasphereClient
from datasphere_api.config import Browser, DatasphereConfig
from datasphere_api.exceptions import (
    AuthenticationFailed,
    DatasphereException,
    InvalidConfiguration,
    MissingCredentials,
    UnexpectedResponse,
)

# Library logger stays silent unless the consumer adds handlers
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "AuthenticationFailed",
    "Browser",
    "DatasphereClient",
    "DatasphereConfig",
    "DatasphereException",
    "InvalidConfiguration",
    "MissingCredentials",
    "TokenDict",
    "UnexpectedResponse",
]
