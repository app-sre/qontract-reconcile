from __future__ import annotations

import logging
from collections import namedtuple
from typing import TYPE_CHECKING, Any

from reconcile import queries
from reconcile.container_registry_mirror import register
from reconcile.container_registry_mirror.deep_sync_timer import DeepSyncTimer
from reconcile.container_registry_mirror.engine import MirrorEngine
from reconcile.container_registry_mirror.mirror_spec import MirrorSpec
from reconcile.utils import gql
from reconcile.utils.instrumented_wrappers import InstrumentedSkopeo as Skopeo
from reconcile.utils.secret_reader import SecretReader

if TYPE_CHECKING:
    from collections.abc import Iterable

_LOG = logging.getLogger(__name__)

# Identifies a destination Quay organisation for credential lookup and sync
# task grouping. A composite key because the same org name can exist on
# different Quay instances (e.g., quay.io vs an internal Quay), and push
# credentials must not be shared across instances.
OrgKey = namedtuple("OrgKey", ["instance", "org_name"])

# A Quay org has one set of push credentials that grants write access to
# all repositories within it, while each repository has its own mirror
# definition (source URL, pull credentials, tag filters). These live at
# different levels of the app-interface hierarchy, so they require
# separate queries: this one fetches orgs and their push credential Vault
# paths; get_quay_repos() fetches repos and their mirror definitions.
QUAY_ORG_CATALOG_QUERY = """
{
  quay_orgs: quay_orgs_v1 {
    name
    pushCredentials {
      path
      field
      version
      format
    }
    instance {
      name
      url
    }
  }
}
"""


class QuayMirror:
    """Mirrors images from any source registry into Quay organisations.
    Satisfies the ContainerRegistryMirror protocol by implementing
    the four required methods."""

    def __init__(
        self,
        repository_urls: Iterable[str] | None = None,
        exclude_repository_urls: Iterable[str] | None = None,
    ) -> None:
        self.gqlapi = gql.get_api()
        settings = queries.get_app_interface_settings()
        self.secret_reader = SecretReader(settings=settings)
        self.repository_urls = repository_urls
        self.exclude_repository_urls = exclude_repository_urls
        # Credentials are fetched eagerly so that misconfiguration
        # (missing Vault secret, wrong path) fails immediately.
        self.push_creds = self._get_push_creds()

    def resolve_source_credentials(
        self,
        secret_ref: dict[str, Any] | None,
    ) -> str | None:
        """Read pull credentials from Vault and return in skopeo's
        "user:password" format. Returns None for public sources."""
        if secret_ref is None:
            return None
        raw_data = self.secret_reader.read_all(secret_ref)
        return f"{raw_data['user']}:{raw_data['token']}"

    def resolve_destination_credentials(self, key: Any) -> str:
        """Look up pre-fetched push credentials by OrgKey. Raises
        KeyError if the org has no push credentials configured,
        surfacing misconfiguration immediately."""
        return self.push_creds[key]

    def should_skip_mirror(
        self,
        source_registry: str,
        source_url: str,
        destination_url: str,
        destination_public: bool | None,
    ) -> bool:
        """Block docker.io sources from being mirrored to public Quay
        repos. Security control: Docker Hub images pulled via
        authenticated mirror credentials could be re-exposed to the
        public internet if written to a public repository."""
        return source_registry == "docker.io" and destination_public is True

    def discover_mirrors(self) -> list[MirrorSpec]:
        """Query quay_repos from app-interface and transform each
        mirror definition into a MirrorSpec with resolved credentials."""
        apps = queries.get_quay_repos()

        # Converted to sets for O(1) lookup because the filter is
        # checked once per repo item.
        repo_urls = None
        if self.repository_urls:
            repo_urls = set(self.repository_urls)

        exclude_urls = None
        if self.exclude_repository_urls:
            exclude_urls = set(self.exclude_repository_urls)

        specs = []

        for app in apps:
            quay_repos = app.get("quayRepos")
            if quay_repos is None:
                continue

            for quay_repo in quay_repos:
                org = quay_repo["org"]["name"]
                instance = quay_repo["org"]["instance"]["name"]
                server_url = quay_repo["org"]["instance"]["url"]
                org_key = OrgKey(instance, org)

                for item in quay_repo["items"]:
                    if item["mirror"] is None:
                        continue

                    mirror_url = item["mirror"]["url"]

                    # URL filtering supports incident response (mirror
                    # only one image) or maintenance (exclude a
                    # known-bad upstream).
                    if repo_urls and mirror_url not in repo_urls:
                        continue
                    if exclude_urls and mirror_url in exclude_urls:
                        continue

                    source_creds = self.resolve_source_credentials(
                        item["mirror"]["pullCredentials"]
                    )
                    dest_creds = self.resolve_destination_credentials(org_key)

                    specs.append(
                        MirrorSpec(
                            source_url=mirror_url,
                            source_creds=source_creds,
                            destination_url=f"{server_url}/{org}/{item['name']}",
                            destination_creds=dest_creds,
                            tag_include=item["mirror"].get("tags"),
                            tag_exclude=item["mirror"].get("tagsExclude"),
                        )
                    )

        return specs

    def _get_push_creds(self) -> dict[OrgKey, str]:
        """Fetch push credentials for all Quay orgs from Vault. The
        GraphQL query returns Vault paths, not secrets."""
        result = self.gqlapi.query(QUAY_ORG_CATALOG_QUERY)

        creds: dict[OrgKey, str] = {}
        if not result:
            return creds

        for org_data in result.get("quay_orgs") or []:
            push_secret = org_data.get("pushCredentials")
            # Orgs without push credentials are read-only.
            if push_secret is None:
                continue

            raw_data = self.secret_reader.read_all(push_secret)
            org = org_data["name"]
            instance = org_data["instance"]["name"]
            org_key = OrgKey(instance, org)
            creds[org_key] = f"{raw_data['user']}:{raw_data['token']}"

        return creds


# Equivalent of Go's init() in add_pod.go. When this module is
# imported, the Quay implementation is registered.
register("quay-mirror", QuayMirror)

# Used by the integration framework for metric labels, log context,
# and early-exit cache keys.
QONTRACT_INTEGRATION = "quay-mirror"
CONTROL_FILE_NAME = "qontract-reconcile-quay-mirror.timestamp"


def run(
    dry_run: bool,
    control_file_dir: str | None,
    compare_tags: bool | None,
    compare_tags_interval: int,
    repository_urls: Iterable[str] | None,
    exclude_repository_urls: Iterable[str] | None,
) -> None:
    """Module-level entry point called by the integration framework.
    Parameters map directly to CLI options in reconcile/cli.py."""
    impl = QuayMirror(
        repository_urls=repository_urls,
        exclude_repository_urls=exclude_repository_urls,
    )
    timer = DeepSyncTimer.from_dir(
        control_file_dir=control_file_dir,
        control_file_name=CONTROL_FILE_NAME,
        interval=compare_tags_interval,
        compare_tags_override=compare_tags,
    )
    specs = impl.discover_mirrors()
    engine = MirrorEngine(
        skopeo=Skopeo(dry_run),
        dry_run=dry_run,
        deep_sync_timer=timer,
    )
    engine.sync(specs)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """The early-exit mechanism hashes this return value and compares
    it to the previous run's hash. If the desired state has not
    changed, the integration skips execution entirely."""
    impl = QuayMirror()
    return {
        "repos": impl.discover_mirrors(),
        "orgs": impl.push_creds,
    }
