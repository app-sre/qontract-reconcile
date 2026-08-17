from __future__ import annotations

import logging
from collections import defaultdict
from operator import itemgetter
from typing import TYPE_CHECKING, Any

import requests
import yaml

from reconcile.utils.datetime_util import utc_now
from reconcile.utils.semver_helper import parse_semver

if TYPE_CHECKING:
    from semver import VersionInfo

RDS_EOL_URL = (
    "https://raw.githubusercontent.com/app-sre/aws-generated-data"
    "/main/output/rds_eol.yaml"
)


def load_rds_eol_data() -> list[dict[str, Any]]:
    """Fetch the AWS RDS calendar dataset. Returns an empty list on failure."""
    try:
        resp = requests.get(RDS_EOL_URL, timeout=10)
        resp.raise_for_status()
        data = yaml.safe_load(resp.text) or []
    except (requests.RequestException, yaml.YAMLError) as exc:
        logging.warning("Could not fetch RDS EOL data from %s: %s", RDS_EOL_URL, exc)
        return []
    if not isinstance(data, list):
        logging.warning("RDS EOL data from %s is not a list", RDS_EOL_URL)
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def _parse_rds_version(version: str) -> VersionInfo | None:
    try:
        return parse_semver(version, optional_minor_and_patch=True)
    except ValueError:
        return None


def build_eol_lookup(
    eol_data: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Map exact (engine, version) strings from the AWS calendar to EOL dates."""
    lookup: dict[tuple[str, str], str] = {}
    for entry in eol_data:
        engine = entry.get("engine")
        version = entry.get("version")
        eol = entry.get("eol")
        if engine is None or version is None or eol is None:
            continue
        lookup[str(engine), str(version)] = str(eol)
    return lookup


def build_next_version_lookup(
    eol_data: list[dict[str, Any]],
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
        engine = entry.get("engine")
        version = entry.get("version")
        if engine is None or version is None:
            continue
        version_str = str(version)
        parsed = _parse_rds_version(version_str)
        if parsed is None:
            continue
        by_engine_major[str(engine), parsed.major].append((parsed, version_str))

    for versions in by_engine_major.values():
        versions.sort(key=itemgetter(0))

    result: dict[tuple[str, str], str] = {}
    for entry in eol_data:
        engine = entry.get("engine")
        version = entry.get("version")
        if engine is None or version is None:
            continue
        engine_str = str(engine)
        version_str = str(version)
        current = _parse_rds_version(version_str)
        if current is None:
            continue
        for candidate, candidate_str in by_engine_major[engine_str, current.major]:
            if candidate <= current:
                continue
            candidate_eol = eol_lookup.get((engine_str, candidate_str), "")
            if candidate_eol >= today:
                result[engine_str, version_str] = candidate_str
                break
    return result


def rds_version_fields(
    engine: object | None,
    engine_version: object | None,
    eol_lookup: dict[tuple[str, str], str],
    next_version_lookup: dict[tuple[str, str], str],
) -> tuple[str, str]:
    """Return (eol_date, next_version) only for an exact calendar match."""
    if engine is None or engine_version is None:
        return "", ""
    key = (str(engine), str(engine_version))
    if key not in eol_lookup:
        return "", ""
    return eol_lookup[key], next_version_lookup.get(key, "")
