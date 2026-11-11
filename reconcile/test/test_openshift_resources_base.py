from __future__ import annotations

import copy
from typing import (
    TYPE_CHECKING,
    Any,
)
from unittest.mock import (
    MagicMock,
    Mock,
)

import pytest
from kubernetes.dynamic import Resource

from reconcile import openshift_resources_base as orb
from reconcile import query_validator, resource_template_tester
from reconcile.gql_definitions.openshift_resources.settings import (
    AppInterfaceSettingsV1,
)
from reconcile.openshift_base import CurrentStateSpec
from reconcile.openshift_resources_base import (
    CheckClusterScopedResourceDuplicates,
    CheckError,
    SecretKeyFormatError,
    canonicalize_namespaces,
    ob,
)
from reconcile.test.fixtures import Fixtures
from reconcile.utils import oc
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pytest_mock import MockerFixture

fxt = Fixtures("namespaces")
REPO_URL = "https://git.example.com/app-interface"


@pytest.fixture
def resource_settings() -> AppInterfaceSettingsV1:
    return AppInterfaceSettingsV1(repoUrl=REPO_URL, vault=True)


@pytest.fixture
def vault_resource() -> dict[str, str | None]:
    return {
        "provider": "vault-secret",
        "path": "example/secret",
        "version": "1",
        "name": "example",
        "labels": None,
        "annotations": None,
        "type": "Opaque",
    }


def test_vault_resources_use_supplied_reader(
    secret_reader: MagicMock, vault_resource: Mapping[str, str | None]
) -> None:
    secret_reader.read_all.return_value = {"key": "value"}

    for _ in range(2):
        resource = orb.fetch_openshift_resource(
            resource=vault_resource,
            parent={},
            repo_url=REPO_URL,
            secret_reader=secret_reader,
        )
        assert resource.body["data"] == {"key": "dmFsdWU="}

    assert secret_reader.read_all.call_count == 2
    secret_reader.read_all.assert_called_with({
        "path": "example/secret",
        "version": "1",
    })


@pytest.mark.parametrize(
    ("provider", "template_type", "expression"),
    [
        ("resource-template", "jinja2", '{{ vault("example", "key") }}'),
        ("resource-template", "extracurlyjinja2", '{{{ vault("example", "key") }}}'),
        (
            "prometheus-rule",
            "resource-template-jinja2",
            '{{ vault("example", "key") }}',
        ),
        (
            "prometheus-rule",
            "resource-template-extracurlyjinja2",
            '{{{ vault("example", "key") }}}',
        ),
    ],
)
def test_resource_templates_use_supplied_reader(
    secret_reader: MagicMock, provider: str, template_type: str, expression: str
) -> None:
    secret_reader.read_all.return_value = {"key": "rendered"}

    resource = orb.fetch_openshift_resource(
        resource={
            "provider": provider,
            "type": template_type,
            "variables": None,
            "resource": {
                "path": "/template.yaml",
                "content": f"kind: ConfigMap\nmetadata:\n  name: example\ndata:\n  key: {expression}\n",
            },
        },
        parent={},
        repo_url=REPO_URL,
        secret_reader=secret_reader,
    )

    assert resource.body["data"] == {"key": "rendered"}
    secret_reader.read_all.assert_called_once_with({
        "path": "example",
        "field": "",
        "version": None,
    })


@pytest.mark.parametrize(
    ("tls_path", "tls_version"),
    [(None, None), (None, "1"), ("example/tls", None), ("example/tls", "1")],
)
def test_routes_use_supplied_reader_only_for_versioned_tls(
    secret_reader: MagicMock, tls_path: str | None, tls_version: str | None
) -> None:
    secret_reader.read_all.return_value = {"termination": "edge", "key": "tls-key"}

    resource = orb.fetch_openshift_resource(
        resource={
            "provider": "route",
            "resource": {
                "path": "/route.yaml",
                "content": "kind: Route\nmetadata:\n  name: example\nspec:\n  to:\n    kind: Service\n    name: example\n",
            },
            "vault_tls_secret_path": tls_path,
            "vault_tls_secret_version": tls_version,
        },
        parent={},
        repo_url=REPO_URL,
        secret_reader=secret_reader,
    )

    if tls_path is not None and tls_version is not None:
        assert resource.body["spec"]["tls"] == {
            "termination": "edge",
            "key": "tls-key",
        }
        secret_reader.read_all.assert_called_once_with({
            "path": tls_path,
            "version": tls_version,
        })
    else:
        assert "tls" not in resource.body["spec"]
        secret_reader.read_all.assert_not_called()


