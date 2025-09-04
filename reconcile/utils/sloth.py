from io import StringIO
from typing import NotRequired, TypedDict

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
