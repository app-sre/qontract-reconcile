from collections.abc import Iterable
from typing import Any

import yaml
from ruamel.yaml.compat import StringIO

from reconcile.fleet_labeler.dependencies import Dependencies
from reconcile.fleet_labeler.merge_request import YamlCluster
from reconcile.fleet_labeler.meta import QONTRACT_INTEGRATION
from reconcile.fleet_labeler.ocm import OCMClient
from reconcile.fleet_labeler.validate import validate_label_specs
from reconcile.fleet_labeler.vcs import VCS
from reconcile.gql_definitions.fleet_labeler.fleet_labels import (
    FleetLabelsSpecV1,
    FleetSubscriptionLabelTemplateV1,
)
from reconcile.utils.differ import DiffResult, diff_iterables
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

    def run(self, dry_run: bool) -> None:
        dependencies = Dependencies(
            secret_reader=self.secret_reader,
            dry_run=dry_run,
        )
        dependencies.populate_all()
        self.reconcile(dependencies=dependencies)

    def reconcile(self, dependencies: Dependencies) -> None:
        validate_label_specs(specs=dependencies.label_specs_by_name)
        if not dependencies.vcs:
            raise ValueError("VCS is not initialized")
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

    def _sync_cluster_inventory(
        self, ocm: OCMClient, spec: FleetLabelsSpecV1, vcs: VCS
    ) -> None:
        all_current_cluster_ids = [cluster.cluster_id for cluster in spec.clusters]
        all_desired_cluster_ids: list[str] = []
        clusters_to_add: list[YamlCluster] = []
        for label_default in spec.label_defaults:
            discovered_clusters_by_id = {
                cluster.cluster_id: cluster
                for cluster in ocm.discover_clusters_by_label_keys(
                    keys=list(dict(label_default.match_subscription_labels).keys())
                )
                if dict(label_default.match_subscription_labels).items()
                <= cluster.subscription_labels.items()
            }
            diff: DiffResult[str, str, str] = diff_iterables(
                current=all_current_cluster_ids,
                desired=discovered_clusters_by_id.keys(),
            )
            all_desired_cluster_ids.extend(discovered_clusters_by_id.keys())
            for cluster_id in diff.add:
                # We want to query actual cluster labels only for clusters that need to be added
                cluster = discovered_clusters_by_id[cluster_id]
                clusters_to_add.append(
                    YamlCluster(
                        cluster_id=cluster.cluster_id,
                        name=cluster.name,
                        server_url=cluster.server_url,
                        subscription_labels_content=self._render_default_labels(
                            template=label_default.subscription_label_template,
                            labels=ocm.get_cluster_labels(
                                cluster_id=cluster.cluster_id
                            ),
                        ),
                    )
                )
        diff = diff_iterables(
            current=all_current_cluster_ids,
            desired=all_desired_cluster_ids,
        )
        cluster_ids_to_delete = diff.delete.values()

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
