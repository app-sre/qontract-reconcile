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


def get_cleaned_rule_labels(rule: PrometheusRule) -> dict[str, str] | None:
    if rule.get("record") or not rule.get("labels"):
        return None
    # sloth adds several sloth_* labels to rules that are not compliant with prometheus-rule-1 schema
    # see https://sloth.dev/examples/default/getting-started/#__tabbed_1_2
    labels = {k: v for k, v in rule["labels"].items() if not k.startswith("sloth")}
    return labels or None


def get_cleaned_rule_annotations(rule: PrometheusRule) -> dict[str, str] | None:
    if rule.get("alert") and rule.get("annotations"):
        # sloth adds a `title` key within annotations: https://sloth.dev/examples/default/getting-started/#__tabbed_1_2
        # not supported within schema: https://github.com/app-sre/qontract-schemas/blob/main/schemas/openshift/prometheus-rule-1.yml#L165-L192
        annotations = {k: v for k, v in rule["annotations"].items() if k != "title"}
        return annotations or None
    return rule.get("annotations")


def process_sloth_output(output_file_path: str) -> str:
    ruamel_instance = create_ruamel_instance()
    with open(output_file_path, encoding="utf-8") as f:
        data: PrometheusRuleSpec = ruamel_instance.load(f)
    for group in data.get("groups", []):
        for rule in group.get("rules", []):
            cleaned_labels = get_cleaned_rule_labels(rule)
            cleaned_annotations = get_cleaned_rule_annotations(rule)
            if cleaned_labels is not None:
                rule["labels"] = cleaned_labels
            else:
                rule.pop("labels", None)
            if cleaned_annotations is not None:
                rule["annotations"] = cleaned_annotations
            else:
                rule.pop("annotations", None)

    with StringIO() as s:
        ruamel_instance.dump(data, s)
        return s.getvalue()
