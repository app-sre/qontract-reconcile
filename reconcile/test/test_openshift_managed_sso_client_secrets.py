"""Tests for the managed-sso-client openshift-resource provider."""

from __future__ import annotations

import json
import warnings
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from qontract_utils.managed_sso_client import DEFAULT_OUTPUT_VAULT_PATH_PREFIX

import reconcile.openshift_resources_base as orb
from reconcile.gql_definitions.openshift_managed_sso_client_secret.namespaces import (
    AppV1,
    ClusterV1,
    DisableClusterAutomationsV1,
    ManagedSsoClientV1,
    NamespaceOpenshiftResourceManagedSsoClientV1,
    NamespaceOpenshiftResourceV1,
    NamespaceV1,
    SharedResourcesV1,
)
from reconcile.openshift_managed_sso_client_secrets import (
    OpenshiftManagedSsoClientSecretsIntegration,
    OpenshiftManagedSsoClientSecretsIntegrationParams,
)
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.secret_reader import SecretNotFoundError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _integration(**overrides: Any) -> OpenshiftManagedSsoClientSecretsIntegration:
    return OpenshiftManagedSsoClientSecretsIntegration(
        OpenshiftManagedSsoClientSecretsIntegrationParams(**overrides)
    )


def _client(
    name: str = "ci-bot", app_name: str = "my-app", output: str | None = None
) -> ManagedSsoClientV1:
    return ManagedSsoClientV1(
        name=name,
        app=AppV1(name=app_name),
        output=output,
    )


def _resource(
    client: ManagedSsoClientV1,
    name: str | None = None,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
) -> NamespaceOpenshiftResourceManagedSsoClientV1:
    return NamespaceOpenshiftResourceManagedSsoClientV1(
        provider="managed-sso-client",
        name=name,
        labels=json.dumps(labels) if labels is not None else None,
        annotations=json.dumps(annotations) if annotations is not None else None,
        managedSsoClient=client,
    )


def _other_resource(provider: str = "vault-secret") -> NamespaceOpenshiftResourceV1:
    """A namespace resource of some other provider - openshiftResources is
    heterogeneous (any provider a namespace declares), and GraphQL only
    resolves this integration's fragment fields for items that are actually
    NamespaceOpenshiftResourceManagedSsoClient_v1; other providers come back
    with none of those fields set.
    """
    return NamespaceOpenshiftResourceV1(provider=provider)


def _cluster(
    name: str = "cluster1", disable_integrations: list[str] | None = None
) -> ClusterV1:
    return ClusterV1(
        name=name,
        serverUrl="https://cluster1.example.com",
        insecureSkipTLSVerify=None,
        automationToken=None,
        clusterAdminAutomationToken=None,
        internal=None,
        disable=(
            DisableClusterAutomationsV1(integrations=disable_integrations)
            if disable_integrations is not None
            else None
        ),
    )


def _namespace(
    name: str = "ns1",
    cluster: ClusterV1 | None = None,
    delete: bool | None = None,
    resources: list[
        NamespaceOpenshiftResourceManagedSsoClientV1 | NamespaceOpenshiftResourceV1
    ]
    | None = None,
    shared_resources: list[
        NamespaceOpenshiftResourceManagedSsoClientV1 | NamespaceOpenshiftResourceV1
    ]
    | None = None,
) -> NamespaceV1:
    return NamespaceV1(
        name=name,
        delete=delete,
        clusterAdmin=None,
        openshiftResources=resources,
        sharedResources=(
            [
                # sharedResources.openshiftResources items are their own
                # (structurally identical but distinct) qenerate-generated
                # types, not NamespaceOpenshiftResource*V1 - re-validate via
                # dict round-trip instead of passing the instances directly.
                SharedResourcesV1(
                    openshiftResources=[
                        r.model_dump(by_alias=True) for r in shared_resources
                    ]
                )
            ]
            if shared_resources is not None
            else None
        ),
        cluster=cluster or _cluster(),
    )


#
# tenant_secret_vault_path
#


def test_tenant_secret_vault_path_uses_output_when_set() -> None:
    integration = _integration()
    client = _client(output="my-app/creds/ci-bot")

    assert integration.tenant_secret_vault_path(client) == "my-app/creds/ci-bot"


def test_tenant_secret_vault_path_uses_default_prefix_when_output_unset() -> None:
    integration = _integration()
    client = _client(name="CI-Bot", app_name="My-App", output=None)

    assert integration.tenant_secret_vault_path(client) == (
        f"{DEFAULT_OUTPUT_VAULT_PATH_PREFIX}/my-app-ci-bot"
    )


