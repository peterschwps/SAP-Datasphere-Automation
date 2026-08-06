from typing import Any


def to_text(value: object) -> str | None:
    """
    Converts a value from a Datasphere response into a string. Datasphere
    returns logIds as integers and statuses as strings, so both are normalized
    to a string.

    Args:
        value (object): Value taken from a Datasphere response.

    Returns:
        str | None: String representation, or None if the value is missing or
                    not an integer or string.
    """
    if isinstance(value, int | str):
        return str(value)
    return None


def runtime_to_seconds(log_details: dict[str, Any]) -> int | None:
    """
    Converts the millisecond runtime of a Datasphere log entry to rounded
    seconds.

    Args:
        log_details (dict[str, Any]): Log details containing ``runTime``.

    Returns:
        int | None: Rounded runtime in seconds, or None if the key is missing
                    or holds an unsupported value.
    """
    runtime = log_details.get("runTime")
    if isinstance(runtime, int | float) and runtime >= 0:
        return round(runtime / 1000)
    return None


def format_runtime(seconds: float) -> str:
    """
    Formats a duration as hours, minutes and seconds. Hours are not wrapped
    at a day, because a run may legitimately take longer than that.

    Args:
        seconds (float): Duration to format.

    Returns:
        str: Duration as 'HH:MM:SS'.
    """
    hours, remainder = divmod(int(seconds), 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{remaining_seconds:02}"
