import json
import logging
from typing import (
    Any,
    Optional,
)

import yaml

import reconcile.utils.mr.ocm_upgrade_scheduler_org_updates as ousou
from reconcile import (
    mr_client_gateway,
    queries,
)
from reconcile.openshift_resources_base import process_jinja2_template
from reconcile.utils.ocm import (
    OCMMap,
    OCMSpec,
)

QONTRACT_INTEGRATION = "ocm-upgrade-scheduler-org-updater"


def render_policy(
    template: dict[str, Any],
    cluster_spec: OCMSpec,
    labels: dict[str, str],
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    body = template["path"]["content"]
    type = template.get("type") or "jinja2"
    extra_curly = type == "extracurlyjinja2"
    vars = json.loads(template.get("variables") or "{}")
    vars["cluster"] = cluster_spec
    vars["labels"] = labels
    rendered = process_jinja2_template(
        body, vars, extra_curly=extra_curly, settings=settings
    )
    return yaml.safe_load(rendered)


def run(dry_run, gitlab_project_id):
    settings = queries.get_app_interface_settings()
    ocms = queries.get_openshift_cluster_managers()
    for ocm_info in ocms:
        updates = []
        create_update_mr = False
        upgrade_policy_defaults = ocm_info.get("upgradePolicyDefaults")
        if not upgrade_policy_defaults:
            continue

        upgrade_policy_clusters = ocm_info.get("upgradePolicyClusters") or []
        ocm_map = OCMMap(
            ocms=[ocm_info],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            init_version_gates=True,
        )
        ocm_name = ocm_info["name"]
        ocm_path = ocm_info["path"]
        ocm = ocm_map[ocm_name]

        for ocm_cluster_name, ocm_cluster_spec in ocm.clusters.items():
            found = [
                c for c in upgrade_policy_clusters if c["name"] == ocm_cluster_name
            ]
            if not found:
                ocm_cluster_labels = ocm.get_external_configuration_labels(
                    ocm_cluster_name
                )
                for default in upgrade_policy_defaults:
                    default_name = default["name"]
                    match_labels: dict[str, str] = json.loads(default["matchLabels"])
                    if match_labels.items() <= ocm_cluster_labels.items():
                        create_update_mr = True
                        logging.info(
                            ["add_cluster", ocm_name, ocm_cluster_name, default_name]
                        )
                        policy = default["upgradePolicy"]
                        if not policy:
                            template = default["upgradePolicyTemplate"]
                            policy = render_policy(
                                template, ocm_cluster_spec, ocm_cluster_labels, settings
                            )
                        item = {
                            "action": "add",
                            "cluster": ocm_cluster_name,
                            "policy": policy,
                        }
                        updates.append(item)
                        break

        for up_cluster in upgrade_policy_clusters:
            up_cluster_name = up_cluster["name"]
            found = [c for c in ocm.clusters if c == up_cluster_name]
            if not found:
                create_update_mr = True
                logging.info(["delete_cluster", ocm_name, up_cluster_name])
                item = {
                    "action": "delete",
                    "cluster": up_cluster_name,
                }
                updates.append(item)

        if create_update_mr and not dry_run:
            mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)
            updates_info = {
                "path": "data" + ocm_path,
                "name": ocm_name,
                "updates": updates,
            }
            mr = ousou.CreateOCMUpgradeSchedulerOrgUpdates(updates_info)
            mr.submit(cli=mr_cli)
