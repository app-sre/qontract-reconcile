from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MirrorSpec:
    """A single mirror relationship between a source and destination
    registry. By the time this object reaches the engine, all credentials
    are resolved to plain "user:password" strings suitable for skopeo."""

    source_url: str
    source_creds: str | None
    destination_url: str
    destination_creds: str
    # Regex patterns controlling which tags are mirrored. Operators use
    # these to limit mirroring to specific tag conventions (e.g.,
    # "^v[0-9]+" for semver releases) or to exclude unwanted tags
    # (e.g., "^sha256-.+sig$" for cosign signatures that should not
    # be mirrored). When both are set, exclusions take precedence.
    # None means no filtering for that direction.
    tag_include: list[str] | None = None
    tag_exclude: list[str] | None = None