def test_fetch_data_shares_supplied_reader_with_clients_and_workers(
    mocker: MockerFixture, secret_reader: MagicMock
) -> None:
    oc_map = mocker.patch.object(orb, "OC_Map", autospec=True)
    mocker.patch.object(ob, "init_specs_to_fetch", return_value=[])
    fetch = mocker.patch.object(orb.threaded, "run")

    result, _ = orb.fetch_data(
        namespaces=[],
        thread_pool_size=2,
        internal=None,
        cache=orb.Jinja2TemplateCache(),
        repo_url=REPO_URL,
        secret_reader=secret_reader,
    )

    assert result is oc_map.return_value
    assert oc_map.call_args.kwargs["secret_reader"] is secret_reader
    assert fetch.call_args.kwargs["secret_reader"] is secret_reader
    assert fetch.call_args.kwargs["repo_url"] == REPO_URL


@pytest.mark.parametrize("dry_run", [True, False])
def test_run_creates_reader_at_boundary(
    mocker: MockerFixture,
    secret_reader: MagicMock,
    resource_settings: AppInterfaceSettingsV1,
    dry_run: bool,
) -> None:
    mocker.patch.object(orb, "QONTRACT_INTEGRATION", "openshift-vault-secrets")
    mocker.patch.object(orb, "get_namespaces", return_value=([{}], None))
    mocker.patch.object(
        orb,
        "get_openshift_resources_settings",
        return_value=resource_settings,
    )
    create_reader = mocker.patch.object(
        orb, "create_secret_reader", return_value=secret_reader
    )
    oc_map = mocker.create_autospec(oc.OC_Map, instance=True)
    ri = ResourceInventory()
    fetch = mocker.patch.object(orb, "fetch_data", return_value=(oc_map, ri))
    mocker.patch.object(ob, "publish_metrics")
    realize = mocker.patch.object(ob, "realize_data")

    assert orb.run(dry_run=dry_run, thread_pool_size=2) is ri

    create_reader.assert_called_once_with(use_vault=True)
    assert fetch.call_args.kwargs["secret_reader"] is secret_reader
    assert fetch.call_args.kwargs["repo_url"] == REPO_URL
    realize.assert_called_once_with(dry_run, oc_map, ri, 2)


def test_early_exit_templates_do_not_read_secrets(secret_reader: MagicMock) -> None:
    resource = {
        "provider": "resource-template",
        "type": "jinja2",
        "variables": None,
        "enable_query_support": True,
        "resource": {
            "path": "/template.yaml",
            "content": 'kind: ConfigMap\nmetadata:\n  name: example\ndata:\n  key: {{ vault("example", "key") }}\n',
        },
    }

    with orb.early_exit_monkey_patch():
        result = orb._early_exit_fetch_resource(
            spec=(resource, {"name": "namespace", "cluster": {"name": "cluster"}}),
            repo_url=REPO_URL,
            secret_reader=secret_reader,
        )

    assert result["cluster"] == "cluster"
    secret_reader.read_all.assert_not_called()


def test_desired_state_uses_supplied_reader(
    oc_cs1: oc.OCClient,
    secret_reader: MagicMock,
    vault_resource: Mapping[str, str | None],
) -> None:
    secret_reader.read_all.return_value = {"key": "value"}
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Secret")

    orb.fetch_states(
        spec=ob.DesiredStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            resource=vault_resource,
            parent={},
        ),
        ri=ri,
        cache=orb.Jinja2TemplateCache(),
        repo_url=REPO_URL,
        secret_reader=secret_reader,
    )

    _, _, _, resources = next(iter(ri))
    assert resources["desired"]["example"].body["data"] == {"key": "dmFsdWU="}
    secret_reader.read_all.assert_called_once_with({
        "path": "example/secret",
        "version": "1",
    })


