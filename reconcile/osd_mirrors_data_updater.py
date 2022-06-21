import logging

from reconcile import mr_client_gateway
from reconcile.utils.external_resources import (
    PROVIDER_AWS,
    get_external_resource_specs,
    managed_external_resources,
)
from reconcile.utils.mr import CSInstallConfig

from reconcile import queries
from reconcile.utils.aws_api import AWSApi


QONTRACT_INTEGRATION = "osd-mirrors-data-updater"
LOG = logging.getLogger(__name__)


def get_ecr_tf_resource_info(namespace, identifier):
    """
    Takes a namespace from app-interface and searches
    a given ECR by its identifier.
    """
    specs = get_external_resource_specs(namespace)
    for spec in specs:
        if spec.provider != "ecr":
            continue

        if spec.identifier != identifier:
            continue

        return spec.resource


def get_aws_account_info(account):
    """
    Gets all AWS accounts from app-interface and searches the
    desired one.
    """
    for account_info in queries.get_aws_accounts():
        if "name" not in account_info:
            continue
        if account_info["name"] != account:
            continue
        return account_info


def get_image_uri(aws_cli, account, repository):
    """
    Finds the repository URI for a given ECR resource.
    """
    for repo in aws_cli.resources[account]["ecr"]:
        if repo["repositoryName"] == repository:
            return repo["repositoryUri"]


def run(dry_run, gitlab_project_id=None):
    settings = queries.get_app_interface_settings()
    namespaces = queries.get_namespaces()

    # This is a list of app-interface ECR resources and their
    # mirrors
    osd_mirrors = []
    for namespace in namespaces:
        # We are only interested on the ECR resources from
        # this specific namespace
        if namespace["name"] != "osd-operators-ecr-mirrors":
            continue

        if not managed_external_resources(namespace):
            continue

        for spec in get_external_resource_specs(
            namespace, provision_provider=PROVIDER_AWS
        ):
            if spec.provider != "ecr":
                continue
            if spec.resource.get("mirror") is None:
                continue

            osd_mirrors.append(spec.resource)

    # Now the tricky part. The "OCP Release ECR Mirror" is a stand-alone
    # object in app-interface. We have to process it so we get the
    # upstream and the mirror repositories
    instances = queries.get_ocp_release_mirror()
    for instance in instances:
        namespace = instance["ecrResourcesNamespace"]
        ocp_release_identifier = instance["ocpReleaseEcrIdentifier"]
        ocp_art_dev_identifier = instance["ocpArtDevEcrIdentifier"]

        ocp_release_tf_info = get_ecr_tf_resource_info(
            namespace, ocp_release_identifier
        )

        # We get an ECR resource from app-interface, but it has
        # no mirror property as the mirroring is done differently
        # there (see qontract-reconcile-ocp-release-mirror).
        # The quay repositories are not managed in app-interface, but
        # we know where they are by looking at the ClusterImageSets
        # in Hive.
        # Let's just manually inject the mirror information so we
        # process all the ECR resources the same way
        ocp_release_tf_info["mirror"] = {
            "url": "quay.io/openshift-release-dev/ocp-release",
            "pullCredentials": None,
            "tags": None,
            "tagsExclude": None,
        }
        osd_mirrors.append(ocp_release_tf_info)
        ocp_art_dev_tf_info = get_ecr_tf_resource_info(
            namespace, ocp_art_dev_identifier
        )
        ocp_art_dev_tf_info["mirror"] = {
            "url": "quay.io/openshift-release-dev/ocp-v4.0-art-dev",
            "pullCredentials": None,
            "tags": None,
            "tagsExclude": None,
        }
        osd_mirrors.append(ocp_art_dev_tf_info)

    # Initializing the AWS Client for all the accounts
    # with ECR resources of interest
    accounts = []
    for tfr in osd_mirrors:
        account = get_aws_account_info(tfr["account"])
        if account not in accounts:
            accounts.append(account)
    aws_cli = AWSApi(
        thread_pool_size=1,
        accounts=accounts,
        settings=settings,
        init_ecr_auth_tokens=True,
    )
    aws_cli.map_ecr_resources()

    # Building up the mirrors information in the
    # install-config.yaml compatible format
    mirrors_info = []
    for tfr in osd_mirrors:
        image_url = get_image_uri(
            aws_cli=aws_cli, account=tfr["account"], repository=tfr["identifier"]
        )
        mirrors_info.append(
            {
                "source": tfr["mirror"]["url"],
                "mirrors": [
                    image_url,
                ],
            }
        )

    if not dry_run:
        # Creating the MR to app-interface
        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)
        mr = CSInstallConfig(mirrors_info=mirrors_info)
        mr.submit(cli=mr_cli)
