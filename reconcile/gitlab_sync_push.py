import base64
import os
import sys
import shutil
import logging

from typing import Any, Dict, List
from git import Repo
from gnupg import GPG # type: ignore

from reconcile import queries
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.vault import VaultClient


QONTRACT_INTEGRATION = "gitlab-sync-push"


# Inspired by https://github.com/app-sre/git-keeper
class GitArchive:
    gpgs: Dict[str, Dict[str, Any]] = {}

    def __init__(
        self, origin, destination, commit, key, vault_gpg_path, workdir="clone-workdir"
    ):
        self.origin = origin
        self.destination = destination
        self.commit = commit
        self.to_delete_key = key
        self.vault_gpg_path = vault_gpg_path
        self.workdir = workdir

    @staticmethod
    def b64_encode(original) -> str:
        to_b64_bytes = original.encode("ascii")
        b64_bytes = base64.b64encode(to_b64_bytes)
        b64_str = b64_bytes.decode("ascii")
        return b64_str

    @staticmethod
    def init_gpgs(vault_client, sync_enabled):
        for sync in sync_enabled:
            if sync["public_key"]["path"] not in GitArchive.gpgs:
                key_data = vault_client.read(
                    {
                        "path": sync["public_key"]["path"],
                        "field": sync["public_key"]["field"],
                    }
                )
                gpg = GPG()
                gpg.import_keys(key_data)
                recipients = [k["fingerprint"] for k in gpg.list_keys()]
                GitArchive.gpgs[sync["public_key"]["path"]] = {
                    "gpg": gpg,
                    "recipients": recipients,
                }

    def clean_working_dir(self):
        shutil.rmtree(self.workdir, ignore_errors=True)
        os.makedirs(self.workdir, exist_ok=True)

    def upload_encrypted_clone(self, s3_session, bucket_name):
        """
        Clones git repo, archives and encrypts it, uploads to s3 and deletes old version
        Uploaded object names are base64_encoded(destination_url/commit_sha).tar.gpg
        """
        self.clean_working_dir()
        # get local copy of repo
        clone_url = self.origin + ".git"
        repo_dir = os.path.join(self.workdir, os.path.basename(clone_url))
        repo = Repo.clone_from(clone_url, repo_dir)
        # archive and encrypt repo
        repo_tar = repo_dir + ".tar"
        with open(repo_tar, "wb") as f:
            repo.archive(f)
        repo_gpg = repo_tar + ".gpg"
        with open(repo_tar, "rb") as f:
            GitArchive.gpgs[self.vault_gpg_path]["gpg"].encrypt_file(
                f,
                recipients=GitArchive.gpgs[self.vault_gpg_path]["recipients"],
                output=repo_gpg,
                armor=True,
                always_trust=True,
            )
        # upload to s3
        to_b64_name = self.destination + "/" + self.commit
        b64_name = GitArchive.b64_encode(to_b64_name)
        obj_key = b64_name + ".tar.gpg"
        s3 = s3_session.client("s3")
        s3.upload_file(repo_gpg, bucket_name, obj_key)
        # TODO check for success and delete old if successful uploading new
        # to_delete_key is empty for newly enabled gitsync
        if len(self.to_delete_key) > 0:
            b64_to_delete_key = GitArchive.b64_encode(self.to_delete_key)
            b64_to_delete_key = b64_to_delete_key + ".tar.gpg"
            s3.delete_object(Bucket=bucket_name, Key=b64_to_delete_key)
        self.clean_working_dir()


def get_latest_commits(repos, instance, settings) -> dict[str, str]:
    """Returns dict of repo name to latest commit sha for gitlab projects"""
    gitlab_commits = {}
    for repo in repos:
        gl = GitLabApi(instance, project_url=repo, settings=settings)
        project = gl.get_project(repo_url=repo)
        gitlab_commits[repo] = project.commits.list()[0].id
    return gitlab_commits


