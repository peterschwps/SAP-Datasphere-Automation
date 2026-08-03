from uuid import uuid4


def request_headers(**extra: str) -> dict[str, str]:
    """
    Builds the headers a Datasphere request carries. Every request gets its
    own identifier, which the tenant echoes in its logs.

    Args:
        **extra (str): Additional headers, merged over the defaults.

    Returns:
        dict[str, str]: Headers for one request.
    """
    return {"Accept": "*/*", "x-request-id": uuid4().hex, **extra}
