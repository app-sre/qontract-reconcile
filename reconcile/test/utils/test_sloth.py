import os

import pytest
import yaml

from reconcile.utils.sloth import SLODocumentDict, SlothInputError, generate_sloth_rules


def test_generate_sloth_rules_success() -> None:
    """Test generate_sloth_rules function with valid SLO document input"""
    # Sample SLO document with new format
    slo_document: SLODocumentDict = {
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
                "SLODetails": "test details",
                "dashboard": "test-dashboard",
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
                "SLODetails": "test details",
                "dashboard": "test-dashboard",
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


def test_generate_sloth_rules_no_slos() -> None:
    """Test generate_sloth_rules raises SlothInputError when no SLOs defined"""
    slo_document: SLODocumentDict = {
        "name": "test-app",
        "app": {"name": "test-app"},
    }

    with pytest.raises(SlothInputError, match="SLO document has no SLOs defined"):
        generate_sloth_rules(slo_document)


def test_generate_sloth_rules_empty_slos() -> None:
    """Test generate_sloth_rules raises SlothInputError when SLOs list is empty"""
    slo_document: SLODocumentDict = {
        "name": "test-app",
        "app": {"name": "test-app"},
        "slos": [],
    }

    with pytest.raises(SlothInputError, match="SLO document has no SLOs defined"):
        generate_sloth_rules(slo_document)


def test_generate_sloth_rules_no_valid_slos() -> None:
    """Test generate_sloth_rules raises SlothInputError when no SLOs have required queries"""
    slo_document: SLODocumentDict = {
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
                "dashboard": "test-dashboard",
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
                "dashboard": "test-dashboard",
                "expr": "test-expr",
            },
        ],
    }

    with pytest.raises(
        SlothInputError,
        match="No SLOs found with both SLIErrorQuery and SLITotalQuery defined",
    ):
        generate_sloth_rules(slo_document)
