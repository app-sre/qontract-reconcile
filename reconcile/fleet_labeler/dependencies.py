from reconcile.fleet_labeler.ocm import OCMClient, OCMClientConfig
from reconcile.fleet_labeler.vcs import VCS
from reconcile.gql_definitions.fleet_labeler.fleet_labels import FleetLabelsSpecV1
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.fleet_labels import get_fleet_label_specs
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.utils.ocm_base_client import (
    init_ocm_base_client,
)
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.vcs import VCS as VCSBase


class Dependencies:
    """
    Depenedencies class to hold all the dependencies (API clients, Specs) for the Fleet Labeler.
    Dependency inversion simplifies setting up tests.
    """

    def __init__(
        self,
        secret_reader: SecretReaderBase,
        dry_run: bool = True,
    ):
        self.secret_reader = secret_reader
        self.label_specs_by_name: dict[str, FleetLabelsSpecV1] = {}
        self.ocm_clients_by_label_spec_name: dict[str, OCMClient] = {}
        self.vcs: VCS | None = None
        self.dry_run = dry_run

    def populate_all(self) -> None:
        self.populate_label_specs()
        self.populate_ocm_clients()
        self.populate_vcs()

    def populate_label_specs(self) -> None:
        self.label_specs_by_name = {spec.name: spec for spec in get_fleet_label_specs()}

    def populate_ocm_clients(self) -> None:
        # Extra query for label specs so we stay independent of call order.
        # The extra gql query doesnt hurt, since this integration is not sharded
        # and runs only every couple of minutes.
        for spec in get_fleet_label_specs():
            ocm_base_client = init_ocm_base_client(
                cfg=OCMClientConfig(
                    url=spec.ocm.environment.url,
                    access_token_client_id=spec.ocm.access_token_client_id,
                    access_token_url=spec.ocm.access_token_url,
                    access_token_client_secret=spec.ocm.access_token_client_secret,
                ),
                secret_reader=self.secret_reader,
            )
            self.ocm_clients_by_label_spec_name[spec.name] = OCMClient(ocm_base_client)

    def populate_vcs(self) -> None:
        self.vcs = VCS(
            vcs=VCSBase(
                secret_reader=self.secret_reader,
                github_orgs=get_github_orgs(),
                gitlab_instances=get_gitlab_instances(),
                app_interface_repo_url=get_app_interface_repo_url(),
                dry_run=self.dry_run,
                allow_deleting_mrs=False,
                allow_opening_mrs=True,
            )
        )
