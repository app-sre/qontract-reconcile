import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

import yaml
from pydantic import BaseModel
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
from reconcile.fleet_labeler.vcs import VCS, Gitlab404Error
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
                ocm=ocm,
                spec=dependencies.label_specs_by_name[spec_name],
                vcs=dependencies.vcs,
                dry_run=dependencies.dry_run,
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
                "subscriptionId": cluster.subscription_id,
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
        self,
        ocm: OCMClient,
        spec: FleetLabelsSpecV1,
        vcs: VCS,
        dry_run: bool,
    ) -> None:
        class ClusterData(BaseModel):
            """
            Helper structure for synching process
            """

            name: str
            server_url: str
            subscription_id: str
            label_default: FleetLabelDefaultV1

        all_current_cluster_ids = {cluster.cluster_id for cluster in spec.clusters}
        clusters: dict[str, list[ClusterData]] = defaultdict(list)
        for label_default in spec.label_defaults:
            match_subscription_labels = dict(label_default.match_subscription_labels)
            for cluster in ocm.discover_clusters_by_labels(
                labels=match_subscription_labels
            ):
                # TODO: ideally we filter on server side - see TODO in ocm.py
                if (
                    match_subscription_labels.items()
                    <= cluster.subscription_labels.items()
                ):
                    clusters[cluster.cluster_id].append(
                        ClusterData(
                            label_default=label_default,
                            subscription_id=cluster.subscription_id,
                            name=cluster.name,
                            server_url=cluster.server_url,
                        )
                    )

        cluster_with_duplicate_matches = {
            k: v for k, v in clusters.items() if len(v) > 1
        }
        for cluster_id, matches in cluster_with_duplicate_matches.items():
            label_matches = "\n".join(
                str(m.label_default.match_subscription_labels) for m in matches
            )
            logging.error(
                f"Spec '{spec.name}': Cluster ID {cluster_id} is matched multiple times by different label matchers:\n{label_matches}"
            )
        metrics.set_gauge(
            FleetLabelerDuplicateClusterMatchesGauge(
                integration=self.name,
                ocm_name=spec.ocm.name,
            ),
            len(cluster_with_duplicate_matches),
        )

        all_desired_clusters = {k: v[0] for k, v in clusters.items() if len(v) == 1}
        clusters_to_add = [
            YamlCluster(
                cluster_id=cluster_id,
                subscription_id=cluster_info.subscription_id,
                name=cluster_info.name,
                server_url=cluster_info.server_url,
                subscription_labels_content=self._render_default_labels(
                    template=cluster_info.label_default.subscription_label_template,
                    labels=ocm.get_cluster_labels(cluster_id=cluster_id),
                ),
            )
            for cluster_id, cluster_info in all_desired_clusters.items()
            if cluster_id not in all_current_cluster_ids
        ]
        cluster_ids_to_delete = all_current_cluster_ids - all_desired_clusters.keys()

        if not (cluster_ids_to_delete or clusters_to_add):
            return

        for yaml_cluster in clusters_to_add:
            logging.info(
                f"[{spec.name}] Adding cluster '{yaml_cluster.name}' with id '{yaml_cluster.cluster_id}' to inventory with default labels {yaml_cluster.subscription_labels_content}."
            )
        for cluster_id in cluster_ids_to_delete:
            logging.info(
                f"[{spec.name}] Deleting cluster {cluster_id=} from inventory."
            )

        # When adding a new label spec file, then we dont have any existing content in main yet.
        # This is a chicken-egg problem, but if we are in dry-run we can skip these steps on 404s.
        # Note, that the diff is already printed above, so we can make a good decision if desired
        # content fits.
        # If the content exists in main, then it doesnt harm to also run the rendering procedure.
        try:
            current_content = vcs.get_file_content_from_main(path=spec.path)
        except Gitlab404Error:
            if dry_run:
                logging.info(
                    f"The file data{spec.path} does not exist in main branch yet. This is likely because it is being created with this MR. We are skipping rendering steps."
                )
                return
            # 404 must never happen on non-dry-run, as the file must have already passed
            # MR check and must have been merged to main
            raise

        # Lets make sure we are deterministic when adding new clusters
        # The overhead is neglectable and it makes testing easier
        sorted_clusters_to_add = sorted(clusters_to_add, key=lambda c: c.name)
        desired_content = self._render_yaml_file(
            current_content, cluster_ids_to_delete, sorted_clusters_to_add
        )
        vcs.open_merge_request(path=f"data{spec.path}", content=desired_content)