@pytest.mark.parametrize(
    ("provider", "resource_type"),
    [
        ("resource", None),
        ("resource-template", "jinja2"),
        ("resource-template", "extracurlyjinja2"),
        ("prometheus-rule", "resource"),
        ("prometheus-rule", "resource-template-jinja2"),
        ("prometheus-rule", "resource-template-extracurlyjinja2"),
    ],
)
@pytest.mark.parametrize(
    ("skip_validation", "add_path"), [(False, True), (False, False), (True, True)]
)
def test_prometheus_annotations_use_supplied_repo_without_queries(
    mocker: MockerFixture,
    secret_reader: MagicMock,
    provider: str,
    resource_type: str | None,
    skip_validation: bool,
    add_path: bool,
) -> None:
    mocker.patch.object(
        orb.gql, "get_api", side_effect=AssertionError("Unexpected GraphQL lookup")
    )
    content = """kind: PrometheusRule
metadata:
  name: example
spec:
  groups:
  - name: example
    rules:
    - alert: Example
      expr: vector(1)
      labels:
        service: example
      annotations:
        summary: Example
"""
    resource = orb.fetch_openshift_resource(
        resource={
            "provider": provider,
            "type": resource_type,
            "variables": None,
            "add_path_to_prom_rules": add_path,
            "resource": {"path": "/rule.yaml", "content": content},
        },
        parent={},
        repo_url=REPO_URL,
        secret_reader=secret_reader,
        skip_validation=skip_validation,
    )

    if skip_validation:
        assert str(resource.body).rstrip("\n") == content.rstrip("\n")
        return

    rule = resource.body["spec"]["groups"][0]["rules"][0]
    assert rule["labels"] == {"service": "example"}
    if add_path:
        assert rule["annotations"] == {
            "summary": "Example",
            "html_url": f"{REPO_URL}/blob/master/resources/rule.yaml",
        }
    else:
        assert rule["annotations"] == {"summary": "Example"}


def test_query_validator_supplies_resource_dependencies(
    mocker: MockerFixture,
    secret_reader: MagicMock,
    resource_settings: AppInterfaceSettingsV1,
) -> None:
    api = mocker.patch.object(query_validator.gql, "get_api").return_value
    api.query.return_value = {
        "validations": [{"name": "example", "resources": [{}, {}]}]
    }
    settings = mocker.patch.object(
        query_validator,
        "get_openshift_resources_settings",
        return_value=resource_settings,
    )
    create_reader = mocker.patch.object(
        query_validator, "create_secret_reader", return_value=secret_reader
    )
    fetch = mocker.patch.object(query_validator, "fetch_openshift_resource")

    query_validator.run(dry_run=True)

    settings.assert_called_once_with()
    create_reader.assert_called_once_with(use_vault=True)
    assert fetch.call_count == 2
    for call in fetch.call_args_list:
        assert call.kwargs["repo_url"] == REPO_URL
        assert call.kwargs["secret_reader"] is secret_reader
        assert call.kwargs["skip_validation"] is True
        assert "settings" not in call.kwargs


def test_template_tester_supplies_resource_dependencies(
    mocker: MockerFixture,
    secret_reader: MagicMock,
    resource_settings: AppInterfaceSettingsV1,
) -> None:
    api = mocker.patch.object(resource_template_tester.gql, "get_api").return_value
    namespace = {"openshiftResources": [{"resource": {"path": "/template.yaml"}}]}
    api.query.side_effect = [
        {
            "tests": [
                {
                    "name": "example",
                    "resourcePath": "/template.yaml",
                    "expectedResult": "/expected.yaml",
                }
            ]
            * 2
        },
        {"namespaces": [namespace]},
        {"namespaces": [namespace]},
    ]
    settings = mocker.patch.object(
        resource_template_tester,
        "get_openshift_resources_settings",
        return_value=resource_settings,
    )
    create_reader = mocker.patch.object(
        resource_template_tester, "create_secret_reader", return_value=secret_reader
    )
    mocker.patch.object(ob, "aggregate_shared_resources")
    mocker.patch.object(
        resource_template_tester, "load_resource", return_value={"key": "value"}
    )
    fetch = mocker.patch.object(orb, "fetch_openshift_resource")
    fetch.return_value.body = {"key": "value"}

    resource_template_tester.run(dry_run=True)

    settings.assert_called_once_with()
    create_reader.assert_called_once_with(use_vault=True)
    assert fetch.call_count == 2
    for call in fetch.call_args_list:
        assert call.kwargs["repo_url"] == REPO_URL
        assert call.kwargs["secret_reader"] is secret_reader
        assert "settings" not in call.kwargs