def test_tenant_secret_vault_path_uses_configured_prefix() -> None:
    integration = _integration(vault_path_prefix="custom/prefix")
    client = _client(name="ci-bot", app_name="my-app", output=None)

    assert integration.tenant_secret_vault_path(client) == "custom/prefix/my-app-ci-bot"


#
# construct_managed_sso_client_secret
#


def test_construct_secret_builds_correct_k8s_manifest() -> None:
    integration = _integration()
    client = _client()
    resource = _resource(client)
    secret_data = {
        "client_id": "my-app-ci-bot",
        "client_secret": "s3cr3t",
        "issuer": "https://sso.example.com/auth/realms/example-realm",
    }

    result = integration.construct_managed_sso_client_secret(
        resource, client, secret_data
    )

    assert result.body["apiVersion"] == "v1"
    assert result.body["kind"] == "Secret"
    assert result.body["type"] == "Opaque"
    assert result.body["metadata"]["name"] == "ci-bot"
    assert "labels" not in result.body["metadata"]
    assert "annotations" not in result.body["metadata"]
    # plaintext, not pre-base64-encoded - the apply/diff pipeline
    # (OpenshiftResource.canonicalize / three_way_diff_strategy) converts
    # stringData -> data for us.
    assert result.body["stringData"] == secret_data
    assert "data" not in result.body


def test_construct_secret_uses_resource_name_override() -> None:
    integration = _integration()
    client = _client(name="ci-bot")
    resource = _resource(client, name="custom-secret-name")

    result = integration.construct_managed_sso_client_secret(resource, client, {})

    assert result.body["metadata"]["name"] == "custom-secret-name"


def test_construct_secret_with_labels_and_annotations() -> None:
    integration = _integration()
    client = _client()
    resource = _resource(
        client,
        labels={"app": "my-app"},
        annotations={"description": "ci bot creds"},
    )

    result = integration.construct_managed_sso_client_secret(resource, client, {})

    assert result.body["metadata"]["labels"] == {"app": "my-app"}
    assert result.body["metadata"]["annotations"] == {"description": "ci bot creds"}


#
# get_namespaces
#


def _query_func(namespaces: list[NamespaceV1]) -> Any:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {"namespaces": [ns.model_dump(by_alias=True) for ns in namespaces]}

    return q


def test_get_namespaces_filters_deleted_namespaces() -> None:
    integration = _integration()
    client = _client()
    namespaces = [
        _namespace(name="kept", resources=[_resource(client)]),
        _namespace(name="deleted", delete=True, resources=[_resource(client)]),
    ]

    result = integration.get_namespaces(_query_func(namespaces))

    assert [ns.name for ns in result] == ["kept"]


def test_get_namespaces_filters_namespaces_without_resources() -> None:
    """Matches openshift_resources_base.canonicalize_namespaces' own
    `if ors and providers:` filter, and thus openshift-vault-secrets'
    behavior for the same scenario: a namespace without a current matching
    resource is out of scope entirely. Removing the last managed-sso-client
    resource can leave a stale Secret behind, uncleaned, until another
    resource is added back - the same known trade-off every other
    openshiftResources-based integration in this codebase accepts, rather
    than scanning every namespace on every enabled cluster unconditionally.
    """
    integration = _integration()
    namespaces = [
        _namespace(name="empty", resources=None),
    ]

    result = integration.get_namespaces(_query_func(namespaces))

    assert result == []


def test_get_namespaces_ignores_other_provider_resources() -> None:
    """openshiftResources is a NamespaceOpenshiftResource_v1 interface field -
    a namespace can freely mix a managed-sso-client resource with resources of
    any other provider (vault-secret, route, resource, ...). GraphQL only
    resolves this integration's fragment fields for items that are actually
    NamespaceOpenshiftResourceManagedSsoClient_v1; other providers come back
    with none of those fields, which used to make the whole query raise a
    pydantic ValidationError instead of the other-provider items simply being
    ignored - confirmed empirically against the raw generated models before
    fixing the .gql query to select `provider` plus a proper inline fragment.
    """
    integration = _integration()
    client = _client()
    ns = _namespace(
        name="mixed",
        resources=[_other_resource("vault-secret"), _resource(client)],
    )

    result = integration.get_namespaces(_query_func([ns]))

    assert [n.name for n in result] == ["mixed"]
    assert len(integration.managed_sso_client_resources(result[0])) == 1


def test_get_namespaces_filters_disabled_integration() -> None:
    integration = _integration()
    client = _client()
    namespaces = [
        _namespace(
            name="disabled",
            cluster=_cluster(disable_integrations=[integration.name]),
            resources=[_resource(client)],
        ),
    ]

    result = integration.get_namespaces(_query_func(namespaces))

    assert result == []


