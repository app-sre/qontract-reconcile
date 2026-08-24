import os

import pytest
import yaml

from reconcile.utils.sloth import (
    SLO,
    SLODocument,
    SlothInputError,
    generate_sloth_rules,
)


def test_generate_sloth_rules_success() -> None:
    """Test generate_sloth_rules function with valid SLO document input"""
    # Sample SLO document with new format
    slo_document: SLODocument = {
        "name": "test-app",
        "app": {"name": "test-app"},
        "slos": [
            {
                "name": "Availability",
                "SLOTarget": 0.95,
                "SLOTargetUnit": "percent_0_1",
                "SLIErrorQuery": 'sum(rate(http_requests_total{status=~"5.."}[{{window}}]))',
                "SLITotalQuery": "sum(rate(http_requests_total{}[{{window}}]))",
                "SLIType": "events",
                "SLISpecification": "availability",
                "SLOParameters": {"window": "30d"},
                "SLODetails": "https://example.com/test-app/availability-runbook.md",
                "dashboard": "https://example.com/dashboard",
                "expr": "test-expr",
            },
            {
                "name": "Latency",
                "SLOTarget": 0.99,
                "SLOTargetUnit": "percent_0_1",
                "SLIErrorQuery": 'sum(rate(http_requests_latency_bucket{le="+Inf"}[{{window}}])) - sum(rate(http_requests_latency_bucket{le="1.0"}[{{window}}]))',
                "SLITotalQuery": "sum(rate(http_requests_latency_bucket{}[{{window}}]))",
                "SLIType": "events",
                "SLISpecification": "latency",
                "SLOParameters": {"window": "30d"},
                "SLODetails": "https://example.com/test-app/latency-runbook.md",
                "dashboard": "https://example.com/dashboard",
                "expr": "test-expr",
            },
        ],
    }

    fixture_dir = os.path.join(os.path.dirname(__file__), "../fixtures", "jinja2")
    expected_result_path = os.path.join(
        fixture_dir, "sloth_alerts_expected_result.yaml"
    )
    with open(expected_result_path, encoding="utf-8") as f:
        expected_result = f.read()

    result = generate_sloth_rules(slo_document)
    result_data = yaml.safe_load(result)
    expected_data = yaml.safe_load(expected_result)

    assert result_data == expected_data


def _alert_rules(rendered: str) -> list[dict]:
    """Return only the `alert` rules from rendered sloth output.

    Record rules keep sloth's own labels; routing labels like `env` only need to
    live on alert rules, so tests assert against alert rules specifically.
    """
    data = yaml.safe_load(rendered)
    return [
        rule
        for group in data.get("groups", [])
        for rule in group.get("rules", [])
        if rule.get("alert")
    ]


def test_generate_sloth_rules_injects_env_label() -> None:
    """When `env` is set, every generated alert rule carries the env label."""
    slo_document: SLODocument = {
        "name": "test-app",
        "env": "stage",
        "app": {"name": "test-app"},
        "slos": [
            {
                "name": "Availability",
                "SLOTarget": 0.95,
                "SLOTargetUnit": "percent_0_1",
                "SLIErrorQuery": 'sum(rate(http_requests_total{status=~"5.."}[{{window}}]))',
                "SLITotalQuery": "sum(rate(http_requests_total{}[{{window}}]))",
                "SLIType": "events",
                "SLISpecification": "availability",
                "SLOParameters": {"window": "30d"},
                "SLODetails": "https://example.com/test-app/availability-runbook.md",
                "dashboard": "https://example.com/dashboard",
                "expr": "test-expr",
            },
        ],
    }

    alert_rules = _alert_rules(generate_sloth_rules(slo_document))

    assert alert_rules  # sanity: multi-window alerts were generated
    assert all(rule["labels"].get("env") == "stage" for rule in alert_rules)


