from collections.abc import Iterator

import pytest
from datasphere_core import stop_http_logging


@pytest.fixture(autouse=True)
def stop_logging_after_the_test() -> Iterator[None]:
    """
    Closes a log a test left behind. The log is global, so one failed test
    would otherwise write its successors into a stale file.
    """
    yield
    stop_http_logging()