@pytest.fixture
def namespaces() -> list[dict[str, Any]]:
    return [fxt.get_anymarkup("openshift-resources-only.yml")]


@pytest.fixture
def oc_cs1(mocker: MockerFixture) -> oc.OCClient:
    client = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    client.init_api_resources = True
    client.api_resources = {
        "Template": ["template.openshift.io/v1"],
        "Subscription": ["apps.open-cluster-management.io/v1", "operators.coreos.com"],
    }
    client.get_items.return_value = []
    return client


@pytest.fixture
def tmpl1() -> dict[str, Any]:
    return {
        "kind": "Template",
        "apiVersion": "template.openshift.io/v1",
        "metadata": {"name": "tmpl1"},
    }


@pytest.fixture
def current_state_spec(oc_cs1: oc.OCNative) -> CurrentStateSpec:
    return CurrentStateSpec(
        oc=oc_cs1, cluster="cs1", namespace="ns1", kind="Template", resource_names=None
    )


def test_secret(namespaces: list[dict[str, Any]], mocker: MockerFixture) -> None:
    mocker.patch.object(ob, "aggregate_shared_resources", autospec=True)
    expected = (
        [
            {
                "name": "ns1",
                "cluster": {"name": "cs1"},
                "managedResourceTypes": ["Template"],
                "openshiftResources": [
                    {
                        "provider": "vault-secret",
                        "path": "/secret/place.yml",
                    }
                ],
            }
        ],
        ["Secret"],
    )

    ns, override = canonicalize_namespaces(namespaces, ["vault-secret"])
    assert (ns, override) == expected


def test_route(namespaces: list[dict[str, Any]], mocker: MockerFixture) -> None:
    mocker.patch.object(ob, "aggregate_shared_resources", autospec=True)
    expected = (
        [
            {
                "name": "ns1",
                "cluster": {"name": "cs1"},
                "managedResourceTypes": ["Template"],
                "openshiftResources": [
                    {"provider": "route", "path": "/route/network.yml"}
                ],
            }
        ],
        ["Route"],
    )
    ns, override = canonicalize_namespaces(namespaces, ["route"])
    assert (ns, override) == expected


def test_prometheus_rule(
    namespaces: list[dict[str, Any]], mocker: MockerFixture
) -> None:
    mocker.patch.object(ob, "aggregate_shared_resources", autospec=True)
    _, override = canonicalize_namespaces(namespaces, ["prometheus-rule"])
    assert override == [
        "PrometheusRule.monitoring.coreos.com",
        "PrometheusRule.monitoring.rhobs",
    ]


def test_no_overrides(namespaces: list[dict[str, Any]], mocker: MockerFixture) -> None:
    mocker.patch.object(ob, "aggregate_shared_resources", autospec=True)
    expected = (
        [
            {
                "name": "ns1",
                "cluster": {"name": "cs1"},
                "managedResourceTypes": ["Template"],
                "openshiftResources": [
                    {"provider": "resource", "path": "/some/path.yml"}
                ],
            }
        ],
        None,
    )

    ns, override = canonicalize_namespaces(namespaces, ["resource"])
    assert (ns, override) == expected


@pytest.fixture
def test_fetch_current_state_ri_not_initialized(
    oc_cs1: MagicMock, tmpl1: dict[str, Any]
) -> None:
    ri = ResourceInventory()
    oc_cs1.get_items.return_value = [tmpl1]
    ri.initialize_resource_type("cs1", "wrong_namespace", "Template")
    ri.initialize_resource_type("wrong_cluster", "ns1", "Template")
    ri.initialize_resource_type("cs1", "ns1", "wrong_kind")
    with pytest.raises(KeyError):
        orb.fetch_current_state(
            oc=oc_cs1,
            ri=ri,
            cluster="cs1",
            namespace="ns1",
            kind="Template",
            resource_names=[],
        )

    for _, _, _, resource in ri:
        assert len(resource["current"]) == 0


