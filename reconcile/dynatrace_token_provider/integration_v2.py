from reconcile.dynatrace_token_provider.meta import QONTRACT_INTEGRATION
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)


class DynatraceTokenProviderIntegrationParamsV2(PydanticRunParams):
    ocm_organization_ids: set[str] | None = None


class DynatraceTokenProviderIntegrationV2(
    QontractReconcileIntegration[DynatraceTokenProviderIntegrationParamsV2]
):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        pass
