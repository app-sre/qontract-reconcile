from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import requests

from tools.cli_commands import rds_eol

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

RDS_EOL_SAMPLE: list[dict[str, str]] = [
    {"engine": "postgres", "version": "15.12", "eol": "2026-03-31"},
    {"engine": "postgres", "version": "15.13", "eol": "2026-09-30"},
    {"engine": "postgres", "version": "16.8", "eol": "2026-03-31"},
    {"engine": "postgres", "version": "16.9", "eol": "2026-09-30"},
    {"engine": "mysql", "version": "8.4.9", "eol": "2026-09-30"},
    {"engine": "mysql", "version": "8.4.10", "eol": "2027-01-31"},
]


def test_build_eol_lookup_exact_match() -> None:
    lookup = rds_eol.build_eol_lookup(RDS_EOL_SAMPLE)
    assert lookup["postgres", "15.13"] == "2026-09-30"
    assert lookup["mysql", "8.4.10"] == "2027-01-31"
    assert ("postgres", "17") not in lookup
    assert ("postgres", "15") not in lookup


def test_build_eol_lookup_skips_incomplete_entries() -> None:
    lookup = rds_eol.build_eol_lookup([
        {"engine": "postgres", "version": "15.13"},
        {"engine": "postgres", "eol": "2026-09-30"},
        {"version": "15.13", "eol": "2026-09-30"},
        {"engine": "postgres", "version": "15.13", "eol": "2026-09-30"},
    ])
    assert lookup == {("postgres", "15.13"): "2026-09-30"}


def test_next_version_stays_in_same_major() -> None:
    lookup = rds_eol.build_next_version_lookup(RDS_EOL_SAMPLE, today="2026-08-17")
    assert lookup["postgres", "15.12"] == "15.13"
    assert lookup["postgres", "16.8"] == "16.9"
    assert lookup["mysql", "8.4.9"] == "8.4.10"
    assert ("postgres", "15.13") not in lookup
    assert lookup["postgres", "15.12"] != "16.8"


def test_next_version_skips_candidates_past_eol() -> None:
    data = [
        {"engine": "postgres", "version": "15.10", "eol": "2025-01-01"},
        {"engine": "postgres", "version": "15.11", "eol": "2025-06-01"},
        {"engine": "postgres", "version": "15.12", "eol": "2026-09-30"},
    ]
    lookup = rds_eol.build_next_version_lookup(data, today="2026-08-17")
    assert lookup["postgres", "15.10"] == "15.12"
    assert lookup["postgres", "15.11"] == "15.12"
    assert ("postgres", "15.12") not in lookup


def test_next_version_blank_when_higher_versions_are_eol() -> None:
    data = [
        {"engine": "postgres", "version": "15.10", "eol": "2026-09-30"},
        {"engine": "postgres", "version": "15.11", "eol": "2026-01-01"},
    ]
    lookup = rds_eol.build_next_version_lookup(data, today="2026-08-17")
    assert lookup == {}


def test_rds_version_fields_blank_without_exact_calendar_match() -> None:
    eol_lookup = rds_eol.build_eol_lookup(RDS_EOL_SAMPLE)
    next_lookup = rds_eol.build_next_version_lookup(RDS_EOL_SAMPLE, today="2026-08-17")
    assert rds_eol.rds_version_fields("postgres", "15.13", eol_lookup, next_lookup) == (
        "2026-09-30",
        "",
    )
    assert rds_eol.rds_version_fields("postgres", "15.12", eol_lookup, next_lookup) == (
        "2026-03-31",
        "15.13",
    )
    assert rds_eol.rds_version_fields("postgres", "17", eol_lookup, next_lookup) == (
        "",
        "",
    )
    assert rds_eol.rds_version_fields("postgres", None, eol_lookup, next_lookup) == (
        "",
        "",
    )
    assert rds_eol.rds_version_fields(
        "not-an-engine", "15.13", eol_lookup, next_lookup
    ) == ("", "")


def test_load_rds_eol_data_success(mocker: MockerFixture) -> None:
    response = Mock()
    response.text = "- engine: postgres\n  version: '15.13'\n  eol: '2026-09-30'\n"
    response.raise_for_status.return_value = None
    mocker.patch("tools.cli_commands.rds_eol.requests.get", return_value=response)

    data = rds_eol.load_rds_eol_data()
    assert data == [{"engine": "postgres", "version": "15.13", "eol": "2026-09-30"}]


def test_load_rds_eol_data_http_failure(mocker: MockerFixture) -> None:
    mocker.patch(
        "tools.cli_commands.rds_eol.requests.get",
        side_effect=requests.RequestException("boom"),
    )
    assert rds_eol.load_rds_eol_data() == []


def test_load_rds_eol_data_rejects_non_list(mocker: MockerFixture) -> None:
    response = Mock()
    response.text = "engine: postgres\n"
    response.raise_for_status.return_value = None
    mocker.patch("tools.cli_commands.rds_eol.requests.get", return_value=response)
    assert rds_eol.load_rds_eol_data() == []
