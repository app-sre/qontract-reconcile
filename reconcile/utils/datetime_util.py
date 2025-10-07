from datetime import UTC, datetime

ISO8601 = "%Y-%m-%dT%H:%M:%SZ"
ISO8601_MICRO = "%Y-%m-%dT%H:%M:%S.%fZ"


def utc_now() -> datetime:
    """
    Get the current UTC datetime.

    Returns:
        A datetime object representing the current time in UTC.
    """
    return datetime.now(tz=UTC)


def ensure_utc(dt: datetime) -> datetime:
    """
    Ensure the provided datetime is in UTC timezone.

    Args:
        dt: A datetime object.

    Returns:
        A datetime object in UTC timezone.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_utc_seconds_iso_format(dt: datetime) -> str:
    """
    Convert a datetime object to ISO 8601 format YYYY-MM-DDTHH:MM:SSZ.

    Args:
        dt: A datetime object.

    Returns:
        A string representing the datetime in ISO 8601 format.
    """
    return ensure_utc(dt).strftime(ISO8601)


def to_utc_microseconds_iso_format(dt: datetime) -> str:
    """
    Convert a datetime object to ISO 8601 format with microseconds YYYY-MM-DDTHH:MM:SS.mmmmmmZ.

    Args:
        dt: A datetime object.

    Returns:
        A string representing the datetime in ISO 8601 format with microseconds.
    """
    return ensure_utc(dt).strftime(ISO8601_MICRO)


def from_utc_iso_format(dt_str: str) -> datetime:
    """
    Parse a datetime string in ISO 8601 format to a datetime object.

    Args:
        dt_str: A string representing the datetime in ISO 8601 format.
    Returns:
        A datetime object in UTC timezone.
    """
    return ensure_utc(datetime.fromisoformat(dt_str))
