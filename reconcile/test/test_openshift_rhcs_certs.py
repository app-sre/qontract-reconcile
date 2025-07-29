import base64
import time
from collections.abc import Callable, Mapping
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

import reconcile.openshift_rhcs_certs as rhcs_certs
from reconcile.gql_definitions.rhcs.certs import (
    NamespaceOpenshiftResourceRhcsCertV1,
    NamespaceV1,
)
from reconcile.openshift_rhcs_certs import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
    _is_rhcs_cert,
    construct_rhcs_cert_oc_secret,
    fetch_desired_state,
    get_namespaces_with_rhcs_certs,
)
from reconcile.test.fixtures import Fixtures
from reconcile.typed_queries.rhcs_provider_settings import RhcsProviderSettingsV1
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.rhcsv2_certs import RhcsV2Cert
from reconcile.utils.vault import SecretNotFoundError


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("openshift_rhcs_certs")


@pytest.fixture
def query_func(
    data_factory: Callable[[type[NamespaceV1], Mapping[str, Any]], Mapping[str, Any]],
    fx: Fixtures,
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "namespaces": [
                data_factory(NamespaceV1, item)
                for item in fx.get_anymarkup("namespaces.yml")["namespaces"]
            ]
        }

    return q


@pytest.fixture
def namespaces(query_func: Callable) -> list[NamespaceV1]:
    return get_namespaces_with_rhcs_certs(query_func)


@pytest.fixture
def ri(namespaces: list[NamespaceV1]) -> ResourceInventory:
    ri_ = ResourceInventory()
    ri_.initialize_resource_type(
        cluster="cluster",
        namespace="namespace",
        resource_type="Secret",
    )
    for ns in namespaces:
        ri_.initialize_resource_type(
            cluster=ns.cluster.name, namespace=ns.name, resource_type="Secret"
        )
    return ri_


@pytest.fixture
def mock_rhcs_cert_provider(mocker: MockerFixture) -> MagicMock:
    mock_provider = RhcsProviderSettingsV1(
        issuerUrl="https://ca.example.com/submit",
        vaultBasePath="app-interface/integrations-output",
        caCertUrl="https://ca.example.com/cert",
    )
    return mocker.patch.object(
        rhcs_certs, "get_rhcs_provider_settings", return_value=mock_provider
    )


@pytest.fixture
def mock_cert_generator(mocker: MockerFixture) -> MagicMock:
    fake_cert = RhcsV2Cert(
        certificate="PEM_ENCODED_CERTIFICATE",
        private_key="PEM_ENCODED_PRIVATE_KEY",
        ca_cert="PLACEHOLDER_CA_CERT",
        expiration_timestamp=123456789,
    )
    return mocker.patch(
        "reconcile.openshift_rhcs_certs.generate_cert", return_value=fake_cert
    )


def test_openshift_rhcs_certs__construct_rhcs_cert_secret_oc_resource() -> None:
    qr = construct_rhcs_cert_oc_secret(
        "foobar",
        {
            "tls.crt": "PEM_ENCODED_CERTIFICATE",
            "tls.key": "PEM_ENCODED_PRIVATE_KEY",
            "ca.crt": "PEM_ENCODED_CA_CERTIFICATE",
            "expiration_timestamp": 123456789,
        },
        {"foo": "bar"},
    )
    assert qr.body == {
        "apiVersion": "v1",
        "data": {
            "tls.crt": base64.b64encode(b"PEM_ENCODED_CERTIFICATE").decode(),
            "tls.key": base64.b64encode(b"PEM_ENCODED_PRIVATE_KEY").decode(),
            "ca.crt": base64.b64encode(b"PEM_ENCODED_CA_CERTIFICATE").decode(),
            "expiration_timestamp": base64.b64encode(b"123456789").decode(),
        },
        "kind": "Secret",
        "metadata": {"name": "foobar", "annotations": {"foo": "bar"}},
        "type": "kubernetes.io/tls",
    }


