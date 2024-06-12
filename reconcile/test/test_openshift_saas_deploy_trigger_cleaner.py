from datetime import UTC, datetime
from typing import Any

import pytest

from reconcile.gql_definitions.fragments.pipeline_provider_retention import (
    PipelineProviderRetention,
)
from reconcile.openshift_saas_deploy_trigger_cleaner import get_pipeline_runs_to_delete

from .fixtures import Fixtures

fxt = Fixtures("openshift_saas_deploy_trigger_cleaner")


@pytest.fixture
def now() -> datetime:
    return datetime(2024, 4, 4, 0, 0, 0, 0, tzinfo=UTC)


# A fixture simulating the output of getting PipelineRuns from a namespace, simplified
# as it contains only the fields relevant for get_pipeline_runs_to_delete, reversed
# sorted by creationTimestamp
@pytest.fixture
def pipeline_runs() -> list[dict[str, Any]]:
    return fxt.get_anymarkup("pipeline_runs.yaml")


# No min/max settings, we go with whatever "days" says
def test_days(now: datetime, pipeline_runs: list[dict[str, Any]]) -> None:
    retention = PipelineProviderRetention(days=1, minimum=None, maximum=None)
    assert len(get_pipeline_runs_to_delete(pipeline_runs, retention, now)) == 4

    retention = PipelineProviderRetention(days=2, minimum=None, maximum=None)
    assert len(get_pipeline_runs_to_delete(pipeline_runs, retention, now)) == 2


# Minimum set, it takes precedence over "days"
def test_days_and_minimum(now: datetime, pipeline_runs: list[dict[str, Any]]) -> None:
    retention = PipelineProviderRetention(days=1, minimum=5, maximum=None)
    assert len(get_pipeline_runs_to_delete(pipeline_runs, retention, now)) == 1
    # We would have removed four from the "days" setting, we can only remove one

    retention = PipelineProviderRetention(days=1, minimum=3, maximum=None)
    assert len(get_pipeline_runs_to_delete(pipeline_runs, retention, now)) == 3
    # We would have removed four from the "days" setting, we can only remove three

    retention = PipelineProviderRetention(days=1, minimum=1, maximum=None)
    assert len(get_pipeline_runs_to_delete(pipeline_runs, retention, now)) == 4
    # Removing 4 we still have two, we're fine.


# Maximum set, it takes precedence over "days"
def test_days_and_maximum(now: datetime, pipeline_runs: list[dict[str, Any]]) -> None:
    retention = PipelineProviderRetention(days=1, minimum=None, maximum=1)
    assert len(get_pipeline_runs_to_delete(pipeline_runs, retention, now)) == 5
    # we have a max of 1, no matter what "days" says.

    retention = PipelineProviderRetention(days=1, minimum=None, maximum=3)
    assert len(get_pipeline_runs_to_delete(pipeline_runs, retention, now)) == 4
    # by removing 4 we comply with the max setting of three.

    retention = PipelineProviderRetention(days=2, minimum=None, maximum=3)
    assert len(get_pipeline_runs_to_delete(pipeline_runs, retention, now)) == 3
    # We would have remove only two following "days", but max tells us otherwise.
