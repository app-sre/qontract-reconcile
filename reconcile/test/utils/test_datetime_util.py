import datetime

import pytest

from reconcile.utils.datetime_util import (
    ensure_utc,
    from_utc_iso_format,
    to_utc_microseconds_iso_format,
    to_utc_seconds_iso_format,
)


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0),  # noqa: DTZ001
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=datetime.UTC),
        ),
        (
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=datetime.UTC),
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=datetime.UTC),
        ),
        (
            datetime.datetime(
                2025,
                1,
                1,
                1,
                0,
                0,
                0,
                tzinfo=datetime.timezone(datetime.timedelta(hours=1)),
            ),
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=datetime.UTC),
        ),
    ],
)
def test_ensure_utc(dt: datetime.datetime, expected: datetime.datetime) -> None:
    result = ensure_utc(dt)

    assert result == expected
    assert result.tzinfo == datetime.UTC


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0),  # noqa: DTZ001
            "2025-01-01T00:00:00Z",
        ),
        (
            datetime.datetime(2025, 1, 1, 0, 0, 0, 1),  # noqa: DTZ001
            "2025-01-01T00:00:00Z",
        ),
        (
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=datetime.UTC),
            "2025-01-01T00:00:00Z",
        ),
        (
            datetime.datetime(
                2025,
                1,
                1,
                1,
                0,
                0,
                0,
                tzinfo=datetime.timezone(datetime.timedelta(hours=1)),
            ),
            "2025-01-01T00:00:00Z",
        ),
    ],
)
def test_to_utc_seconds_iso_format(dt: datetime.datetime, expected: str) -> None:
    result = to_utc_seconds_iso_format(dt)

    assert result == expected


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0),  # noqa: DTZ001
            "2025-01-01T00:00:00.000000Z",
        ),
        (
            datetime.datetime(2025, 1, 1, 0, 0, 0, 1),  # noqa: DTZ001
            "2025-01-01T00:00:00.000001Z",
        ),
        (
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=datetime.UTC),
            "2025-01-01T00:00:00.000000Z",
        ),
        (
            datetime.datetime(
                2025,
                1,
                1,
                1,
                0,
                0,
                0,
                tzinfo=datetime.timezone(datetime.timedelta(hours=1)),
            ),
            "2025-01-01T00:00:00.000000Z",
        ),
    ],
)
def test_to_utc_microseconds_iso_format(dt: datetime.datetime, expected: str) -> None:
    result = to_utc_microseconds_iso_format(dt)

    assert result == expected


@pytest.mark.parametrize(
    ("dt_str", "expected"),
    [
        (
            "2025-01-01T00:00:00",
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=datetime.UTC),
        ),
        (
            "2025-01-01T00:00:00.000001Z",
            datetime.datetime(2025, 1, 1, 0, 0, 0, 1, tzinfo=datetime.UTC),
        ),
        (
            "2025-01-01T00:00:00Z",
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=datetime.UTC),
        ),
        (
            "2025-01-01T01:00:00.000000+01:00",
            datetime.datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=datetime.UTC),
        ),
    ],
)
def test_from_utc_iso_format(dt_str: str, expected: datetime.datetime) -> None:
    result = from_utc_iso_format(dt_str)

    assert result == expected
    assert result.tzinfo == datetime.UTC
