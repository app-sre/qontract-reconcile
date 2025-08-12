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


def process_sloth_output(output_file_path: str) -> str:
    """Process sloth output to make it compliant with the prometheus-rule-1 schema"""
    cleaned_rule_spec = PrometheusRuleSpec(groups=[])
    with open(output_file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rule_spec = PrometheusRuleSpec(**data)
    for group in rule_spec.groups:
        cleaned_group = PrometheusRuleGroup(name=group.name, rules=[])
        for rule in group.rules:
            # sloth adds several labels/annotations that are invalid within our rule schema
            # see: https://sloth.dev/examples/default/getting-started/#__tabbed_1_2
            cleaned_rule = rule.copy(deep=True)
            if cleaned_rule.alert:
                if cleaned_rule.labels:
                    cleaned_labels = {
                        k: v
                        for k, v in cleaned_rule.labels.items()
                        if not k.startswith("sloth")
                    }
                    cleaned_rule.labels = cleaned_labels or None
                if cleaned_rule.annotations:
                    cleaned_annotations = {
                        k: v
                        for k, v in cleaned_rule.annotations.items()
                        if k != "title"
                    }
                    cleaned_rule.annotations = cleaned_annotations or None
            # recording rule
            else:
                cleaned_rule.labels = None
            cleaned_group.rules.append(cleaned_rule)
        cleaned_rule_spec.groups.append(cleaned_group)
    return yaml.safe_dump(cleaned_rule_spec.dict(exclude_none=True))
