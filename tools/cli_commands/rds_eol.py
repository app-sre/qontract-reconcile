from __future__ import annotations

import logging
from collections import defaultdict
from operator import itemgetter
from typing import TYPE_CHECKING

import requests
import yaml
from pydantic import BaseModel

from reconcile.utils.datetime_util import utc_now
from reconcile.utils.semver_helper import parse_semver

if TYPE_CHECKING:
    from semver import VersionInfo

DEFAULT_RDS_EOL_URL = (
    "https://raw.githubusercontent.com/app-sre/aws-generated-data"
    "/main/output/rds_eol.yaml"
)


class RdsEolEntry(BaseModel):
    """A single entry from the AWS RDS end-of-life calendar dataset."""

    engine: str
    version: str
    eol: str


def load_rds_eol_data(url: str = DEFAULT_RDS_EOL_URL) -> list[RdsEolEntry]:
    """Fetch the AWS RDS calendar dataset. Returns an empty list on failure."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = yaml.safe_load(resp.text) or []
    except (requests.RequestException, yaml.YAMLError) as exc:
        logging.warning("Could not fetch RDS EOL data from %s: %s", url, exc)
        return []
    if not isinstance(data, list):
        logging.warning("RDS EOL data from %s is not a list", url)
        return []
    entries: list[RdsEolEntry] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        try:
            entries.append(
                RdsEolEntry(
                    engine=str(raw["engine"]),
                    version=str(raw["version"]),
                    eol=str(raw["eol"]),
                )
            )
        except KeyError, TypeError:
            continue
    return entries


def _parse_rds_version(version: str) -> VersionInfo | None:
    try:
        return parse_semver(version, optional_minor_and_patch=True)
    except ValueError:
        return None


def build_eol_lookup(
    eol_data: list[RdsEolEntry],
) -> dict[tuple[str, str], str]:
    """Map exact (engine, version) strings from the AWS calendar to EOL dates."""
    return {(entry.engine, entry.version): entry.eol for entry in eol_data}


def build_next_version_lookup(
    eol_data: list[RdsEolEntry],
    today: str | None = None,
) -> dict[tuple[str, str], str]:
    """Map (engine, version) to the next non-EOL version in the same major line.

    Only exact versions present in the AWS calendar dataset are keys. There is
    no fuzzy match for major-only versions (e.g. "17"). Missing keys mean blank
    output. "Next" never crosses a major version.
    """
    if today is None:
        today = utc_now().strftime("%Y-%m-%d")

    eol_lookup = build_eol_lookup(eol_data)
    by_engine_major: dict[tuple[str, int], list[tuple[VersionInfo, str]]] = defaultdict(
        list
    )
    for entry in eol_data:
        parsed = _parse_rds_version(entry.version)
        if parsed is None:
            continue
        by_engine_major[entry.engine, parsed.major].append((parsed, entry.version))

    for versions in by_engine_major.values():
        versions.sort(key=itemgetter(0))

    result: dict[tuple[str, str], str] = {}
    for entry in eol_data:
        current = _parse_rds_version(entry.version)
        if current is None:
            continue
        for candidate, candidate_str in by_engine_major[entry.engine, current.major]:
            if candidate <= current:
                continue
            candidate_eol = eol_lookup.get((entry.engine, candidate_str), "")
            if candidate_eol >= today:
                result[entry.engine, entry.version] = candidate_str
                break
    return result


def rds_version_fields(
    engine: str | None,
    engine_version: str | None,
    eol_lookup: dict[tuple[str, str], str],
    next_version_lookup: dict[tuple[str, str], str],
) -> tuple[str, str]:
    """Return (eol_date, next_version) only for an exact calendar match."""
    if engine is None or engine_version is None:
        return "", ""
    key = (engine, engine_version)
    if key not in eol_lookup:
        return "", ""
    return eol_lookup[key], next_version_lookup.get(key, "")
