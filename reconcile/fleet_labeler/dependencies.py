from __future__ import annotations

from collections.abc import Mapping

from reconcile.fleet_labeler.metrics import FleetLabelerMetrics
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
        label_specs_by_name: Mapping[str, FleetLabelsSpecV1],
        ocm_clients_by_label_spec_name: Mapping[str, OCMClient],
        metrics: FleetLabelerMetrics,
        vcs: VCS,
        dry_run: bool,
    ):
        self.label_specs_by_name = label_specs_by_name
        self.ocm_clients_by_label_spec_name = ocm_clients_by_label_spec_name
        self.vcs = vcs
        self.metrics = metrics
        self.dry_run = dry_run

    @classmethod
    def create(
        cls,
        secret_reader: SecretReaderBase,
        dry_run: bool = True,
    ) -> Dependencies:
        return Dependencies(
            label_specs_by_name=_label_specs(),
            ocm_clients_by_label_spec_name=_ocm_clients(secret_reader=secret_reader),
            vcs=_vcs(secret_reader=secret_reader, dry_run=dry_run),
            dry_run=dry_run,
            metrics=FleetLabelerMetrics(),
        )


def _label_specs() -> dict[str, FleetLabelsSpecV1]:
    return {spec.name: spec for spec in get_fleet_label_specs()}


def _ocm_clients(secret_reader: SecretReaderBase) -> dict[str, OCMClient]:
    ocm_clients_by_label_spec_name: dict[str, OCMClient] = {}
    for spec in get_fleet_label_specs():
        ocm_base_client = init_ocm_base_client(
            cfg=OCMClientConfig(
                url=spec.ocm_env.url,
                access_token_client_id=spec.ocm_env.access_token_client_id,
                access_token_url=spec.ocm_env.access_token_url,
                access_token_client_secret=spec.ocm_env.access_token_client_secret,
            ),
            secret_reader=secret_reader,
        )
        ocm_clients_by_label_spec_name[spec.name] = OCMClient(ocm_base_client)
    return ocm_clients_by_label_spec_name


def _vcs(secret_reader: SecretReaderBase, dry_run: bool = True) -> VCS:
    return VCS(
        vcs=VCSBase(
            secret_reader=secret_reader,
            github_orgs=get_github_orgs(),
            gitlab_instances=get_gitlab_instances(),
            app_interface_repo_url=get_app_interface_repo_url(),
            dry_run=dry_run,
            allow_deleting_mrs=False,
            allow_opening_mrs=True,
        )
    )
