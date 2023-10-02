import re
import yaml

from jinja2 import Template


from reconcile.typed_queries.status_board import (
    get_status_board,
)

from reconcile.status_board import StatusBoardExporterIntegration
from reconcile.dashdotdb_slo import get_slo_documents

QONTRACT_INTEGRATION = "slo-document-alerts"


def run(dry_run: bool, thread_pool_size: int = 5) -> None:
    sb = [sb for sb in get_status_board() if sb.name == "status-board-production"][0]
    desired_product_apps: dict[
        str, set[str]
    ] = StatusBoardExporterIntegration.get_product_apps(sb)

    status_board_services = []
    for slo_doc in get_slo_documents():
        for ns in slo_doc.namespaces:
            product = ns.namespace.environment.product.name
            app = ns.namespace.app.name

            if app not in desired_product_apps.get(product, []):
                continue

            alerts = []
            for slo in slo_doc.slos:
                status_board_service = f"{product}/{app}/{slo.name}"
                status_board_services.append(status_board_service)

                expr = (
                    Template(slo.expr).render(slo.slo_parameters.__dict__)
                    + f" <= {slo.slo_target}"
                )

                alert = {
                    "alert": slo.name,
                    "expr": expr,
                    "for": "10m",
                    "labels": {"statusBoardService": status_board_service},
                    "annotations": {
                        "SLIType": slo.sli_type,
                        "SLOTarget": slo.slo_target,
                        "SLOTargetUnit": slo.slo_target_unit,
                        "SLODetails": slo.slo_details,
                        "SLISpecification": slo.sli_specification,
                        "prometheusRules": slo.prometheus_rules,
                    },
                }
                alerts.append(alert)

            prometheus_rules = {
                "apiVersion": "monitoring.coreos.com/v1",
                "kind": "PrometheusRule",
                "metadata": {
                    "name": f"slo-document-{slo_doc.name}",
                },
                "spec": {
                    "groups": [
                        {"name": f"slo-document-{slo_doc.name}", "rules": alerts}
                    ]
                },
            }

            print(f"# slodoc path: {slo_doc.path}")
            print(f"# namespace path: {ns.namespace.path}")
            print("---")
            print(yaml.safe_dump(prometheus_rules))
            print()
