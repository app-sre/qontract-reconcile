import logging
import os
import pathlib

from ruamel import yaml

_LOG = logging.getLogger(__name__)


class RepoOwners:
    """
    Abstracts the owners of a repository with per-path granularity.
    """

    def __init__(self, git_cli, ref="master"):
        self._git_cli = git_cli
        self._ref = ref
        self._owners_map = None

    @property
    def owners_map(self):
        if self._owners_map is None:
            self._owners_map = self._get_owners_map()
        return self._owners_map

    def get_owners(self):
        """
        Gets all the owners of the repository.

        :return: the repository owners
        :rtype: dict
        """
        repo_owners = {"approvers": set(), "reviewers": set()}

        if "." in self.owners_map:
            repo_owners["approvers"].update(self.owners_map["."]["approvers"])
            repo_owners["reviewers"].update(self.owners_map["."]["reviewers"])

        for owners in self.owners_map.values():
            repo_owners["approvers"].update(owners["approvers"])
            repo_owners["reviewers"].update(owners["reviewers"])

        return repo_owners

    def get_root_owners(self):
        """
        Gets all the owners defined in the repository root.

        :return: the repository root owners
        :rtype: dict
        """

        if "." in self.owners_map:
            return self._set_to_sorted_list(self.owners_map["."])

        return {"approvers": [], "reviewers": []}

    def get_path_owners(self, path):
        """
        Gets all the owners of a given path, no matter in which
        level of the filesystem tree the owner was specified.

        :param path: the path to look up owners for
        :type path: str

        :return: the path owners
        :rtype: dict
        """
        path_owners = {"approvers": set(), "reviewers": set()}

        if "." in self.owners_map:
            path_owners["approvers"].update(self.owners_map["."]["approvers"])
            path_owners["reviewers"].update(self.owners_map["."]["reviewers"])

        for owned_path, owners in self.owners_map.items():
            if os.path.commonpath([path, owned_path]) == owned_path:
                path_owners["approvers"].update(owners["approvers"])
                path_owners["reviewers"].update(owners["reviewers"])

        return self._set_to_sorted_list(path_owners)

    def get_path_closest_owners(self, path):
        """
        Gets all closest owners of a given path, no matter in which
        level of the filesystem tree the owner was specified.
        Returns a sorted list of unique owners.

        :param path: the path to look up owners for
        :type path: str

        :return: the path closest owners
        :rtype: dict
        """
        candidates = []

        if "." in self.owners_map:
            candidates.append(".")

        for owned_path in self.owners_map:
            if os.path.commonpath([path, owned_path]) == owned_path:
                candidates.append(owned_path)

        if candidates:
            # The longest owned_path is the chosen
            elected = max(candidates, key=len)
            return self._set_to_sorted_list(self.owners_map[elected])

        return {"approvers": [], "reviewers": []}

    def _get_owners_map(self):
        """
        Maps all the OWNERS files content to their respective
        owned directory.

        :return: owners list per path basis
        :rtype: dict
        """
        owners_map = {}

        repo_tree = self._git_cli.get_repository_tree(ref=self._ref)

        aliases = None
        owner_files = []
        for item in repo_tree:
            if item["path"] == "OWNERS_ALIASES":
                aliases = self._get_aliases()
            elif item["name"] == "OWNERS":
                owner_files.append(item)

        for owner_file in owner_files:
            raw_owners = self._git_cli.get_file(path=owner_file["path"], ref=self._ref)
            try:
                owners = yaml.safe_load(raw_owners.decode())
            except yaml.parser.ParserError:
                owners = None
            if owners is None:
                _LOG.warning(
                    "Non-parsable OWNERS file "
                    f"{self._git_cli.project.web_url}:{owner_file.get('path')}"
                )
                continue
            if not isinstance(owners, dict):
                _LOG.warning(
                    f"owner file {self._git_cli.project.web_url}:{owner_file.get('path')} "
                    "content is not a dictionary"
                )
                continue

            approvers = owners.get("approvers") or set()

            # Approver might be an alias. Let's resolve them.
            resolved_approvers = set()
            for approver in approvers:
                if aliases is not None and approver in aliases:
                    resolved_approvers.update(aliases[approver])
                else:
                    resolved_approvers.add(approver)

            reviewers = owners.get("reviewers") or set()

            # Reviewer might be an alias. Let's resolve them.
            resolved_reviewers = set()
            for reviewer in reviewers:
                if aliases is not None and reviewer in aliases:
                    resolved_reviewers.update(aliases[reviewer])
                else:
                    resolved_reviewers.add(reviewer)

            # The OWNERS file basedir is the owners_map dictionary key
            owners_path = str(pathlib.Path(owner_file["path"]).parent)
            owners_map[owners_path] = {
                "approvers": resolved_approvers,
                "reviewers": resolved_reviewers,
            }
        return owners_map

    def _get_aliases(self):
        """
        Retrieves the approvers aliases from the OWNERS_ALIASES file.

        :return: owners list per alias basis
        :rtype: dict
        """
        raw_aliases = self._git_cli.get_file(path="OWNERS_ALIASES", ref=self._ref)
        if raw_aliases is None:
            return {}

        aliases = yaml.safe_load(raw_aliases.decode())
        if aliases is None:
            return {}

        return aliases["aliases"]

    @staticmethod
    def _set_to_sorted_list(owners):
        approvers = owners["approvers"]
        sorted_approvers = sorted(approvers) if approvers else []

        reviewers = owners["reviewers"]
        sorted_reviewers = sorted(reviewers) if reviewers else []

        return {"approvers": sorted_approvers, "reviewers": sorted_reviewers}
