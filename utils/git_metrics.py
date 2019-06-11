import copy
import itertools
import logging
import os
import subprocess
import tempfile

from multiprocessing.dummy import Pool as ThreadPool

import yaml

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

POOL_SIZE = 10


def short_repo(repo):
    gitlab_prefix = 'https://gitlab.cee.redhat.com/'
    github_prefix = 'https://github.com/'

    if repo.startswith(gitlab_prefix):
        provider = 'gitlab'
        short_repo = repo[len(gitlab_prefix):]
    elif repo.startswith(github_prefix):
        short_repo = repo[len(github_prefix):]
        provider = 'github'
    else:
        raise Exception("Unknown provider for {}".format(repo))

    short_repo = short_repo.rstrip("/").rstrip(".git")
    short_repo_split = short_repo.split("/")

    if len(short_repo_split) != 2:
        raise Exception("Expecting only two components {}".format(repo))

    return "{}-{}".format(provider, "-".join(short_repo_split))


class GitCommandError(Exception):
    pass


class GitMetrics(object):
    def __init__(self, repo, **kwargs):
        self.repo = repo
        self.bare = kwargs.get('bare', False)
        self.cache = kwargs.get('cache', False)

        if self.cache:
            self.work_dir = os.path.join(self.cache, short_repo(repo))
        else:
            self.work_dir = tempfile.mkdtemp(prefix='tmp-git-metrics-',
                                             dir='.')

        if self.bare:
            self.git_dir = self.work_dir
        else:
            self.git_dir = self.work_dir + "/.git"

        self.clone_or_pull()

    def clone_or_pull(self):
        if not os.path.isdir(self.git_dir):
            logging.info(['cloning', self.repo, self.work_dir])
            self.clone()
        else:
            logging.info(['pulling', self.repo, self.work_dir])
            self.pull()

    def clone(self):
        if self.bare:
            subprocess.call(['git', 'clone', '--bare', '--quiet', self.repo,
                             self.work_dir])
        else:
            subprocess.call(['git', 'clone', '--quiet', self.repo,
                             self.work_dir])

    def pull(self):
        if self.bare:
            self._git_command(["fetch", "-q"])
            self._git_command(["update-ref", "HEAD", "FETCH_HEAD"])
        else:
            self._git_command(["pull"])

    def get_file(self, commit, path):
        return self._git_command(['show', '{}:{}'.format(commit, path)])

    def ls_files_dir(self, commit, path):
        ls_tree_cmd = ['ls-tree', '--name-only', commit, path.rstrip('/')+'/']
        return self._git_command(ls_tree_cmd).splitlines()

    def count(self, commit="HEAD"):
        fist_command_cmd = ["rev-list", "--max-parents=0", "HEAD"]
        first_commit = self._git_command(fist_command_cmd)

        count_cmd = ['rev-list',
                     '{}..{}'.format(first_commit, commit),
                     '--count']

        return self._git_command(count_cmd)

    def commit_date(self, commit):
        commit_date_cmd = ['show', '-s', '--format=%ci', commit]
        return self._git_command(commit_date_cmd)

    def rev_parse(self, commit):
        return self._git_command(['rev-parse', commit])

    def is_sha(self, h):
        return len(str(h)) == 40

    def _git_command(self, cmd):
        git_cmd = ['git', '--git-dir', self.git_dir] + cmd

        p = subprocess.Popen(git_cmd,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE)

        out, _ = p.communicate()

        if p.returncode != 0:
            msg = "error running {} in {}".format(git_cmd, self.repo)
            raise GitCommandError(msg)

        return out.strip()


class SaasGitMetrics(GitMetrics):
    def __init__(self, *args, **kwds):
        super(SaasGitMetrics, self).__init__(*args, **kwds)
        self.cache = kwds.get('cache', False)
        self.upstream_repo_metrics = {}

        config = yaml.safe_load(self.get_file('HEAD', 'config.yaml'))
        self.contexts = config['contexts']

    def get_yaml(self, commit, path):
        data = self._git_command(['show', '{}:{}'.format(commit, path)])
        return yaml.safe_load(data)

    def fetch_repo_metrics(self, repo):
        repo_metrics = GitMetrics(repo, bare=True, cache=self.cache)
        return (repo, repo_metrics)

    def services(self, commit='HEAD'):
        """
        Returns a dict of tuples {(context, service_name): service}
        """

        return {
            (c['name'], service['name']): service
            for c in self.contexts
            for sf in self.ls_files_dir(commit, c['data']['services_dir'])
            for service in self.get_yaml(commit, sf)['services']
        }

    def services_with_info(self, commit='HEAD'):
        services = self.services(commit)

        # fetch all repos
        upstream_urls = list(set([service['url']
                                  for service in services.values()]))

        pool = ThreadPool(POOL_SIZE)
        repo_metrics_tuples = pool.map(self.fetch_repo_metrics,
                                       upstream_urls)

        repo_metrics = {k: v for (k, v) in repo_metrics_tuples}

        for (context_name, _), service in services.items():
            url = service['url']
            h = service['hash']

            upstream_commits = repo_metrics[url].count()
            upstream_saas_commit_index = repo_metrics[url].count(h)

            service['context'] = context_name
            service['commit'] = self.rev_parse('HEAD')
            service['commit_timestamp'] = self.commit_date('HEAD')
            service['upstream_commits'] = upstream_commits
            service['upstream_saas_commit_index'] = upstream_saas_commit_index

        return services

    def services_hash_history(self):
        services_head = self.services_with_info()
        services_history = copy.deepcopy(services_head)

        services_found = []
        for index in itertools.count(1):
            if len(services_found) == len(services_head):
                break

            commit = "HEAD~{}".format(index)

            commit_hash = self.rev_parse(commit)
            commit_ts = self.commit_date(commit)

            services_commit = self.services(commit)

            for service_tuple, service in services_head.items():
                if service_tuple in services_found:
                    continue

                context_name, service_name = service_tuple

                try:
                    commit_hash = services_commit[service_tuple]['hash']
                except KeyError:
                    commit_hash = None

                if not commit_hash or service['hash'] != commit_hash or \
                        not self.is_sha(service['hash']):
                    services_found.append(service_tuple)
                else:
                    services_history[service_tuple]['commit'] = commit_hash
                    services_history[service_tuple]['commit_timestamp'] = \
                        commit_ts

        return services_history.values()


if __name__ == "__main__":
    repo = "https://github.com/openshiftio/saas-launchpad"
    repo = "https://github.com/openshiftio/saas-openshiftio"

    repo_metrics = SaasGitMetrics(repo, cache=".cache")

    import json
    print(json.dumps(repo_metrics.services_hash_history()))
