from collections.abc import Mapping
from typing import Self

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

    @classmethod
    def create(cls, secret_reader: SecretReaderBase) -> Self:
        return cls(
            secret_reader=secret_reader,
            dynatrace_client_by_tenant_id=_dynatrace_client_map(
                secret_reader=secret_reader
            ),
            ocm_client_by_env_name=_ocm_clients(secret_reader=secret_reader),
            token_spec_by_name=_token_specs(),
        )


def _token_specs() -> dict[str, DynatraceTokenProviderTokenSpecV1]:
    token_specs = get_dynatrace_token_provider_token_specs()
    return {spec.name: spec for spec in token_specs}


def _dynatrace_client_map(
    secret_reader: SecretReaderBase,
) -> dict[str, DynatraceClient]:
    dynatrace_client_by_tenant_id: dict[str, DynatraceClient] = {}
    dynatrace_environments = get_dynatrace_environments()
    if not dynatrace_environments:
        raise RuntimeError("No Dynatrace environment defined.")
    for tenant in dynatrace_environments:
        dt_api_token = secret_reader.read_secret(tenant.bootstrap_token)
        dt_client = DynatraceClient.create(
            environment_url=tenant.environment_url,
            token=dt_api_token,
            api=None,
        )
        tenant_id = tenant.environment_url.split(".")[0].removeprefix("https://")
        dynatrace_client_by_tenant_id[tenant_id] = dt_client
    return dynatrace_client_by_tenant_id


def _ocm_clients(secret_reader: SecretReaderBase) -> dict[str, OCMClient]:
    ocm_environments = get_ocm_environments()
    return {
        env.name: OCMClient(ocm_client=init_ocm_base_client(env, secret_reader))
        for env in ocm_environments
    }
