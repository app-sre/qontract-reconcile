DAY_TO_SECONDS = 24 * 3600
HOUR_TO_SECONDS = 3600
MINUTE_TO_SECONDS = 60


class BadHDMSDurationError(Exception):
    pass


def _days_to_seconds(days: int) -> int:
    return days * DAY_TO_SECONDS


def _hours_to_seconds(hours: int) -> int:
    return hours * HOUR_TO_SECONDS


def _minutes_to_seconds(minutes: int) -> int:
    return minutes * MINUTE_TO_SECONDS


def _seconds_to_seconds(seconds: int) -> int:
    return seconds


HANDLE_UNIT_MAP = {
    "d": _days_to_seconds,
    "h": _hours_to_seconds,
    "m": _minutes_to_seconds,
    "s": _seconds_to_seconds,
}


def seconds_to_hms(seconds: int) -> str:
    minutes, s = divmod(seconds, 60)
    if minutes == 0:
        return f"{s}s"

    h, m = divmod(minutes, 60)
    if h == 0:
        return f"{m}m{s}s"

    return f"{h}h{m}m{s}s"


def dhms_to_seconds(time_str: str) -> int:
    """Parses durations and returns seconds. The format is a subset of Go's
    ParseDuration format, only allowing from days to seconds in resolution,
    e.g. "1h", "1d1h1m2s", ...
    """
    total_seconds = 0
    s = previous_number = time_str[0]

    if not previous_number.isnumeric():
        raise BadHDMSDurationError(f"Invalid time duration {time_str}")

    for s in time_str[1:]:
        if s.isnumeric():
            previous_number += s
        else:
            if not previous_number:
                raise BadHDMSDurationError(f"Invalid time duration {time_str}")

            if s in HANDLE_UNIT_MAP:
                total_seconds += HANDLE_UNIT_MAP[s](int(previous_number))
                previous_number = ""
            else:
                raise BadHDMSDurationError(
                    f"Invalid unit {s} in time duration {time_str}"
                )

    if s.isnumeric():
        raise BadHDMSDurationError(f"Invalid time duration {time_str}")

    return total_seconds
