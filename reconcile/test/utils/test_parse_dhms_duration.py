import pytest

from reconcile.utils.parse_dhms_duration import (
    BadHDMSDurationError,
    dhms_to_seconds,
    seconds_to_hms,
)


@pytest.mark.parametrize(
    "test_input, expected",
    [
        ("3s", 3),
        ("1h30m", 5400),
        ("2m", 120),
        ("2h", 7200),
        ("1d", 86400),
        ("1m1s", 61),
        ("2h1m1s", 7261),
        ("2d1h1m2s", 176462),
        ("1s2h", 7201),
        ("1s1m1s", 62),
    ],
)
def test_valid_duration(test_input: str, expected: int) -> None:
    assert dhms_to_seconds(test_input) == expected


@pytest.mark.parametrize(
    "bad_input",
    ["2", "35", "1d1", "1d1j", "2hh", "ms"],
)
def test_invalid_duration(bad_input: str):
    with pytest.raises(BadHDMSDurationError):
        dhms_to_seconds(bad_input)


@pytest.mark.parametrize(
    "test_input, expected",
    [
        ("3s", "3s"),
        ("2m1s", "2m1s"),
        ("2m", "2m0s"),
        ("3h2m1s", "3h2m1s"),
        ("3h2m", "3h2m0s"),
        ("3h", "3h0m0s"),
        ("4d3h2m1s", "99h2m1s"),
        ("4d3h2m", "99h2m0s"),
        ("4d3h", "99h0m0s"),
        ("4d", "96h0m0s"),
        ("90m", "1h30m0s"),
    ],
)
def test_format_valid_duration(test_input: str, expected: int) -> None:
    assert seconds_to_hms(dhms_to_seconds(test_input)) == expected
