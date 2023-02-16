import base64
import logging
import sys
from collections import namedtuple
from collections.abc import Mapping
from typing import (
    Any,
    Optional,
)
from urllib.parse import urlparse

from sretoolbox.container import Image

from reconcile import queries
from reconcile.gql_definitions.ocp_release_mirror.ocp_release_mirror import (
    NamespaceV1,
    OcpReleaseMirrorV1,
)
from reconcile.quay_base import (
    OrgKey,
    get_quay_api_store,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.ocp_release_mirror import get_ocp_release_mirrors
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.external_resources import get_external_resource_specs
from reconcile.utils.oc import OCLocal
from reconcile.utils.oc_map import init_oc_map_from_clusters
from reconcile.utils.ocm import OCMMap
from reconcile.utils.secret_reader import create_secret_reader

QONTRACT_INTEGRATION = "ocp-release-mirror"

LOG = logging.getLogger(__name__)

OcpReleaseInfo = namedtuple("OcpReleaseInfo", ["ocp_release", "tag"])


class OcpReleaseMirrorError(Exception):
    """
    Used by the OcpReleaseMirror.
    """


class OcpReleaseMirror:
    def __init__(self, dry_run: bool, instance: OcpReleaseMirrorV1):
        self.dry_run = dry_run
        settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=settings.vault)

        cluster_info = instance.hive_cluster
        hive_cluster = instance.hive_cluster.name

        # Getting the OCM Client for the hive cluster
        ocm_map = OCMMap(
            clusters=[cluster_info.dict(by_alias=True)],
            integration=QONTRACT_INTEGRATION,
            settings=settings.dict(by_alias=True),
        )

        self.ocm_cli = ocm_map.get(hive_cluster)
        if self.ocm_cli is None:
            raise OcpReleaseMirrorError(
                f"Can't create ocm client for " f"cluster {hive_cluster}"
            )

        # Getting the OC Client for the hive cluster
        oc_map = init_oc_map_from_clusters(
            clusters=[cluster_info],
            integration=QONTRACT_INTEGRATION,
            secret_reader=secret_reader,
        )
        self.oc_cli = oc_map.get(hive_cluster)
        if not self.oc_cli:
            raise OcpReleaseMirrorError(
                f"Can't create oc client for " f"cluster {hive_cluster}"
            )

        namespace = instance.ecr_resources_namespace
        ocp_release_identifier = instance.ocp_release_ecr_identifier
        ocp_art_dev_identifier = instance.ocp_art_dev_ecr_identifier

        ocp_release_info = self._get_tf_resource_info(
            namespace=namespace, identifier=ocp_release_identifier
        )
        if ocp_release_info is None:
            raise OcpReleaseMirrorError(
                f"Could not find rds "
                f"identifier "
                f"{ocp_release_identifier} in "
                f"namespace {namespace.name}"
            )

        ocp_art_dev_info = self._get_tf_resource_info(
            namespace=namespace, identifier=ocp_art_dev_identifier
        )
        if ocp_art_dev_info is None:
            raise OcpReleaseMirrorError(
                f"Could not find rds identifier"
                f" {ocp_art_dev_identifier} in"
                f"namespace {namespace.name}"
            )

        # Getting the AWS Client for the accounts
        aws_accounts = [
            self._get_aws_account_info(account=ocp_release_info["account"]),
            self._get_aws_account_info(account=ocp_art_dev_info["account"]),
        ]
        self.aws_cli = AWSApi(
            thread_pool_size=1,
            accounts=aws_accounts,
            secret_reader=secret_reader,
            init_ecr_auth_tokens=True,
        )
        self.aws_cli.map_ecr_resources()

        self.ocp_release_ecr_uri = self._get_image_uri(
            account=ocp_release_info["account"], repository=ocp_release_identifier
        )
        if self.ocp_release_ecr_uri is None:
            raise OcpReleaseMirrorError(
                f"Could not find the " f"ECR repository " f"{ocp_release_identifier}"
            )

        self.ocp_art_dev_ecr_uri = self._get_image_uri(
            account=ocp_art_dev_info["account"], repository=ocp_art_dev_identifier
        )
        if self.ocp_art_dev_ecr_uri is None:
            raise OcpReleaseMirrorError(
                f"Could not find the " f"ECR repository " f"{ocp_art_dev_identifier}"
            )

        # Process all the quayOrgTargets
        quay_api_store = get_quay_api_store()
        self.quay_target_orgs: list[dict[str, Any]] = []
        for quay_target_org in instance.quay_target_orgs:
            org_name = quay_target_org.name
            instance_name = quay_target_org.instance.name
            org_key = OrgKey(instance_name, org_name)
            org_info = quay_api_store[org_key]

            if not org_info["push_token"]:
                raise OcpReleaseMirrorError(f"{org_key} has no push_token defined.")

            url = org_info["url"]
            user = org_info["push_token"]["user"]
            token = org_info["push_token"]["token"]

            self.quay_target_orgs.append(
                {
                    "url": url,
                    "dest_ocp_release": f"{url}/{org_name}/ocp-release",
                    "dest_ocp_art_dev": f"{url}/{org_name}/ocp-v4.0-art-dev",
                    "auths": self._build_quay_auths(url, user, token),
                }
            )

        # Getting all the credentials
        quay_creds = self._get_quay_creds()
        ocp_release_creds = self._get_ecr_creds(
            account=ocp_release_info["account"], region=ocp_release_info["region"]
        )
        ocp_art_dev_creds = self._get_ecr_creds(
            account=ocp_art_dev_info["account"], region=ocp_art_dev_info["region"]
        )

        # Creating a single dictionary with all credentials to be used by the
        # "oc adm release mirror" command
        self.registry_creds = {
            "auths": {
                **quay_creds["auths"],
                **ocp_release_creds["auths"],
                **ocp_art_dev_creds["auths"],
            }
        }

        # Append quay_target_orgs auths to registry_creds
        for quay_target_org_dict in self.quay_target_orgs:
            url = quay_target_org_dict["url"]

            if url in self.registry_creds["auths"].keys():
                OcpReleaseMirrorError(
                    "Cannot mirror to the same Quay " f"instance multiple times: {url}"
                )

            self.registry_creds["auths"].update(quay_target_org_dict["auths"])

        # Initiate channel groups
        self.channel_groups = instance.mirror_channels

    def run(self):
        ocp_releases = self._get_ocp_releases()
        if not ocp_releases:
            raise RuntimeError("No OCP Releases found")

        for ocp_release_info in ocp_releases:
            ocp_release = ocp_release_info.ocp_release
            tag = ocp_release_info.tag

            # mirror to ecr
            dest_ocp_release = f"{self.ocp_release_ecr_uri}:{tag}"
            self._run_mirror(
                ocp_release=ocp_release,
                dest_ocp_release=dest_ocp_release,
                dest_ocp_art_dev=self.ocp_art_dev_ecr_uri,
            )

            # mirror to all quay target orgs
            for quay_target_org in self.quay_target_orgs:
                dest_ocp_release = f'{quay_target_org["dest_ocp_release"]}:' f"{tag}"
                dest_ocp_art_dev = quay_target_org["dest_ocp_art_dev"]
                self._run_mirror(
                    ocp_release=ocp_release,
                    dest_ocp_release=dest_ocp_release,
                    dest_ocp_art_dev=dest_ocp_art_dev,
                )

    def _run_mirror(self, ocp_release, dest_ocp_release, dest_ocp_art_dev):
        # Checking if the image is already there
        if self._is_image_there(dest_ocp_release):
            LOG.debug(f"Image {ocp_release} already in " f"the mirror. Skipping.")
            return

        LOG.info(
            f"Mirroring {ocp_release} to {dest_ocp_art_dev} "
            f"to_release {dest_ocp_release}"
        )

        if self.dry_run:
            return

        # Creating a new, bare, OC client since we don't
        # want to run this against any cluster or via
        # a jump host
        oc_cli = OCLocal("cluster", None, None, local=True)
        oc_cli.release_mirror(
            from_release=ocp_release,
            to=dest_ocp_art_dev,
            to_release=dest_ocp_release,
            dockerconfig=self.registry_creds,
        )

    def _is_image_there(self, image):
        image_obj = Image(image)

        for registry, creds in self.registry_creds["auths"].items():
            # Getting the credentials for the image_obj
            if "//" not in registry:
                registry = "//" + registry
            registry_obj = urlparse(registry)

            if registry_obj.netloc != image_obj.registry:
                continue
            image_obj.auth = (creds["username"], creds["password"])

            # Checking if the image is already
            # in the registry
            if image_obj:
                return True

        return False

    @staticmethod
    def _get_aws_account_info(
        account: Optional[Mapping[str, Any]]
    ) -> Optional[dict[str, Any]]:
        for account_info in queries.get_aws_accounts():
            if "name" not in account_info:
                continue
            if account_info["name"] != account:
                continue
            return account_info
        return None

    def _get_ocp_releases(self):
        ocp_releases = []
        clusterimagesets = self.oc_cli.get_all("ClusterImageSet")
        for clusterimageset in clusterimagesets["items"]:
            release_image = clusterimageset["spec"]["releaseImage"]
            # There are images in some ClusterImagesSets not coming
            # from quay.io, e.g.:
            # registry.svc.ci.openshift.org/ocp/release:4.2.0-0.nightly-2020-11-04-053758
            # Let's filter out everything not from quay.io
            if not release_image.startswith("quay.io"):
                continue
            labels = clusterimageset["metadata"]["labels"]
            name = clusterimageset["metadata"]["name"]
            # ClusterImagesSets may be enabled or disabled.
            # Let's only mirror enabled ones
            enabled = labels["api.openshift.com/enabled"]
            if enabled == "false":
                continue
            # ClusterImageSets may be in different channels.
            channel_group = labels["api.openshift.com/channel-group"]
            if channel_group not in self.channel_groups:
                continue
            ocp_releases.append(OcpReleaseInfo(release_image, name))
        return ocp_releases

    def _get_quay_creds(self):
        return self.ocm_cli.get_pull_secrets()

    def _get_ecr_creds(self, account, region):
        if region is None:
            region = self.aws_cli.accounts[account]["resourcesDefaultRegion"]
        auth_token = f"{account}/{region}"
        data = self.aws_cli.auth_tokens[auth_token]
        auth_data = data["authorizationData"][0]
        server = auth_data["proxyEndpoint"]
        token = auth_data["authorizationToken"]
        password = base64.b64decode(token).decode("utf-8").split(":")[1]

        return {
            "auths": {
                server: {
                    "username": "AWS",
                    "password": password,
                    "email": "sd-app-sre@redhat.com",
                    "auth": token,
                }
            }
        }

    @staticmethod
    def _get_tf_resource_info(
        namespace: NamespaceV1, identifier: str
    ) -> Optional[dict[str, Any]]:
        specs = get_external_resource_specs(namespace.dict(by_alias=True))
        for spec in specs:
            if spec.provider != "ecr":
                continue

            if spec.identifier != identifier:
                continue

            return {
                "account": spec.provisioner_name,
                "region": spec.resource.get("region"),
            }
        return None

    def _get_image_uri(self, account: str, repository: str) -> Any:
        for repo in self.aws_cli.resources[account]["ecr"]:
            if repo["repositoryName"] == repository:
                return repo["repositoryUri"]

    @staticmethod
    def _build_quay_auths(url, user, token):
        auth_bytes = bytes(f"{user}:{token}", "utf-8")
        auth = base64.b64encode(auth_bytes).decode("utf-8")
        return {url: {"username": user, "password": token, "email": "", "auth": auth}}


def run(dry_run: bool) -> None:
    instances = get_ocp_release_mirrors()
    for instance in instances:
        try:
            quay_mirror = OcpReleaseMirror(dry_run=dry_run, instance=instance)
            quay_mirror.run()
        except OcpReleaseMirrorError as details:
            LOG.error(str(details))
            sys.exit(ExitCodes.ERROR)