def test_openshift_rhcs_certs__fetch_desired_state_new_certs(
    mocker: MockerFixture,
    mock_rhcs_cert_provider: MagicMock,
    mock_cert_generator: MagicMock,
    namespaces: list[NamespaceV1],
    ri: ResourceInventory,
    query_func: Callable,
) -> None:
    mock_vault = mocker.patch("reconcile.openshift_rhcs_certs.VaultClient")
    vault_instance = mock_vault.return_value
    vault_instance.read_all.side_effect = SecretNotFoundError("not found")
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None
    mocker.patch("reconcile.openshift_rhcs_certs.metrics.set_gauge")

    fetch_desired_state(False, namespaces, ri, query_func)

    expected_cert_count = sum(
        1 for ns in namespaces for r in ns.openshift_resources or [] if _is_rhcs_cert(r)
    )
    expected_vault_paths: set[str] = {
        f"app-interface/integrations-output/{QONTRACT_INTEGRATION}"
        f"/{ns.cluster.name}/{ns.name}/"
        f"{cast('NamespaceOpenshiftResourceRhcsCertV1', r).secret_name}"
        for ns in namespaces
        for r in ns.openshift_resources or []
        if _is_rhcs_cert(r)
    }

    assert mock_cert_generator.call_count == expected_cert_count
    assert vault_instance.write.call_count == expected_cert_count

    for call_ in vault_instance.write.call_args_list:
        secret = call_.kwargs["secret"]
        assert secret["path"] in expected_vault_paths, (
            f"unexpected path {secret['path']}"
        )
        assert "tls.crt" in secret["data"]
        assert "expiration_timestamp" in secret["data"]

    # only the two *inline* certs belong to this namespace
    assert (
        len(ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"]["desired"])
        == 3
    )
    assert "with-different-openshift-resource-providers" not in ri._clusters["cluster"]


def test_openshift_rhcs_certs__fetch_desired_state_new_certs_dry_run(
    mocker: MockerFixture,
    mock_rhcs_cert_provider: MagicMock,
    mock_cert_generator: MagicMock,
    namespaces: list[NamespaceV1],
    ri: ResourceInventory,
    query_func: Callable,
) -> None:
    mock_vault = mocker.patch("reconcile.openshift_rhcs_certs.VaultClient")
    vault_instance = mock_vault.return_value
    vault_instance.read_all.side_effect = SecretNotFoundError("not found")
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None
    mocker.patch("reconcile.openshift_rhcs_certs.metrics.set_gauge")

    # dry-run → no Vault writes and no real cert generation
    fetch_desired_state(True, namespaces, ri, query_func)

    vault_instance.write.assert_not_called()
    mock_cert_generator.assert_not_called()

    assert (
        len(ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"]["desired"])
        == 3
    )
    assert "with-different-openshift-resource-providers" not in ri._clusters["cluster"]


def test_openshift_rhcs_certs__fetch_desired_state_existing_certs(
    mocker: MockerFixture,
    mock_rhcs_cert_provider: MagicMock,
    mock_cert_generator: MagicMock,
    namespaces: list[NamespaceV1],
    ri: ResourceInventory,
    query_func: Callable,
) -> None:
    mock_vault = mocker.patch("reconcile.openshift_rhcs_certs.VaultClient")
    vault_instance = mock_vault.return_value
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None
    mocker.patch("reconcile.openshift_rhcs_certs.metrics.set_gauge")

    ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"]["current"][
        "test-cert-1"
    ] = OR(
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        body={
            "apiVersion": "v1",
            "data": {
                "tls.crt": "PEM_ENCODED_CERTIFICATE",
                "tls.key": "PEM_ENCODED_PRIVATE_KEY",
                "ca.crt": "PEM_ENCODED_CA_CERT",
                "expiration_timestamp": "123456789",
            },
            "kind": "Secret",
            "metadata": {"name": "test-cert-1"},
            "type": "kubernetes.io/tls",
        },
    )

    fetch_desired_state(False, namespaces, ri, query_func)

    total_cert_objects = sum(
        1 for ns in namespaces for r in ns.openshift_resources or [] if _is_rhcs_cert(r)
    )
    assert mock_cert_generator.call_count == total_cert_objects
    assert vault_instance.write.call_count == total_cert_objects

    # desired now contains three secrets for the inline namespace
    assert (
        len(ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"]["desired"])
        == 3
    )
    assert "with-different-openshift-resource-providers" not in ri._clusters["cluster"]


def test_openshift_rhcs_certs__fetch_desired_state_expired_cert(
    mocker: MockerFixture,
    mock_rhcs_cert_provider: MagicMock,
    namespaces: list[NamespaceV1],
    ri: ResourceInventory,
    query_func: Callable,
) -> None:
    expiring_cert = {
        "tls.crt": "EXPIRED_CERT",
        "tls.key": "EXPIRED_KEY",
        "ca.crt": "CA_CERT",
        "expiration_timestamp": str(int(time.time()) + 86400),  # 1 day from now
    }
    valid_cert = {
        "tls.crt": "VALID_CERT",
        "tls.key": "VALID_KEY",
        "ca.crt": "CA_CERT",
        "expiration_timestamp": str(int(time.time()) + 86400 * 120),  # 120 days
    }

    mock_vault = mocker.patch("reconcile.openshift_rhcs_certs.VaultClient")
    vault_instance = mock_vault.return_value

    # Simulate returning [expiring_cert, valid_cert] for cert-1 and cert-2 respectively
    def read_all_side_effect(secret: dict) -> dict[str, str]:
        path = secret["path"]
        if path.endswith("test-cert-1"):
            return expiring_cert
        elif path.endswith("test-cert-2") or path.endswith("test-cert-shared"):
            return valid_cert
        raise ValueError(f"Unexpected path: {path}")

    vault_instance.read_all.side_effect = read_all_side_effect
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None

    new_cert = RhcsV2Cert(
        certificate="NEW_CERT",
        private_key="NEW_KEY",
        ca_cert="CA_CERT",
        expiration_timestamp=int(time.time()) + 86400 * 90,
    )
    mock_cert_generator = mocker.patch(
        "reconcile.openshift_rhcs_certs.generate_cert", return_value=new_cert
    )

    mocker.patch("reconcile.openshift_rhcs_certs.metrics.set_gauge")

    # Populate cluster with both current certs
    for cert_name in ["test-cert-1", "test-cert-2"]:
        ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"]["current"][
            cert_name
        ] = OR(
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            body={
                "apiVersion": "v1",
                "data": {
                    "tls.crt": "PEM_ENCODED_CERTIFICATE",
                    "tls.key": "PEM_ENCODED_PRIVATE_KEY",
                    "ca.crt": "PEM_ENCODED_CA_CERT",
                    "expiration_timestamp": "123456789",
                },
                "kind": "Secret",
                "metadata": {"name": cert_name},
                "type": "kubernetes.io/tls",
            },
        )

    fetch_desired_state(False, namespaces, ri, query_func)

    # Only the expiring cert should be regenerated and written
    assert mock_cert_generator.call_count == 1
    assert vault_instance.write.call_count == 1

    # Assert correct data was written to Vault
    secret_data = vault_instance.write.call_args[1]["secret"]["data"]
    assert secret_data["tls.crt"] == "NEW_CERT"
    assert secret_data["tls.key"] == "NEW_KEY"


def test_openshift_rhcs_certs__get_namespaces_with_shared_resources(
    query_func: Callable[[Any], Mapping[str, Any]],
) -> None:
    """
    Ensure that an RHCS-cert object defined only in a sharedResources file
    is copied into `namespace.openshift_resources` and that the namespace
    is therefore selected by `get_namespaces_with_rhcs_certs`.
    """
    namespaces = get_namespaces_with_rhcs_certs(query_func)
    ns_by_name = {ns.name: ns for ns in namespaces}
    assert "with-openshift-rhcs-certs" in ns_by_name

    shared_ns = ns_by_name["cert-from-shared-resources"]
    assert shared_ns.openshift_resources, "shared resources not aggregated"

    assert any(_is_rhcs_cert(r) for r in cast("list", shared_ns.openshift_resources)), (
        "RHCS-cert not propagated from sharedResources"
    )