def test_get_namespaces_filters_by_cluster_name() -> None:
    integration = _integration(cluster_name=["cluster-a"])
    client = _client()
    namespaces = [
        _namespace(
            name="ns-a",
            cluster=_cluster(name="cluster-a"),
            resources=[_resource(client)],
        ),
        _namespace(
            name="ns-b",
            cluster=_cluster(name="cluster-b"),
            resources=[_resource(client)],
        ),
    ]

    result = integration.get_namespaces(_query_func(namespaces))

    assert [ns.name for ns in result] == ["ns-a"]


def test_get_namespaces_aggregates_shared_resources() -> None:
    """sharedResources.openshiftResources items are qenerate-generated as their
    own distinct (but structurally identical) types, not
    NamespaceOpenshiftResourceManagedSsoClientV1 - managed_sso_client_resources()
    must recognize items merged in from shared resources too, not just ones
    declared directly on the namespace.
    """
    integration = _integration()
    client = _client()
    namespaces = [
        _namespace(name="ns1", resources=None, shared_resources=[_resource(client)]),
    ]

    result = integration.get_namespaces(_query_func(namespaces))

    assert len(result) == 1
    assert result[0].openshift_resources is not None
    assert len(result[0].openshift_resources) == 1
    assert len(integration.managed_sso_client_resources(result[0])) == 1


#
# fetch_desired_state
#


def _ri_for(namespaces: list[NamespaceV1]) -> ResourceInventory:
    ri = ResourceInventory()
    for ns in namespaces:
        ri.initialize_resource_type(
            cluster=ns.cluster.name, namespace=ns.name, resource_type="Secret"
        )
    return ri


def test_fetch_desired_state_registers_error_on_duplicate_secret_name() -> None:
    """openshift_resources_base.fetch_desired_state has the identical
    ResourceKeyExistsError -> register_error handling for this same scenario
    (two resources resolving to the same Secret name) - without it,
    ri.add_desired_resource's raise propagates unhandled through run(),
    aborting the whole process instead of just the affected cluster.
    """
    integration = _integration()
    client = _client()
    ns = _namespace(resources=[_resource(client), _resource(client)])
    ri = _ri_for([ns])
    secret_reader = MagicMock()
    secret_reader.read_all.return_value = {"client_id": "my-app-ci-bot"}

    integration.fetch_desired_state([ns], ri, secret_reader, dry_run=False)

    assert ri.has_error_registered(cluster=ns.cluster.name)


def test_fetch_desired_state_adds_desired_resource_on_success() -> None:
    integration = _integration()
    client = _client()
    resource = _resource(client)
    ns = _namespace(resources=[resource])
    ri = _ri_for([ns])
    secret_reader = MagicMock()
    secret_reader.read_all.return_value = {
        "client_id": "my-app-ci-bot",
        "client_secret": "s3cr3t",
        "issuer": "https://sso.example.com/auth/realms/example-realm",
    }

    integration.fetch_desired_state([ns], ri, secret_reader, dry_run=False)

    desired = ri.get_desired(ns.cluster.name, ns.name, "Secret", "ci-bot")
    assert desired is not None
    assert not ri.has_error_registered()
    secret_reader.read_all.assert_called_once_with({
        "path": f"{DEFAULT_OUTPUT_VAULT_PATH_PREFIX}/my-app-ci-bot"
    })


def test_fetch_desired_state_skips_and_registers_error_when_secret_not_found_on_real_run() -> (
    None
):
    integration = _integration()
    client = _client()
    resource = _resource(client)
    ns = _namespace(resources=[resource])
    ri = _ri_for([ns])
    secret_reader = MagicMock()
    secret_reader.read_all.side_effect = SecretNotFoundError()

    integration.fetch_desired_state([ns], ri, secret_reader, dry_run=False)

    assert ri.get_desired(ns.cluster.name, ns.name, "Secret", "ci-bot") is None
    assert ri.has_error_registered(cluster=ns.cluster.name)


def test_fetch_desired_state_skips_without_error_when_secret_not_found_during_dry_run() -> (
    None
):
    """A brand-new managed-sso-client's Vault secret cannot exist before the
    app-interface MR declaring it is merged, so this integration's pr_check
    dry run would always hit SecretNotFoundError for an MR that adds a
    client and wires it into a namespace's openshiftResources together.
    Hard-failing here would make that MR's own CI gate permanently
    unpassable, so a dry run only warns - only a real run registers a hard
    error, where a still-missing secret is a meaningful signal to operators.
    """
    integration = _integration()
    client = _client()
    resource = _resource(client)
    ns = _namespace(resources=[resource])
    ri = _ri_for([ns])
    secret_reader = MagicMock()
    secret_reader.read_all.side_effect = SecretNotFoundError()

    integration.fetch_desired_state([ns], ri, secret_reader, dry_run=True)

    assert ri.get_desired(ns.cluster.name, ns.name, "Secret", "ci-bot") is None
    assert not ri.has_error_registered(cluster=ns.cluster.name)


