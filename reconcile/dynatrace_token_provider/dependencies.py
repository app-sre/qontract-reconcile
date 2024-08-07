from collections.abc import Mapping

from reconcile.dynatrace_token_provider.ocm import OCMClient
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)
from reconcile.typed_queries.dynatrace_environments import get_dynatrace_environments
from reconcile.typed_queries.dynatrace_token_provider_token_specs import (
    get_dynatrace_token_provider_token_specs,
)
from reconcile.typed_queries.ocm import get_ocm_environments
from reconcile.utils.dynatrace.client import DynatraceClient
from reconcile.utils.ocm_base_client import (
    init_ocm_base_client,
)
from reconcile.utils.secret_reader import SecretReaderBase


class Dependencies:
    """
    Depenedencies class to hold all the dependencies (API clients) for the Dynatrace Token Provider.
    Dependency inversion simplifies setting up tests.
    """

    def __init__(
        self,
        secret_reader: SecretReaderBase,
        dynatrace_client_by_tenant_id: Mapping[str, DynatraceClient],
        ocm_client_by_env_name: Mapping[str, OCMClient],
        token_spec_by_name: Mapping[str, DynatraceTokenProviderTokenSpecV1],
    ):
        self.secret_reader = secret_reader
        self.dynatrace_client_by_tenant_id: dict[str, DynatraceClient] = dict(
            dynatrace_client_by_tenant_id
        )
        self.ocm_client_by_env_name: dict[str, OCMClient] = dict(ocm_client_by_env_name)
        self.token_spec_by_name = dict(token_spec_by_name)

    def populate_all(self) -> None:
        self.populate_dynatrace_client_map()
        self.populate_ocm_clients()
        self.populate_token_specs()

    def populate_token_specs(self) -> None:
        token_specs = get_dynatrace_token_provider_token_specs()
        self.token_spec_by_name = {spec.name: spec for spec in token_specs}

    def populate_dynatrace_client_map(self) -> None:
        dynatrace_environments = get_dynatrace_environments()
        if not dynatrace_environments:
            raise RuntimeError("No Dynatrace environment defined.")
        for tenant in dynatrace_environments:
            dt_api_token = self.secret_reader.read_secret(tenant.bootstrap_token)
            dt_client = DynatraceClient.create(
                environment_url=tenant.environment_url,
                token=dt_api_token,
                api=None,
            )
            tenant_id = tenant.environment_url.split(".")[0].removeprefix("https://")
            self.dynatrace_client_by_tenant_id[tenant_id] = dt_client

    def populate_ocm_clients(self) -> None:
        ocm_environments = get_ocm_environments()
        self.ocm_client_by_env_name = {
            env.name: OCMClient(
                ocm_client=init_ocm_base_client(env, self.secret_reader)
            )
            for env in ocm_environments
        }
