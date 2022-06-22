import base64
import logging

from sretoolbox.container import Image
from sretoolbox.container import Skopeo
from sretoolbox.container.skopeo import SkopeoCmdError
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.external_resources import (
    get_external_resource_specs,
    managed_external_resources,
)
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.secret_reader import SecretReader


QONTRACT_INTEGRATION = "ecr-mirror"
LOG = logging.getLogger(__name__)


class EcrMirror:
    def __init__(self, instance: ExternalResourceSpec, dry_run: bool):
        self.dry_run = dry_run
        self.instance = instance
        self.settings = queries.get_app_interface_settings()
        self.secret_reader = SecretReader(settings=self.settings)
        self.skopeo_cli = Skopeo(dry_run)
        self.error = False

        identifier = instance.identifier
        account = instance.provisioner_name
        region = instance.resource.get("region")

        self.aws_cli = AWSApi(
            thread_pool_size=1,
            accounts=[self._get_aws_account_info(account)],
            settings=self.settings,
            init_ecr_auth_tokens=True,
        )

        self.aws_cli.map_ecr_resources()

        self.ecr_uri = self._get_image_uri(
            account=account,
            repository=identifier,
        )
        if self.ecr_uri is None:
            self.error = True
            LOG.error(f"Could not find the ECR repository {identifier}")

        self.ecr_username, self.ecr_password = self._get_ecr_creds(
            account=account,
            region=region,
        )
        self.ecr_auth = f"{self.ecr_username}:{self.ecr_password}"

        self.image_username = None
        self.image_password = None
        self.image_auth = None
        pull_secret = self.instance.resource["mirror"]["pullCredentials"]
        if pull_secret is not None:
            raw_data = self.secret_reader.read_all(pull_secret)
            self.image_username = raw_data["user"]
            self.image_password = raw_data["token"]
            self.image_auth = f"{self.image_username}:{self.image_password}"

    def run(self):
        if self.error:
            return

        ecr_mirror = Image(
            self.ecr_uri, username=self.ecr_username, password=self.ecr_password
        )

        image = Image(
            self.instance.resource["mirror"]["url"],
            username=self.image_username,
            password=self.image_password,
        )

        LOG.debug("[checking %s -> %s]", image, ecr_mirror)
        for tag in image:
            if tag not in ecr_mirror:
                try:
                    self.skopeo_cli.copy(
                        src_image=image[tag],
                        src_creds=self.image_auth,
                        dst_image=ecr_mirror[tag],
                        dest_creds=self.ecr_auth,
                    )
                except SkopeoCmdError as details:
                    LOG.error("[%s]", details)

    def _get_ecr_creds(self, account, region):
        if region is None:
            region = self.aws_cli.accounts[account]["resourcesDefaultRegion"]
        auth_token = f"{account}/{region}"
        data = self.aws_cli.auth_tokens[auth_token]
        auth_data = data["authorizationData"][0]
        token = auth_data["authorizationToken"]
        password = base64.b64decode(token).decode("utf-8").split(":")[1]
        return "AWS", password

    def _get_image_uri(self, account, repository):
        for repo in self.aws_cli.resources[account]["ecr"]:
            if repo["repositoryName"] == repository:
                return repo["repositoryUri"]

    @staticmethod
    def _get_aws_account_info(account):
        for account_info in queries.get_aws_accounts():
            if "name" not in account_info:
                continue
            if account_info["name"] != account:
                continue
            return account_info


def worker(ecr_mirror_instance):
    return ecr_mirror_instance.run()


def run(dry_run, thread_pool_size=10):
    namespaces = queries.get_namespaces()

    tfrs_to_mirror = []
    for namespace in namespaces:

        if not managed_external_resources(namespace):
            continue

        for spec in get_external_resource_specs(namespace):
            if spec.provider != "ecr":
                continue

            if spec.resource.get("mirror") is None:
                continue

            tfrs_to_mirror.append(spec)

    work_list = threaded.run(
        EcrMirror, tfrs_to_mirror, thread_pool_size=thread_pool_size, dry_run=dry_run
    )
    threaded.run(worker, work_list, thread_pool_size=thread_pool_size)