def test_fetch_current_state_ri_initialized(
    oc_cs1: MagicMock, tmpl1: dict[str, Any]
) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Template")
    oc_cs1.get_items.return_value = [tmpl1]
    orb.fetch_current_state(
        oc=oc_cs1,
        ri=ri,
        cluster="cs1",
        namespace="ns1",
        kind="Template",
        resource_names=[],
    )

    _, _, _, resource = next(iter(ri))
    assert len(resource["current"]) == 1
    assert "tmpl1" in resource["current"]
    assert resource["current"]["tmpl1"].kind == "Template"


@pytest.fixture
def test_fetch_current_state_kind_not_supported(
    oc_cs1: MagicMock, tmpl1: dict[str, Any]
) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "AnUnsupportedKind")
    oc_cs1.get_items.return_value = [tmpl1]
    orb.fetch_current_state(
        oc=oc_cs1,
        ri=ri,
        cluster="cs1",
        namespace="ns1",
        kind="AnUnsupportedKind",
        resource_names=[],
    )

    _, _, _, resource = next(iter(ri))
    assert len(resource["current"]) == 0


def test_fetch_current_state_long_kind(
    oc_cs1: MagicMock, tmpl1: dict[str, Any]
) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Template.template.openshift.io")
    oc_cs1.get_items.return_value = [tmpl1]
    orb.fetch_current_state(
        oc=oc_cs1,
        ri=ri,
        cluster="cs1",
        namespace="ns1",
        kind="Template.template.openshift.io",
        resource_names=[],
    )

    _, _, _, resource = next(iter(ri))
    assert len(resource["current"]) == 1
    assert "tmpl1" in resource["current"]
    assert resource["current"]["tmpl1"].kind == "Template"


@pytest.fixture
def test_fetch_current_state_long_kind_not_supported(
    oc_cs1: MagicMock, tmpl1: dict[str, Any]
) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "UnknownKind.mysterious.io")
    oc_cs1.get_items.return_value = [tmpl1]
    orb.fetch_current_state(
        oc=oc_cs1,
        ri=ri,
        cluster="cs1",
        namespace="ns1",
        kind="UnknownKind.mysterious.io",
        resource_names=[],
    )

    _, _, _, resource = next(iter(ri))
    assert len(resource["current"]) == 0


def test_fetch_states(
    current_state_spec: CurrentStateSpec,
    tmpl1: dict[str, Any],
    secret_reader: MagicMock,
) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Template")
    current_state_spec.oc.get_items = lambda kind, **kwargs: [tmpl1]  # type: ignore[method-assign]
    orb.fetch_states(
        ri=ri,
        spec=current_state_spec,
        cache=orb.Jinja2TemplateCache(),
        repo_url=REPO_URL,
        secret_reader=secret_reader,
    )
    _, _, _, resource = next(iter(ri))
    assert len(resource["current"]) == 1
    assert "tmpl1" in resource["current"]
    assert resource["current"]["tmpl1"].kind == "Template"


def test_fetch_states_unknown_kind(
    current_state_spec: CurrentStateSpec, secret_reader: MagicMock
) -> None:
    current_state_spec.kind = "UnknownKind"
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "UnknownKind")
    orb.fetch_states(
        ri=ri,
        spec=current_state_spec,
        cache=orb.Jinja2TemplateCache(),
        repo_url=REPO_URL,
        secret_reader=secret_reader,
    )
    _, _, _, resource = next(iter(ri))
    assert len(resource["current"]) == 0


def test_fetch_states_oc_error(
    current_state_spec: CurrentStateSpec, secret_reader: MagicMock
) -> None:
    current_state_spec.oc.get_items = Mock(  # type: ignore[method-assign]
        side_effect=oc.StatusCodeError("something wrong with openshift")
    )
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Template")
    orb.fetch_states(
        ri=ri,
        spec=current_state_spec,
        cache=orb.Jinja2TemplateCache(),
        repo_url=REPO_URL,
        secret_reader=secret_reader,
    )
    assert ri.has_error_registered("cs1")
    _, _, _, resource = next(iter(ri))
    assert len(resource["current"]) == 0


@pytest.fixture
def nss_csr_overrides() -> list[dict[str, Any]]:
    return [fxt.get_anymarkup("ns-overrides-cluster-resources.yml")]


