import logging
import pathlib

from ruamel import yaml


_LOG = logging.getLogger(__name__)


class RepoOwners:
    """
    Abstracts the owners of a repository with per-path granularity.
    """
    def __init__(self, git_cli, ref='master'):
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
        Returns a sorted list of unique owners.
        """
        repo_owners = set()
        for owners in self.owners_map.values():
            repo_owners.update(owners)
        return sorted(repo_owners)

    def get_path_owners(self, path):
        """
        Gets all the owners of a given path, no matter in which
        level of the filesystem tree the owner was specified.
        Returns a sorted list of unique owners.
        """
        path_owners = set()
        for owned_path, owners in self.owners_map.items():
            if path.startswith(owned_path):
                path_owners.update(owners)
        if not path_owners:
            raise KeyError(f'No owners for path {path!r}')
        return sorted(path_owners)

    def get_path_close_owners(self, path):
        """
        Gets all closest owners of a given path, no matter in which
        level of the filesystem tree the owner was specified.
        Returns a sorted list of unique owners.
        """
        candidates = []

        for owned_path in self.owners_map:
            if path.startswith(owned_path):
                candidates.append(owned_path)

        if not candidates:
            raise KeyError(f'No owners for path {path!r}')

        # The longest owned_path is the chosen
        elected = max(candidates, key=lambda x: len(x))
        return sorted(set(self._owners_map[elected]))

    def _get_owners_map(self):
        """
        Maps all the OWNERS files content to their respective
        owned directory.
        """
        owners_map = dict()
        aliases = self._get_aliases()

        repo_tree = self._git_cli.get_repository_tree(ref='master')
        for item in repo_tree:
            if item['name'] != 'OWNERS':
                continue

            # Loading the list of approvers
            raw_owners = self._git_cli.get_file(path=item['path'],
                                                ref=self._ref)
            approvers = yaml.safe_load(raw_owners.decode())['approvers']

            # Approver might be an alias. Let's resolve them.
            resolved_approvers = []
            for approver in approvers:
                if approver in aliases:
                    resolved_approvers.extend(aliases[approver])
                else:
                    resolved_approvers.append(approver)

            # The OWNERS file basedir is the owners_map key
            owners_path = str(pathlib.Path(item['path']).parent)
            owners_map[owners_path] = resolved_approvers
        return owners_map

    def _get_aliases(self):
        """
        Retrieves the approvers aliases from the OWNERS_ALIASES file.
        """
        aliases = dict()
        raw_aliases = self._git_cli.get_file(path='OWNERS_ALIASES',
                                             ref=self._ref)
        if raw_aliases is not None:
            aliases = yaml.safe_load(raw_aliases.decode())['aliases']
        return aliases
