import logging
from collections.abc import Iterable
from typing import Any

import yaml
from ruamel.yaml.compat import StringIO

from reconcile.fleet_labeler.dependencies import Dependencies
from reconcile.fleet_labeler.merge_request import YamlCluster
from reconcile.fleet_labeler.meta import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
)
from reconcile.fleet_labeler.metrics import FleetLabelerDuplicateClusterMatchesGauge
from reconcile.fleet_labeler.ocm import OCMClient
from reconcile.fleet_labeler.validate import validate_label_specs
from reconcile.fleet_labeler.vcs import VCS
from reconcile.gql_definitions.fleet_labeler.fleet_labels import (
    FleetLabelDefaultV1,
    FleetLabelsSpecV1,
    FleetSubscriptionLabelTemplateV1,
)
from reconcile.typed_queries.fleet_labels import get_fleet_label_specs
from reconcile.utils import (
    metrics,
)
from reconcile.utils.jinja2.utils import process_jinja2_template
from reconcile.utils.ruamel import create_ruamel_instance
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)


class FleetLabelerIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Return the desired state for early exit."""
        return {
            "version": QONTRACT_INTEGRATION_VERSION,
            "specs": {spec.name: spec.dict() for spec in get_fleet_label_specs()},
        }

    def run(self, dry_run: bool) -> None:
        dependencies = Dependencies.create(
            secret_reader=self.secret_reader,
            dry_run=dry_run,
        )
        self.reconcile(dependencies=dependencies)

    def reconcile(self, dependencies: Dependencies) -> None:
        validate_label_specs(specs=dependencies.label_specs_by_name)
        for spec_name, ocm in dependencies.ocm_clients_by_label_spec_name.items():
            self._sync_cluster_inventory(
                ocm, dependencies.label_specs_by_name[spec_name], dependencies.vcs
            )

    def _render_default_labels(
        self,
        template: FleetSubscriptionLabelTemplateV1,
        labels: dict[str, str],
    ) -> dict[str, Any]:
        if not template.path:
            # Make mypy happy
            raise ValueError("path is required for subscription label template")
        body = template.path.content
        type = template.q_type or "jinja2"
        extra_curly = type == "extracurlyjinja2"
        vars = dict(template.variables or {})
        vars["labels"] = labels
        rendered = process_jinja2_template(
            body,
            vars,
            extra_curly=extra_curly,
        )
        return yaml.safe_load(rendered)

    def _render_yaml_file(
        self,
        current_content: str,
        ids_to_delete: Iterable[str],
        clusters_to_add: Iterable[YamlCluster],
    ) -> str:
        yml = create_ruamel_instance(pure=True)
        content = yml.load(current_content)
        current_clusters = content.get("clusters", [])
        desired_clusters = [
            cluster
            for cluster in current_clusters
            if cluster.get("clusterId") not in ids_to_delete
        ]
        desired_clusters.extend([
            {
                "name": cluster.name,
                "clusterId": cluster.cluster_id,
                "serverUrl": cluster.server_url,
                "subscriptionLabels": cluster.subscription_labels_content,
            }
            for cluster in clusters_to_add
        ])
        content["clusters"] = desired_clusters
        with StringIO() as stream:
            yml.dump(content, stream)
            return stream.getvalue()

    def _process_default_label(
        self,
        ocm: OCMClient,
        spec_name: str,
        label_default: FleetLabelDefaultV1,
        all_current_cluster_ids: set[str],
        cluster_ids_with_duplicate_matches: set[str],
        all_desired_cluster_ids: set[str],
        clusters_to_add: list[YamlCluster],
    ) -> None:
        discovered_clusters_by_id = {
            cluster.cluster_id: cluster
            for cluster in ocm.discover_clusters_by_labels(
                labels=dict(label_default.match_subscription_labels)
            )
            # TODO: ideally we filter on server side - see TODO in ocm.py
            if dict(label_default.match_subscription_labels).items()
            <= cluster.subscription_labels.items()
        }
        for discovered_id in discovered_clusters_by_id:
            if discovered_id in cluster_ids_with_duplicate_matches:
                # We already identified this cluster id as a duplicate match
                continue
            if discovered_id in all_desired_cluster_ids:
                logging.error(
                    f"Spec '{spec_name}': Cluster ID {discovered_id} is matched multiple times by different label matchers."
                )
                cluster_ids_with_duplicate_matches.add(discovered_id)
                all_desired_cluster_ids.remove(discovered_id)
                continue
            all_desired_cluster_ids.add(discovered_id)
        cluster_ids_to_add = discovered_clusters_by_id.keys() - all_current_cluster_ids
        for cluster_id in cluster_ids_to_add:
            # We want to query actual cluster labels only for clusters that need to be added
            if cluster_id in cluster_ids_with_duplicate_matches:
                continue
            cluster = discovered_clusters_by_id[cluster_id]
            clusters_to_add.append(
                YamlCluster(
                    cluster_id=cluster.cluster_id,
                    name=cluster.name,
                    server_url=cluster.server_url,
                    subscription_labels_content=self._render_default_labels(
                        template=label_default.subscription_label_template,
                        labels=ocm.get_cluster_labels(cluster_id=cluster.cluster_id),
                    ),
                )
            )

    def _sync_cluster_inventory(
        self, ocm: OCMClient, spec: FleetLabelsSpecV1, vcs: VCS
    ) -> None:
        all_current_cluster_ids = {cluster.cluster_id for cluster in spec.clusters}
        all_desired_cluster_ids: set[str] = set()
        clusters_to_add: list[YamlCluster] = []
        cluster_ids_with_duplicate_matches: set[str] = set()
        for label_default in spec.label_defaults:
            self._process_default_label(
                ocm=ocm,
                spec_name=spec.name,
                label_default=label_default,
                all_current_cluster_ids=all_current_cluster_ids,
                cluster_ids_with_duplicate_matches=cluster_ids_with_duplicate_matches,
                all_desired_cluster_ids=all_desired_cluster_ids,
                clusters_to_add=clusters_to_add,
            )

        all_desired_cluster_ids -= cluster_ids_with_duplicate_matches
        cluster_ids_to_delete = all_current_cluster_ids - all_desired_cluster_ids
        clusters_to_add = [
            cluster
            for cluster in clusters_to_add
            if cluster.cluster_id not in cluster_ids_with_duplicate_matches
        ]

        metrics.set_gauge(
            FleetLabelerDuplicateClusterMatchesGauge(
                integration=self.name,
                ocm_name=spec.ocm.name,
            ),
            len(cluster_ids_with_duplicate_matches),
        )
        if not (cluster_ids_to_delete or clusters_to_add):
            return

        current_content = vcs.get_file_content_from_main(path=spec.path)
        # Lets make sure we are deterministic when adding new clusters
        # The overhead is neglectable and it makes testing easier
        sorted_clusters_to_add = sorted(clusters_to_add, key=lambda c: c.name)
        desired_content = self._render_yaml_file(
            current_content, cluster_ids_to_delete, sorted_clusters_to_add
        )
        vcs.open_merge_request(path=spec.path, content=desired_content)
