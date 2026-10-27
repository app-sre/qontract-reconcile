"""Data models for the github-username-sync integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GithubUsernameUpdate:
    """A single internal user whose github_username should be corrected from LDAP."""

    org_username: str
    path: str
    current_github_username: str
    github_username: str
