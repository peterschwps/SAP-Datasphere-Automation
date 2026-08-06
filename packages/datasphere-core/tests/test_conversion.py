import pytest
from datasphere_core.commands.shared.conversion import format_runtime


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00"),
        (59.9, "00:00:59"),
        (753, "00:12:33"),
        (3600, "01:00:00"),
        # A run may take longer than a day, so the hours must not wrap
        (90061, "25:01:01"),
    ],
)
def test_a_runtime_is_formatted_as_hours_minutes_and_seconds(
    seconds: float,
    expected: str,
) -> None:
    """
    Checks that a duration reads as 'HH:MM:SS' at every magnitude.
    """
    assert format_runtime(seconds) == expected
