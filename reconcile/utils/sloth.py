import subprocess
import tempfile
from io import StringIO
from typing import Any, NotRequired, TypedDict

import yaml

from reconcile.utils.ruamel import create_ruamel_instance


class PrometheusRule(TypedDict):
    record: NotRequired[str]
    alert: NotRequired[str]
    expr: str
    labels: NotRequired[dict[str, str]]
    annotations: NotRequired[dict[str, str]]


class PrometheusRuleGroup(TypedDict):
    name: str
    rules: list[PrometheusRule]


class PrometheusRuleSpec(TypedDict):
    groups: list[PrometheusRuleGroup]


class SLOParametersDict(TypedDict):
    window: str


class SLO(TypedDict):
    name: str
    SLIType: str
    SLISpecification: str
    SLOTarget: float
    SLOTargetUnit: str
    SLOParameters: SLOParametersDict
    SLODetails: str
    dashboard: str
    expr: str
    SLIErrorQuery: NotRequired[str]
    SLITotalQuery: NotRequired[str]


class App(TypedDict):
    name: str


class SLODocument(TypedDict):
    name: str
    app: App
    slos: NotRequired[list[SLO]]


class SlothGenerateError(Exception):
    def __init__(self, msg: Any):
        super().__init__("sloth generate failed: " + str(msg))


class SlothInputError(Exception):
    def __init__(self, msg: Any):
        super().__init__("sloth input validation failed: " + str(msg))


def process_sloth_output(output_file_path: str) -> str:
    ruamel_instance = create_ruamel_instance()
    with open(output_file_path, encoding="utf-8") as f:
        data: PrometheusRuleSpec = ruamel_instance.load(f)
    for group in data.get("groups", []):
        for rule in group.get("rules", []):
            labels = (
                # sloth adds several sloth_* labels to alerting rules that are not compliant with prometheus-rule-1 schema
                # see https://sloth.dev/examples/default/getting-started/#__tabbed_1_2
                {k: v for k, v in rule["labels"].items() if not k.startswith("sloth")}
                if rule.get("alert")
                else rule["labels"]  # retain all labels on record rules
            )
            annotations = (
                # sloth adds a `title` key within annotations for alert rules: https://sloth.dev/examples/default/getting-started/#__tabbed_1_2
                # this is not compliant with schema and is discarded
                {k: v for k, v in rule["annotations"].items() if k != "title"}
                if rule.get("alert")
                else {}  # record rules do not support annotations
            )
            if labels:
                rule["labels"] = labels
            else:
                rule.pop("labels", None)
            if annotations:
                rule["annotations"] = annotations
            else:
                rule.pop("annotations", None)
    with StringIO() as s:
        ruamel_instance.dump(data, s)
        return s.getvalue()


def run_sloth(spec: dict[str, Any]) -> str:
    with (
        tempfile.NamedTemporaryFile(
            encoding="utf-8", mode="w", suffix=".yml"
        ) as input_file,
        tempfile.NamedTemporaryFile(
            encoding="utf-8", mode="w", suffix=".yml"
        ) as output_file,
    ):
        yaml.dump(spec, input_file, allow_unicode=True)
        cmd = ["sloth", "generate", "-i", input_file.name, "-o", output_file.name]
        try:
            subprocess.run(cmd, capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError as e:
            error_msg = f"{e}"
            if e.stdout:
                error_msg += f"\nstdout: {e.stdout}"
            if e.stderr:
                error_msg += f"\nstderr: {e.stderr}"
            raise SlothGenerateError(error_msg) from e
        return process_sloth_output(output_file.name)


def get_slo_target(slo: SLO) -> float:
    """
    Ensure SLO target unit aligns with format expected by sloth for 'Objective' attribute
    https://pkg.go.dev/github.com/slok/sloth/pkg/prometheus/api/v1#section-readme
    """
    val = float(slo["SLOTarget"])
    return val * (100.0 if slo.get("SLOTargetUnit") == "percent_0_1" else 1.0)


def generate_sloth_rules(
    slo_document: SLODocument,
    version: str = "prometheus/v1",
) -> str:
    """Generate Prometheus rules for an slo_document_v1 using sloth

    Args:
        slo_document query:
            {
                slo_docs: slo_document_v1(filter: {name: "foo"}) {
                    name
                    app {
                        name
                    }
                    slos {
                        name
                        SLIType
                        SLOTargetUnit
                        SLOParameters {
                            window
                        }
                        expr
                        SLOTarget
                        SLIErrorQuery
                        SLITotalQuery
                        SLODetails
                        dashboard
                    }
                }
            }
        version: Spec version (default: "prometheus/v1")

    Returns:
        Generated Prometheus rules as YAML string
    """
    if not slo_document.get("slos"):
        raise SlothInputError("SLO document has no SLOs defined")

    service = slo_document["app"]["name"]
    # only process SLOs that have both error and total queries defined
    slo_input = [
        {
            "name": slo["name"],
            "objective": get_slo_target(slo),
            "description": f"{slo['name']} SLO for {service}",
            "sli": {
                "events": {
                    "error_query": slo["SLIErrorQuery"].replace(
                        "{{window}}", "{{.window}}"
                    ),
                    "total_query": slo["SLITotalQuery"].replace(
                        "{{window}}", "{{.window}}"
                    ),
                }
            },
            "alerting": {
                "name": f"{service.title()}{slo['name'].title()}",
                "annotations": {
                    "summary": f"High error rate on {service} {slo['name']}",
                    "message": f"High error rate on {service} {slo['name']}",
                    "runbook": slo["SLODetails"],
                    "dashboard": slo["dashboard"],
                },
                "page_alert": {
                    "labels": {
                        "severity": "critical",
                        "service": service,
                        "slo": slo["name"],
                    }
                },
                "ticket_alert": {
                    "labels": {
                        "severity": "medium",
                        "service": service,
                        "slo": slo["name"],
                    }
                },
            },
        }
        for slo in slo_document["slos"]
        if slo.get("SLIErrorQuery") and slo.get("SLITotalQuery")
    ]

    if not slo_input:
        raise SlothInputError(
            "No SLOs found with both SLIErrorQuery and SLITotalQuery defined"
        )

    spec = {
        "version": version,
        "service": service,
        "slos": slo_input,
    }
    return run_sloth(spec)
