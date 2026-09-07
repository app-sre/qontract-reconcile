"""GitHub organization API client."""

from qontract_utils.github_org.api import GithubOrgApi, GithubRateLimitExceededError

__all__ = ["GithubOrgApi", "GithubRateLimitExceededError"]
