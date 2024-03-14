from pydantic import BaseModel

from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.utils.clusterhealth.providerbase import ClusterHealthProvider


class AUSHealthError(BaseModel):
    source: str
    error: str
    enforce: bool


class AUSClusterHealth(BaseModel):
    state: dict[str, list[AUSHealthError]]

    def get_errors(self, only_enforced: bool = False) -> list[AUSHealthError]:
        return [
            e
            for errors in self.state.values()
            for e in errors
            if not only_enforced or e.enforce
        ]

    def has_health_errors(self, only_enforced: bool = False) -> bool:
        return bool(self.get_errors(only_enforced=only_enforced))

    def health_errors_by_source(
        self, only_enforced: bool = False
    ) -> dict[str, list[AUSHealthError]]:
        return {
            source: [e for e in errors if not only_enforced or e.enforce]
            for source, errors in self.state.items()
        }


class AUSClusterHealthCheckProvider:
    def __init__(self) -> None:
        self.providers: dict[str, tuple[ClusterHealthProvider, bool]] = {}

    def add_provider(
        self, name: str, provider: ClusterHealthProvider, enforce: bool
    ) -> "AUSClusterHealthCheckProvider":
        self.providers[name] = (provider, enforce)
        return self

    def cluster_health(self, cluster_external_id: str, org_id: str) -> AUSClusterHealth:
        state: dict[str, list[AUSHealthError]] = {}
        for provider_name in self.providers.keys():
            state[provider_name] = []
            provider, enforce = self.providers[provider_name]
            health = provider.cluster_health(cluster_external_id, org_id)
            for error in health.errors or {}:
                state[provider_name].append(
                    AUSHealthError(source=provider_name, error=error, enforce=enforce)
                )
        return AUSClusterHealth(state=state)


def build_cluster_health_providers_for_organization(
    org: AUSOCMOrganization,
    providers: dict[str, ClusterHealthProvider],
) -> AUSClusterHealthCheckProvider:
    provider = AUSClusterHealthCheckProvider()

    for health_check in org.aus_cluster_health_checks or []:
        if health_check.provider not in providers:
            raise Exception(
                f"organization {org.name} ({org.org_id}) requests health data "
                f"from an unavailable health check provider {health_check.provider}"
            )
        provider.add_provider(
            name=health_check.provider,
            provider=providers[health_check.provider],
            enforce=health_check.enforced,
        )

    return provider