def get_acct_bucket_keys(aws, accts_to_syncs) -> dict[str, dict[str, list[str]]]:
    """
    Returns dict of accout names to bucket names to decoded object keys
    """
    acct_bucket_keys: Dict[str, Dict[str, List[str]]] = {}
    for a, syncs in accts_to_syncs.items():
        s = aws.sessions[a]
        s3 = s.client("s3")
        acct_bucket_keys[a] = {}
        for sync in syncs:
            try:
                result = s3.list_objects_v2(Bucket=sync["bucket_name"])
            except Exception as err:
                logging.error(err)
                result = None
            # TODO: handle IsTruncated == True (more than 1k items returned)
            if result is not None and "Contents" in result:
                keys = []
                for obj in result["Contents"]:
                    # remove file extension
                    b64_key = obj["Key"].split(".", 1)[0]
                    b64_bytes = b64_key.encode("ascii")
                    decoded_bytes = base64.b64decode(b64_bytes)
                    decoded_key = decoded_bytes.decode("ascii")
                    keys.append(decoded_key)
                acct_bucket_keys[a][sync["bucket_name"]] = keys
    return acct_bucket_keys


def get_objects_to_update(
    acct_bucket_keys, acct_syncs, gitlab_commits
) -> dict[str, dict[str, list[GitArchive]]]:
    """
    Returns dict of acct name to dict of buckets within
    account with corresponding list of ToUpdate objects
    """
    to_update = {}
    for acct, buckets in acct_bucket_keys.items():
        out_of_date_buckets: Dict[str, List[GitArchive]] = {}
        for sync in acct_syncs[acct]:
            i = 0
            to_delete_key = ""
            for key in buckets[sync["bucket_name"]]:
                # separate destination project and commit
                dest_and_commit = key.rsplit("/", 1)
                destination = dest_and_commit[0]
                commit = dest_and_commit[1]
                # remove file extension
                commit = commit.split(".", 1)[0]
                if destination == sync["destination_url"]:
                    if gitlab_commits[sync["origin_url"]] != commit:
                        to_delete_key = key
                    break
                i += 1
            # if out of date object was found OR
            # if all objects were checked and none had name of repo (a new repo added to sync)
            if len(to_delete_key) > 0 or i == len(buckets[sync["bucket_name"]]):
                out_of_date_buckets.setdefault(sync["bucket_name"], []).append(
                    GitArchive(
                        sync["origin_url"],
                        sync["destination_url"],
                        gitlab_commits[sync["origin_url"]],
                        to_delete_key,
                        sync["public_key"]["path"],
                    )
                )
        to_update[acct] = out_of_date_buckets
    return to_update


def run(dry_run, thread_pool_size=10):
    # https://github.com/app-sre/git-keeper#future-enhancements
    os.environ["GIT_SSL_NO_VERIFY"] = "true"

    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    sync_enabled = queries.get_gitlab_sync_repos(server=instance["url"])
    all_accounts = queries.get_aws_accounts()

    account_to_syncs: Dict[str, List[Dict[str, Any]]] = {}
    for sync in sync_enabled:
        account_to_syncs.setdefault(sync["bucket_account"]["name"], []).append(sync)
    accounts = [a for a in all_accounts if a["name"] in account_to_syncs]
    aws = AWSApi(thread_pool_size, accounts, settings=settings)
    acct_bucket_keys = get_acct_bucket_keys(aws, account_to_syncs)
    repos = [s["origin_url"] for s in sync_enabled]

    gitlab_commits = get_latest_commits(repos, instance, settings)
    GitArchive.init_gpgs(VaultClient(), sync_enabled)

    to_update = get_objects_to_update(
        acct_bucket_keys, account_to_syncs, gitlab_commits
    )

    err_count = 0
    for acct, buckets in to_update.items():
        for name, objects in buckets.items():
            for obj in objects:
                if dry_run:
                    logging.info(
                        f"[DRY RUN] Encrypted archive for {obj.destination} within {name} bucket will be updated"
                    )
                else:
                    try:
                        obj.upload_encrypted_clone(aws.sessions[acct], name)
                    except Exception as err:
                        logging.error(err)
                        err_count += 1
                        continue
                    logging.info(
                        f"Encrypted archive for {obj.destination} within {name} bucket successfully updated"
                    )

    if err_count > 0:
        sys.exit(1)
