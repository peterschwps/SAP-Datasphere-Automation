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
