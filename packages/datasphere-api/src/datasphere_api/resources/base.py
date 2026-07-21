import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datasphere_api.client import DatasphereClient


class BaseResource:
    def __init__(self, client: "DatasphereClient"):
        """
        Initializes the resource with a shared client. The client owns the
        authenticated session that is used for all requests.

        Args:
            client (DatasphereClient): Client to send requests with.
        """
        self._client = client
        self.session = client.session
        self._base_url = client.config.base_url


def validate_timeout(timeout_seconds: float | None) -> None:
    """
    Validates a value to be a valid timeout.

    Args:
        timeout_seconds (float | None): Value to validate.

    Raises:
        ValueError: If the timeout is a boolean, non-finite, or not positive.
    """
    if timeout_seconds is None:
        return
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("Timeout must be a positive number.")