#
# run
#


def test_run_overrides_orb_qontract_integration_globals(
    mocker: MockerFixture,
) -> None:
    """orb.fetch_current_state() stamps its own module-level QONTRACT_INTEGRATION/
    VERSION globals onto every fetched current-state object as that object's
    "owning integration" identity. Without overriding them to this
    integration's own name/version first, should_delete()'s
    has_qontract_annotations() check would never match this integration's own
    previously-applied secrets (it would compare against
    openshift_resources_base's own default name instead), and this
    integration could never clean up its own now-obsolete secrets.
    """
    integration = _integration()
    client = _client()
    ns = _namespace(resources=[_resource(client)])

    mocker.patch(
        "reconcile.openshift_managed_sso_client_secrets.gql.get_api",
        return_value=MagicMock(query=MagicMock()),
    )
    mocker.patch.object(integration, "get_namespaces", return_value=[ns])
    mocker.patch.object(integration, "fetch_desired_state")
    mocker.patch(
        "reconcile.openshift_managed_sso_client_secrets.init_oc_map_from_namespaces",
        return_value=MagicMock(),
    )
    mocker.patch(
        "reconcile.openshift_managed_sso_client_secrets.ob.init_specs_to_fetch",
        return_value=[],
    )
    mocker.patch("reconcile.openshift_managed_sso_client_secrets.ob.realize_data")
    mocker.patch("reconcile.openshift_managed_sso_client_secrets.ob.publish_metrics")
    mocker.patch.object(
        OpenshiftManagedSsoClientSecretsIntegration,
        "secret_reader",
        new_callable=mocker.PropertyMock,
        return_value=MagicMock(),
    )

    integration.run(dry_run=True)

    assert integration.name == orb.QONTRACT_INTEGRATION
    assert integration.integration_version == orb.QONTRACT_INTEGRATION_VERSION


#
# get_early_exit_desired_state / get_desired_state_shard_config
#


def test_early_exit_state_shape_matches_shard_selector(mocker: MockerFixture) -> None:
    """get_early_exit_desired_state()'s shape must actually match the jsonpath
    selector declared in get_desired_state_shard_config() - the runtime uses
    jsonpath_ng to find shard identifiers in exactly this returned object
    (reconcile/utils/runtime/desired_state_diff.py). A mismatch doesn't raise -
    jsonpath_ng silently swallows it - it just makes sharded PR-check dry runs
    always fall back to a full unsharded run instead of scoping to affected
    clusters.
    """
    from jsonpath_ng.ext.parser import parse

    integration = _integration()
    client = _client()
    ns = _namespace(
        name="ns1", cluster=_cluster(name="cluster-a"), resources=[_resource(client)]
    )
    mocker.patch.object(integration, "get_namespaces", return_value=[ns])
    mocker.patch(
        "reconcile.openshift_managed_sso_client_secrets.gql.get_api",
        return_value=MagicMock(query=MagicMock()),
    )

    state = integration.get_early_exit_desired_state()

    shard_config = integration.get_desired_state_shard_config()
    (selector,) = shard_config.shard_path_selectors
    matches = [m.value for m in parse(selector).find(state)]

    assert matches == ["cluster-a"]


def test_early_exit_state_ignores_shared_resources_serialization_warning(
    mocker: MockerFixture,
) -> None:
    """aggregate_shared_resources_typed() merges sharedResources items into
    openshiftResources as their own (structurally identical) qenerate-generated
    classes per query path, not the top-level Union members declared on
    NamespaceV1.openshift_resources - pydantic's serializer still dumps them
    correctly via its duck-typed fallback (verified: all fields present either
    way), but warns about the type mismatch on every model_dump(), observed as
    a real UserWarning in a running instance of this integration.
    model_dump(warnings=False) suppresses the noise without affecting the data.
    """
    integration = _integration()
    client = _client()
    ns = _namespace(
        name="ns1",
        resources=None,
        shared_resources=[_other_resource("vault-secret"), _resource(client)],
    )
    mocker.patch(
        "reconcile.openshift_managed_sso_client_secrets.gql.get_api",
        return_value=MagicMock(query=_query_func([ns])),
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        state = integration.get_early_exit_desired_state()

    assert state is not None


def test_shard_config_marks_cluster_name_as_collection() -> None:
    """cluster_name is list[str] | None - without shard_arg_is_collection=True,
    a sharded run degrades it to a bare string (pydantic's model_copy(update=...)
    does not coerce/validate), turning get_namespaces()'s `in` check from list
    membership into substring containment.
    """
    integration = _integration()

    assert integration.get_desired_state_shard_config().shard_arg_is_collection is True
