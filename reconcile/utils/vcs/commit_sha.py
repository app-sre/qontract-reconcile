import re

from github import Github

from reconcile.utils.gitlab_api import GitLabApi


def is_commit_sha(ref: str) -> bool:
    """Check if the given ref is a commit sha."""
    return bool(re.search(r"^[0-9a-f]{40}$", ref))


def get_commit_sha_from_gitlab(
    repo_url: str, ref: str, gitlab_client: GitLabApi
) -> str:
    if is_commit_sha(ref):
        # This is already a commit sha - no need to query VCS
        return ref
    project = gitlab_client.get_project(repo_url)
    commits = project.commits.list(ref_name=ref)
    return commits[0].id


def get_commit_sha_from_github(repo_url: str, ref: str, github_client: Github) -> str:
    if is_commit_sha(ref):
        # This is already a commit sha - no need to query VCS
        return ref
    repo_name = repo_url.rstrip("/").replace("https://github.com/", "")
    gh = github_client.get_repo(repo_name)
    commit = gh.get_commit(sha=ref)
    return commit.sha
