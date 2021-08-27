import os
import anymarkup
import pytest

from tools.app_interface_reporter import prometheus_metrics_to_job_history


def get_fixures_data(file_name):
    base_path = 'fixtures/app_interface_reporter'
    path = os.path.join(
        os.path.dirname(__file__),
        base_path,
        file_name
    )
    with open(path, 'r') as f:
        return f.read().strip()


@pytest.fixture
def metrics():
    return anymarkup.parse(
        get_fixures_data('metrics.yml'),
        force_types=None
    )


@pytest.fixture
def expected_job_history():
    return anymarkup.parse(
        get_fixures_data('expected_job_history.yml'),
        force_types=None
    )


class TestAppInterfaceReporter:
    @staticmethod
    def test_prometheus_metrics_to_job_history(metrics, expected_job_history):
        job_history = \
            prometheus_metrics_to_job_history(metrics, 'cluster_name')

        assert job_history == expected_job_history
