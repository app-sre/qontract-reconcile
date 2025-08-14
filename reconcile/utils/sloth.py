from typing import Any

import yaml
from pydantic import BaseModel


class PrometheusRule(BaseModel):
    record: str | None = None
    alert: str | None = None
    expr: str
    labels: dict[str, str] | None = None
    annotations: dict[str, str] | None = None


class PrometheusRuleGroup(BaseModel):
    name: str
    rules: list[PrometheusRule]


class PrometheusRuleSpec(BaseModel):
    groups: list[PrometheusRuleGroup]


def get_cleaned_rule_labels(rule: PrometheusRule) -> dict[str, str] | None:
    if rule.record or not rule.labels:
        return None
    # sloth adds several sloth_* labels to rules that are not compliant with prometheus-rule-1 schema
    # see https://sloth.dev/examples/default/getting-started/#__tabbed_1_2
    labels = {k: v for k, v in rule.labels.items() if not k.startswith("sloth")}
    return labels or None


def get_cleaned_rule_annotations(rule: PrometheusRule) -> dict[str, str] | None:
    if rule.alert and rule.annotations:
        # sloth adds a `title` key within annotations: https://sloth.dev/examples/default/getting-started/#__tabbed_1_2
        # not supported within schema: https://github.com/app-sre/qontract-schemas/blob/main/schemas/openshift/prometheus-rule-1.yml#L165-L192
        annotations = {k: v for k, v in rule.annotations.items() if k != "title"}
        return annotations or None
    return rule.annotations


def get_cleaned_rule(rule: PrometheusRule) -> PrometheusRule:
    return PrometheusRule(
        record=rule.record,
        alert=rule.alert,
        expr=rule.expr,
        labels=get_cleaned_rule_labels(rule),
        annotations=get_cleaned_rule_annotations(rule),
    )


def process_sloth_output(output_file_path: str) -> str:
    with open(output_file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rule_spec = PrometheusRuleSpec.parse_obj(data)
    cleaned_rule_spec = PrometheusRuleSpec(
        groups=[
            PrometheusRuleGroup(
                name=group.name,
                rules=[get_cleaned_rule(r) for r in group.rules],
            )
            for group in rule_spec.groups
        ]
    )

    # Custom yaml dump to format multi-line strings as literal block scalars
    class LiteralDumper(yaml.SafeDumper):
        def represent_str(self, data: str) -> Any:
            if "\n" in data:
                return self.represent_scalar("tag:yaml.org,2002:str", data, style="|")
            return self.represent_scalar("tag:yaml.org,2002:str", data)

    LiteralDumper.add_representer(str, LiteralDumper.represent_str)
    return yaml.dump(
        cleaned_rule_spec.dict(exclude_none=True),
        Dumper=LiteralDumper,
        default_flow_style=False,
        allow_unicode=True,
    )
