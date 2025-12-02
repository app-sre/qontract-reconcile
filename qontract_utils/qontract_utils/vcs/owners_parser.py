"""OWNERS file parser for repository ownership data.

Parses OWNERS and OWNERS_ALIASES files following Kubernetes-style format.
Ported from reconcile/utils/repo_owners.py but modernized to ADR standards.

Following ADR-012: Fully Typed Pydantic Models Over Nested Dicts
"""

import logging
from collections.abc import Callable

from qontract_utils.ruamel import create_ruamel_instance, yaml
from qontract_utils.vcs.models import OwnersFileData, RepoOwners
from qontract_utils.vcs.provider_protocol import VCSApiProtocol

logger = logging.getLogger(__name__)


class OwnersParser:
    """Parser for OWNERS files in Git repositories.

    Supports:
    - OWNERS files with approvers and reviewers lists
    - OWNERS_ALIASES files for alias resolution

    Args:
        vcs_client: VCS API client (GitHubRepoApi or GitLabRepoApi)
        ref: Git reference (branch, tag, commit SHA)
    """

    def __init__(
        self,
        vcs_client: VCSApiProtocol,
        ref: str = "master",
        yaml_client: Callable[..., yaml.YAML] | None = None,
    ) -> None:
        self._vcs_client = vcs_client
        self._ref = ref
        self._repo_url = vcs_client.repo_url
        self._aliases: dict[str, list[str]] | None = None
        self._yaml = yaml_client() if yaml_client else create_ruamel_instance()

    def get_owners(self, path: str = "/") -> RepoOwners:
        """Get owners defined in OWNERS file at specified path.

        Args:
            path: Path to directory containing OWNERS file (default: root "/")

        Returns:
            RepoOwners with approvers and reviewers from OWNERS file at path

        Note:
            All exception handling is done here. Private methods will raise
            exceptions that are caught and logged with repo_url context.
        """
        # Normalize path to ensure
        # * it ends with a single slash if not root
        # * it does not start with a slash
        # * it does not contain dots
        path = (path.removesuffix("/") + "/").strip(".").lstrip("/")
        owners_file_path = f"{path}OWNERS"

        try:
            raw_owners = self._vcs_client.get_file(path=owners_file_path, ref=self._ref)
            if not raw_owners:
                return RepoOwners(approvers=[], reviewers=[])
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"Non-parsable OWNERS file: {self._repo_url}/{owners_file_path} - {e}"
            )
            return RepoOwners(approvers=[], reviewers=[])

        try:
            owners_data = self._parse_owners_file(raw_owners)

            approvers = self._resolve_aliases(owners_data.approvers)
            reviewers = self._resolve_aliases(owners_data.reviewers)

            return RepoOwners(
                approvers=sorted(approvers),
                reviewers=sorted(reviewers),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"Non-parsable OWNERS_ALIAS file: {self._repo_url}/OWNERS_ALIASES - {e}"
            )
            return RepoOwners(approvers=[], reviewers=[])

    def _parse_owners_file(self, content: str) -> OwnersFileData:
        """Parse OWNERS file YAML content.

        Args:
            content: OWNERS file content as string

        Returns:
            OwnersFileData with approvers/reviewers lists

        Raises:
            yaml.parser.ParserError: If YAML is invalid
            ValueError: If YAML is not a dict or empty
        """
        owners = self._yaml.load(content)

        if owners is None:
            raise ValueError("Empty OWNERS file")

        if not isinstance(owners, dict):
            raise TypeError("OWNERS file content is not a dictionary")

        return OwnersFileData(
            approvers=owners.get("approvers") or [],
            reviewers=owners.get("reviewers") or [],
        )

    def _resolve_aliases(self, usernames: list[str]) -> set[str]:
        """Resolve aliases from OWNERS_ALIASES file.

        Args:
            usernames: List of usernames (may include aliases)

        Returns:
            Set of resolved usernames (aliases expanded to actual users)
        """
        if self._aliases is None:
            self._aliases = self._get_aliases()

        resolved: set[str] = set()
        for username in usernames:
            if username in self._aliases:
                # Expand alias to list of users
                resolved.update(self._aliases[username])
            else:
                # Not an alias, add directly
                resolved.add(username)

        return resolved

    def _get_aliases(self) -> dict[str, list[str]]:
        """Parse OWNERS_ALIASES file.

        Returns:
            Dictionary mapping alias name to list of usernames
            Example: {"platform-team": ["user1", "user2"]}
        """
        raw_aliases = self._vcs_client.get_file(path="OWNERS_ALIASES", ref=self._ref)
        if not raw_aliases:
            return {}

        aliases_data = self._yaml.load(raw_aliases)

        if not aliases_data:
            return {}

        if not isinstance(aliases_data, dict):
            raise TypeError("OWNERS_ALIASES file content is not a dictionary")

        # OWNERS_ALIASES format: {"aliases": {"alias-name": ["user1", "user2"]}}
        return aliases_data.get("aliases", {})
