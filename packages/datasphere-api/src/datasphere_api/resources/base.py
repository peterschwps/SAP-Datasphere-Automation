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
