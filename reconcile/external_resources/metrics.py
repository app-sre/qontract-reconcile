from pydantic import BaseModel

from reconcile.external_resources.meta import QONTRACT_INTEGRATION
from reconcile.external_resources.model import Reconciliation, ReconciliationStatus
from reconcile.external_resources.reconciler import ReconciliationK8sJob
from reconcile.utils import metrics
from reconcile.utils.external_resources import ExternalResourceSpec
from reconcile.utils.metrics import (
    CounterMetric,
    GaugeMetric,
    normalize_integration_name,
)


class ExternalResourcesBaseMetric(BaseModel):
    integration = normalize_integration_name(QONTRACT_INTEGRATION)
    app: str
    environment: str
    provision_provider: str
    provisioner_name: str
    provider: str
    identifier: str
    job_name: str


class ExternalResourcesReconciliationsCounter(
    ExternalResourcesBaseMetric, CounterMetric
):
    @classmethod
    def name(cls) -> str:
        return "external_resources_reconciliations"


class ExternalResourcesReconcileErrorsCounter(
    ExternalResourcesBaseMetric, CounterMetric
):
    @classmethod
    def name(cls) -> str:
        return "external_resources_reconcile_errors"


class ExternalResourcesReconcileTimeGauge(ExternalResourcesBaseMetric, GaugeMetric):
    @classmethod
    def name(cls) -> str:
        return "external_resources_reconcile_time"


class ExternalResourcesResourceStatus(ExternalResourcesBaseMetric, GaugeMetric):
    status: str

    @classmethod
    def name(cls) -> str:
        return "external_resources_resource_status"


def publish_metrics(
    r: Reconciliation,
    spec: ExternalResourceSpec,
    reconciliation_status: ReconciliationStatus,
    is_reconciled: bool,
) -> None:
    job_name = ReconciliationK8sJob(reconciliation=r).name()

    # Use transactional_metrics to remove old status, we just want to expose the latest status
    with metrics.transactional_metrics(scope=job_name) as metrics_container:
        metrics_container.set_gauge(
            ExternalResourcesResourceStatus(
                app=spec.namespace["app"]["name"],
                environment=spec.namespace["environment"]["name"],
                provision_provider=r.key.provision_provider,
                provisioner_name=r.key.provisioner_name,
                provider=r.key.provider,
                identifier=r.key.identifier,
                job_name=job_name,
                status=reconciliation_status.resource_status,
            ),
            1,
        )

    metrics.set_gauge(
        ExternalResourcesReconcileTimeGauge(
            app=spec.namespace["app"]["name"],
            environment=spec.namespace["environment"]["name"],
            provision_provider=r.key.provision_provider,
            provisioner_name=r.key.provisioner_name,
            provider=r.key.provider,
            identifier=r.key.identifier,
            job_name=job_name,
        ),
        reconciliation_status.reconcile_time,
    )

    if reconciliation_status.resource_status.has_errors:
        metrics.inc_counter(
            ExternalResourcesReconcileErrorsCounter(
                app=spec.namespace["app"]["name"],
                environment=spec.namespace["environment"]["name"],
                provision_provider=r.key.provision_provider,
                provisioner_name=r.key.provisioner_name,
                provider=r.key.provider,
                identifier=r.key.identifier,
                job_name=job_name,
            )
        )

    if is_reconciled:
        metrics.inc_counter(
            ExternalResourcesReconciliationsCounter(
                app=spec.namespace["app"]["name"],
                environment=spec.namespace["environment"]["name"],
                provision_provider=r.key.provision_provider,
                provisioner_name=r.key.provisioner_name,
                provider=r.key.provider,
                identifier=r.key.identifier,
                job_name=job_name,
            )
        )