@pytest.fixture
def api_resources() -> dict[str, list[Resource]]:
    p1 = Resource(
        prefix="",
        kind="Project",
        group="project.openshift.io",
        api_version="v1",
        namespaced=False,
    )
    p2 = Resource(
        prefix="",
        kind="Project",
        group="config.openshift.io",
        api_version="v1",
        namespaced=False,
    )
    cr = Resource(
        prefix="",
        kind="ClusterRole",
        group="rbac.authorization.k8s.io",
        api_version="v1",
        namespaced=False,
    )
    d1 = Resource(
        prefix="",
        kind="Deployment",
        group="apps",
        api_version="v1",
        namespaced=True,
    )
    return {"Project": [p1, p2], "ClusterRole": [cr], "Deployment": [d1]}


@pytest.fixture
def oc_api_resources(
    mocker: MockerFixture, api_resources: Mapping[str, Sequence[Resource]]
) -> oc.OCNative:
    mock = mocker.patch("reconcile.utils.oc.OCNative", autospec=True).return_value
    mock.get_api_resources.return_value = api_resources
    mock.is_kind_namespaced.side_effect = lambda k: k == "Deployment"
    return oc.OCNative("cluster", "server", "token", local=True)


@pytest.fixture
def oc_map_api_resources(
    mocker: MockerFixture, oc_api_resources: oc.OCNative
) -> oc.OC_Map:
    ocmap = mocker.patch("reconcile.utils.oc.OC_Map", autospec=True).return_value
    ocmap.get_cluster.return_value = oc_api_resources
    ocmap.clusters.side_effect = lambda include_errors=False, privileged=False: (
        ["cs1"] if not privileged else []
    )
    return ocmap


def test_get_namespace_cluster_scoped_resources(
    oc_map_api_resources: oc.OC_Map, nss_csr_overrides: Sequence[dict[str, Any]]
) -> None:
    expected = (
        "cs1",
        "ns1",
        {
            "ClusterRole": ["cr1"],
            "Project.config.openshift.io": ["pr1", "pr2"],
        },
    )

    result = orb._get_namespace_cluster_scoped_resources(
        nss_csr_overrides[0],
        oc_map_api_resources,
    )
    assert result == expected


def test_get_cluster_scoped_resources(
    oc_map_api_resources: oc.OC_Map, nss_csr_overrides: Sequence[dict[str, Any]]
) -> None:
    expected = {
        "cs1": {
            "ns1": {
                "ClusterRole": ["cr1"],
                "Project.config.openshift.io": ["pr1", "pr2"],
            }
        }
    }
    result = orb.get_cluster_scoped_resources(
        oc_map_api_resources, clusters=["cs1"], namespaces=nss_csr_overrides
    )
    assert result == expected


def test_find_resource_duplicates(oc_map_api_resources: oc.OC_Map) -> None:
    resource_map = {
        "cs1": {
            "ns1": {
                "ClusterRole": ["cr1"],
                "Project.config.openshift.io": ["pr1", "pr2"],
            },
            "ns2": {
                "ClusterRole": ["cr1"],
            },
        },
        "cs2": {
            "ns3": {
                "ClusterRole": ["cr1"],
                "ClusterRoleBinding": ["crb1"],
            },
            "ns4": {
                "ClusterRoleBinding": ["crb1"],
            },
        },
    }
    expected = [
        ("cs1", "ClusterRole", "cr1", ["ns1", "ns2"]),
        ("cs2", "ClusterRoleBinding", "crb1", ["ns3", "ns4"]),
    ]
    c = CheckClusterScopedResourceDuplicates(oc_map_api_resources)
    result = c._find_resource_duplicates(resource_map)
    assert result == expected


@pytest.fixture
def fake_or_resource() -> OR:
    return OR(
        body={
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "name",
            },
            "data": {
                "edge": "false",
                "name": "name",
            },
        },
        integration="integration",
        integration_version="1.0",
    )


@pytest.fixture
def resource_inventory_csr_tests(fake_or_resource: OR) -> ResourceInventory:
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "ClusterRole")
    ri.initialize_resource_type("cs1", "ns1", "Project.config.openshift.io")
    ri.add_desired("cs1", "ns1", "ClusterRole", "cr1", fake_or_resource, True)
    ri.add_desired(
        "cs1", "ns1", "Project.config.openshift.io", "pr1", fake_or_resource, True
    )
    ri.add_desired(
        "cs1", "ns1", "Project.config.openshift.io", "pr2", fake_or_resource, True
    )
    return ri