def test_generate_sloth_rules_omits_env_label_when_unset() -> None:
    """Backward compatibility: no env field means no env label on any rule."""
    slo_document: SLODocument = {
        "name": "test-app",
        "app": {"name": "test-app"},
        "slos": [
            {
                "name": "Availability",
                "SLOTarget": 0.95,
                "SLOTargetUnit": "percent_0_1",
                "SLIErrorQuery": 'sum(rate(http_requests_total{status=~"5.."}[{{window}}]))',
                "SLITotalQuery": "sum(rate(http_requests_total{}[{{window}}]))",
                "SLIType": "events",
                "SLISpecification": "availability",
                "SLOParameters": {"window": "30d"},
                "SLODetails": "https://example.com/test-app/availability-runbook.md",
                "dashboard": "https://example.com/dashboard",
                "expr": "test-expr",
            },
        ],
    }

    rendered = generate_sloth_rules(slo_document)
    data = yaml.safe_load(rendered)

    assert not any(
        "env" in rule.get("labels", {})
        for group in data.get("groups", [])
        for rule in group.get("rules", [])
    )


# A minimal, valid SLO that generates multi-window alert rules; the test below
# varies only the document-level `env`.
_VALID_SLO: SLO = {
    "name": "Availability",
    "SLOTarget": 0.95,
    "SLOTargetUnit": "percent_0_1",
    "SLIErrorQuery": 'sum(rate(http_requests_total{status=~"5.."}[{{window}}]))',
    "SLITotalQuery": "sum(rate(http_requests_total{}[{{window}}]))",
    "SLIType": "events",
    "SLISpecification": "availability",
    "SLOParameters": {"window": "30d"},
    "SLODetails": "https://example.com/test-app/availability-runbook.md",
    "dashboard": "https://example.com/dashboard",
    "expr": "test-expr",
}


@pytest.mark.parametrize("blank_env", ["", "   ", "\t", "\n"])
def test_generate_sloth_rules_rejects_blank_env(blank_env: str) -> None:
    """A present-but-blank `env` is invalid state and must be rejected.

    This test exposes the defect CodeRabbit flagged. Today an empty string is
    silently dropped and a whitespace-only string is emitted verbatim, so
    neither raises: the test FAILS against the current code. It passes only
    once generate_sloth_rules validates `env` (e.g. via `env.strip()`) and
    raises SlothInputError when the key is present but blank.
    """
    slo_document: SLODocument = {
        "name": "test-app",
        "env": blank_env,
        "app": {"name": "test-app"},
        "slos": [_VALID_SLO],
    }

    with pytest.raises(SlothInputError):
        generate_sloth_rules(slo_document)


def test_generate_sloth_rules_no_slos() -> None:
    """Test generate_sloth_rules raises SlothInputError when no SLOs defined"""
    slo_document: SLODocument = {
        "name": "test-app",
        "app": {"name": "test-app"},
    }

    with pytest.raises(SlothInputError, match="SLO document has no SLOs defined"):
        generate_sloth_rules(slo_document)


def test_generate_sloth_rules_empty_slos() -> None:
    """Test generate_sloth_rules raises SlothInputError when SLOs list is empty"""
    slo_document: SLODocument = {
        "name": "test-app",
        "app": {"name": "test-app"},
        "slos": [],
    }

    with pytest.raises(SlothInputError, match="SLO document has no SLOs defined"):
        generate_sloth_rules(slo_document)


def test_generate_sloth_rules_no_valid_slos() -> None:
    """Test generate_sloth_rules raises SlothInputError when no SLOs have required queries"""
    slo_document: SLODocument = {
        "name": "test-app",
        "app": {"name": "test-app"},
        "slos": [
            {
                "name": "Incomplete",
                "SLOTarget": 0.95,
                "SLOTargetUnit": "percent_0_1",
                # Missing SLIErrorQuery and SLITotalQuery
                "SLIType": "events",
                "SLISpecification": "availability",
                "SLOParameters": {"window": "30d"},
                "SLODetails": "test details",
                "dashboard": "https://example.com/dashboard",
                "expr": "test-expr",
            },
            {
                "name": "PartiallyComplete",
                "SLOTarget": 0.99,
                "SLOTargetUnit": "percent_0_1",
                "SLIErrorQuery": "some_query",
                # Missing SLITotalQuery
                "SLIType": "events",
                "SLISpecification": "latency",
                "SLOParameters": {"window": "30d"},
                "SLODetails": "test details",
                "dashboard": "https://example.com/dashboard",
                "expr": "test-expr",
            },
        ],
    }

    with pytest.raises(
        SlothInputError,
        match="No SLOs found with both SLIErrorQuery and SLITotalQuery defined",
    ):
        generate_sloth_rules(slo_document)
