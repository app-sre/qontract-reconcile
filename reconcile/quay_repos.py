import logging
import sys

from collections import namedtuple

from reconcile.utils import gql

from reconcile.quay_base import get_quay_api_store, OrgKey
from reconcile.status import ExitCodes


QUAY_REPOS_QUERY = """
{
  apps: apps_v1 {
    name
    quayRepos {
      org {
        name
        managedRepos
        instance {
          name
        }
      }
      items {
        name
        description
        public
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = "quay-repos"


RepoInfo = namedtuple("RepoInfo", ["org_key", "name", "public", "description"])


def fetch_current_state(quay_api_store):
    state = []

    for org_key, org_info in quay_api_store.items():
        if not org_info["managedRepos"] and not org_info["mirror"]:
            continue

        quay_api = org_info["api"]

        for repo in quay_api.list_images():
            name = repo["name"]
            public = repo["is_public"]
            description = repo["description"]

            if description is None:
                description = ""

            repo_info = RepoInfo(org_key, name, public, description)
            state.append(repo_info)

    return state


def fetch_desired_state(quay_api_store):
    gqlapi = gql.get_api()
    result = gqlapi.query(QUAY_REPOS_QUERY)

    state = []

    seen_repos = set()

    # fetch from quayRepos
    for app in result["apps"]:
        quay_repos = app.get("quayRepos")

        if quay_repos is None:
            continue

        for quay_repo in quay_repos:
            org_name = quay_repo["org"]["name"]
            if not quay_repo["org"]["managedRepos"]:
                logging.error(
                    f"[{app['name']}] Can not manage repos in {org_name} "
                    "since managedRepos is set to false."
                )
                sys.exit(ExitCodes.ERROR)

            instance_name = quay_repo["org"]["instance"]["name"]
            org_key = OrgKey(instance_name, org_name)

            for repo_item in quay_repo["items"]:
                name = repo_item["name"]
                public = repo_item["public"]
                description = repo_item["description"].strip()

                repo = RepoInfo(org_key, name, public, description)

                if (org_key, name) in seen_repos:
                    logging.error(
                        f"Repo {org_key.instance}/"
                        f"{org_key.org_name}/{name} is duplicated"
                    )
                    sys.exit(ExitCodes.ERROR)

                seen_repos.add((org_key, name))
                state.append(repo)

                # downstream orgs
                downstream_orgs = get_downstream_orgs(quay_api_store, org_key)
                for downstream_org_key in downstream_orgs:
                    downstream_repo = RepoInfo(
                        downstream_org_key, name, public, description
                    )
                    state.append(downstream_repo)

    return state


def get_downstream_orgs(quay_api_store, upstream_org_key):
    downstream_orgs = []
    for org_key, org_info in quay_api_store.items():
        if org_info.get("mirror") == upstream_org_key:
            downstream_orgs.append(org_key)

    return downstream_orgs


def get_repo_from_state(state, repo_info):
    for item in state:
        if item.org_key == repo_info.org_key and item.name == repo_info.name:
            return item
    return None


def act_delete(dry_run, quay_api_store, current_repo):
    logging.info(
        [
            "delete_repo",
            current_repo.org_key.instance,
            current_repo.org_key.org_name,
            current_repo.name,
        ]
    )
    if not dry_run:
        api = quay_api_store[current_repo.org_key]["api"]
        api.repo_delete(current_repo.name)


def act_create(dry_run, quay_api_store, desired_repo):
    logging.info(
        [
            "create_repo",
            desired_repo.org_key.instance,
            desired_repo.org_key.org_name,
            desired_repo.name,
        ]
    )
    if not dry_run:
        api = quay_api_store[desired_repo.org_key]["api"]
        api.repo_create(
            desired_repo.name, desired_repo.description, desired_repo.public
        )


def act_description(dry_run, quay_api_store, desired_repo):
    logging.info(
        [
            "update_desc",
            desired_repo.org_key.instance,
            desired_repo.org_key.org_name,
            desired_repo.description,
        ]
    )
    if not dry_run:
        api = quay_api_store[desired_repo.org_key]["api"]
        api.repo_update_description(desired_repo.name, desired_repo.description)


def act_public(dry_run, quay_api_store, desired_repo):
    logging.info(
        [
            "update_public",
            desired_repo.org_key.instance,
            desired_repo.org_key.org_name,
            desired_repo.name,
        ]
    )
    if not dry_run:
        api = quay_api_store[desired_repo.org_key]["api"]
        if desired_repo.public:
            api.repo_make_public(desired_repo.name)
        else:
            api.repo_make_private(desired_repo.name)


def act(dry_run, quay_api_store, current_state, desired_state):
    for current_repo in current_state:
        desired_repo = get_repo_from_state(desired_state, current_repo)
        if not desired_repo:
            act_delete(dry_run, quay_api_store, current_repo)

    for desired_repo in desired_state:
        current_repo = get_repo_from_state(current_state, desired_repo)
        if not current_repo:
            act_create(dry_run, quay_api_store, desired_repo)
        else:
            if current_repo.public != desired_repo.public:
                act_public(dry_run, quay_api_store, desired_repo)
            if current_repo.description != desired_repo.description:
                act_description(dry_run, quay_api_store, desired_repo)


def run(dry_run):
    quay_api_store = get_quay_api_store()

    # consistency checks
    for org_key, org_info in quay_api_store.items():
        if org_info.get("mirror"):
            # ensure there are no circular mirror dependencies
            mirror_org_key = org_info["mirror"]
            mirror_org = quay_api_store[mirror_org_key]
            if mirror_org.get("mirror"):
                logging.error(
                    f"{mirror_org_key.instance}/"
                    + f"{mirror_org_key.org_name} "
                    + "can't have mirrors and be a mirror"
                )
                sys.exit(ExitCodes.ERROR)

            # ensure no org defines `managedRepos` and `mirror` at the same
            if org_info.get("managedRepos"):
                logging.error(
                    f"{org_key.instance}/{org_key.org_name} "
                    + "has defined mirror and managedRepos"
                )
                sys.exit(ExitCodes.ERROR)

    # run integration
    current_state = fetch_current_state(quay_api_store)
    desired_state = fetch_desired_state(quay_api_store)
    act(dry_run, quay_api_store, current_state, desired_state)