def test_check_cluster_scoped_resources_ok(
    oc_map_api_resources: oc.OC_Map,
    resource_inventory_csr_tests: ResourceInventory,
    nss_csr_overrides: Sequence[dict[str, Any]],
) -> None:
    error = orb.check_cluster_scoped_resources(
        oc_map_api_resources,
        resource_inventory_csr_tests,
        nss_csr_overrides,
        nss_csr_overrides,
    )

    assert error is False


def test_check_cluster_scoper_resources_non_declared(
    fake_or_resource: OR,
    oc_map_api_resources: oc.OC_Map,
    resource_inventory_csr_tests: ResourceInventory,
    nss_csr_overrides: Sequence[dict[str, Any]],
) -> None:
    resource_inventory_csr_tests.add_desired(
        "cs1", "ns1", "ClusterRole", "cr3", fake_or_resource, True
    )
    error = orb.check_cluster_scoped_resources(
        oc_map_api_resources,
        resource_inventory_csr_tests,
        nss_csr_overrides,
        nss_csr_overrides,
    )

    assert error is True


def test_check_cluster_scoped_resources_duplicated(
    oc_map_api_resources: oc.OC_Map,
    resource_inventory_csr_tests: ResourceInventory,
    nss_csr_overrides: Sequence[dict[str, Any]],
) -> None:
    ns2: dict[str, Any] = copy.deepcopy(nss_csr_overrides[0])
    ns2["name"] = "ns3"

    all_namespaces = [nss_csr_overrides[0], ns2]
    error = orb.check_cluster_scoped_resources(
        oc_map_api_resources,
        resource_inventory_csr_tests,
        nss_csr_overrides,
        all_namespaces,
    )

    assert error is True


def test_check_error() -> None:
    e = CheckError("message")
    print(e)


def test_cluster_params() -> None:
    with pytest.raises(RuntimeError):
        orb.run(dry_run=False, exclude_cluster=["test-cluster"])

    with pytest.raises(RuntimeError):
        orb.run(
            dry_run=False, cluster_name=["cluster-1"], exclude_cluster=["cluster-2"]
        )

    with pytest.raises(RuntimeError):
        orb.run(dry_run=False, cluster_name=["cluster-1", "cluster-2"])


@pytest.mark.parametrize(
    "test_parameters, exception_expected",
    [
        ({" leading_space": "test"}, SecretKeyFormatError),
        ({" space_padding ": "test"}, SecretKeyFormatError),
        ({"trailing_space ": "test"}, SecretKeyFormatError),
        ({"&invalidkey": "test"}, SecretKeyFormatError),
        ({"!invalidkey": "test"}, SecretKeyFormatError),
        ({"space issues": "test"}, SecretKeyFormatError),
        ({"/etc/passwd": "test"}, SecretKeyFormatError),
        ({"": "test"}, SecretKeyFormatError),
        ({".": "test"}, None),
        ({"0validkey": "test"}, None),
        ({"no_spacing": "test"}, None),
        ({"-": "test"}, None),
    ],
)
def test_secret_keys(
    test_parameters: dict[str, str],
    exception_expected: type[SecretKeyFormatError] | None,
) -> None:
    if exception_expected is not None:
        with pytest.raises(exception_expected):
            orb.assert_valid_secret_keys(test_parameters)
    else:
        orb.assert_valid_secret_keys(test_parameters)


def test_fetch_current_state_skips_argocd_managed(oc_cs1: oc.OCClient) -> None:
    """Resources labeled as managed by ArgoCD should be skipped in current state."""
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Deployment")
    argocd_labeled_resource = {
        "kind": "Deployment",
        "apiVersion": "apps/v1",
        "metadata": {
            "name": "my-deployment",
            "labels": {"app.kubernetes.io/part-of": "argocd"},
        },
    }
    oc_cs1.get_items = lambda kind, **kwargs: [argocd_labeled_resource]  # type: ignore[method-assign]
    orb.fetch_current_state(
        oc=oc_cs1,
        ri=ri,
        cluster="cs1",
        namespace="ns1",
        kind="Deployment",
        resource_names=[],
    )

    _, _, _, resource = next(iter(ri))
    assert len(resource["current"]) == 0
