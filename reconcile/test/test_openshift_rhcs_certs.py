import base64
import time
from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import ANY, MagicMock, call

import pytest
from pytest_mock import MockerFixture

import reconcile.openshift_rhcs_certs as rhcs_certs
from reconcile.gql_definitions.rhcs.certs import (
    NamespaceV1,
)
from reconcile.openshift_rhcs_certs import (
    QONTRACT_INTEGRATION,
    construct_rhcs_cert_oc_secret,
    fetch_desired_state,
    get_namespaces_with_rhcs_certs,
)
from reconcile.test.fixtures import Fixtures
from reconcile.typed_queries.rhcs_provider_settings import RhcsProviderSettingsV1
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.rhcsv2_certs import (
    CertificateFormat,
    RhcsV2CertPem,
    RhcsV2CertPkcs12,
)
from reconcile.utils.vault import SecretNotFoundError


def build_vault_cert_data(
    cert_format: str = "PEM", expiring: bool = False
) -> dict[str, str]:
    """Helper to build vault certificate data for different formats."""
    expiry_days = 1 if expiring else 120
    expiry_timestamp = str(int(time.time()) + 86400 * expiry_days)

    if cert_format == "PKCS12":
        return {
            "keystore.pkcs12.b64": "VALID_KEYSTORE",
            "truststore.pkcs12.b64": "VALID_TRUSTSTORE",
            "expiration_timestamp": expiry_timestamp,
        }
    else:
        return {
            "tls.crt": "VALID_CERT" if not expiring else "EXPIRED_CERT",
            "tls.key": "VALID_KEY" if not expiring else "EXPIRED_KEY",
            "ca.crt": "CA_CERT",
            "expiration_timestamp": expiry_timestamp,
        }


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


def assert_vault_writes_contain_cert_data__new_certs(vault_mock: MagicMock) -> None:
    """Validate vault writes contain correct certificate data using explicit call verification."""
    vault_mock.write.assert_has_calls(
        [
            # PEM certificates
            call(
                secret={
                    "path": f"app-interface/integrations-output/{QONTRACT_INTEGRATION}/cluster/with-openshift-rhcs-certs/test-cert-1",
                    "data": {
                        "tls.crt": ANY,
                        "tls.key": ANY,
                        "ca.crt": ANY,
                        "expiration_timestamp": ANY,
                    },
                },
                decode_base64=False,
            ),
            call(
                secret={
                    "path": f"app-interface/integrations-output/{QONTRACT_INTEGRATION}/cluster/with-openshift-rhcs-certs/test-cert-2",
                    "data": {
                        "tls.crt": ANY,
                        "tls.key": ANY,
                        "ca.crt": ANY,
                        "expiration_timestamp": ANY,
                    },
                },
                decode_base64=False,
            ),
            call(
                secret={
                    "path": f"app-interface/integrations-output/{QONTRACT_INTEGRATION}/cluster/with-openshift-rhcs-certs/test-cert-shared",
                    "data": {
                        "tls.crt": ANY,
                        "tls.key": ANY,
                        "ca.crt": ANY,
                        "expiration_timestamp": ANY,
                    },
                },
                decode_base64=False,
            ),
            # PKCS12 certificates
            call(
                secret={
                    "path": f"app-interface/integrations-output/{QONTRACT_INTEGRATION}/cluster/with-openshift-rhcs-certs/test-cert-pkcs12",
                    "data": {
                        "keystore.pkcs12.b64": ANY,
                        "truststore.pkcs12.b64": ANY,
                        "expiration_timestamp": ANY,
                    },
                },
                decode_base64=False,
            ),
            call(
                secret={
                    "path": f"app-interface/integrations-output/{QONTRACT_INTEGRATION}/cluster/with-openshift-rhcs-certs/test-cert-shared-pkcs12",
                    "data": {
                        "keystore.pkcs12.b64": ANY,
                        "truststore.pkcs12.b64": ANY,
                        "expiration_timestamp": ANY,
                    },
                },
                decode_base64=False,
            ),
        ],
        any_order=True,
    )


def create_vault_read_all_side_effect(
    secrets_by_name: dict[str, dict[str, str]],
) -> Callable:
    """Create a vault read_all side effect function that returns different cert data based on path endings."""

    def read_all_side_effect(secret: dict) -> dict[str, str]:
        path = secret["path"]
        secret_name = path.split("/")[-1]
        return secrets_by_name[secret_name]

    return read_all_side_effect


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
    """Smart certificate generator mock that returns appropriate format based on cert_format parameter."""

    def generate_cert_mock(
        *args: Any, **kwargs: Any
    ) -> RhcsV2CertPkcs12 | RhcsV2CertPem:
        cert_format = kwargs.get("cert_format", "PEM")
        if cert_format == "PKCS12":
            return RhcsV2CertPkcs12(
                pkcs12_keystore="FAKE_BASE64_KEYSTORE_DATA",
                pkcs12_truststore="FAKE_BASE64_TRUSTSTORE_DATA",
                expiration_timestamp=123456789,
            )
        else:
            return RhcsV2CertPem(
                certificate="PEM_ENCODED_CERTIFICATE",
                private_key="PEM_ENCODED_PRIVATE_KEY",
                ca_cert="PLACEHOLDER_CA_CERT",
                expiration_timestamp=123456789,
            )

    return mocker.patch(
        "reconcile.openshift_rhcs_certs.generate_cert", side_effect=generate_cert_mock
    )


def test_openshift_rhcs_certs__construct_rhcs_cert_secret_oc_resource_pem() -> None:
    """Test PEM format creates TLS secret with correct data."""
    qr = construct_rhcs_cert_oc_secret(
        "foobar",
        {
            "tls.crt": "PEM_ENCODED_CERTIFICATE",
            "tls.key": "PEM_ENCODED_PRIVATE_KEY",
            "ca.crt": "PEM_ENCODED_CA_CERTIFICATE",
            "expiration_timestamp": 123456789,
        },
        {"foo": "bar"},
        CertificateFormat.PEM,
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


def test_openshift_rhcs_certs__construct_rhcs_cert_secret_oc_resource_pkcs12() -> None:
    """Test PKCS#12 format creates Opaque secret with correct data."""
    qr = construct_rhcs_cert_oc_secret(
        "pkcs12-secret",
        {
            "keystore.pkcs12.b64": "FAKE_BASE64_KEYSTORE_DATA",
            "truststore.pkcs12.b64": "FAKE_BASE64_TRUSTSTORE_DATA",
            "expiration_timestamp": 123456789,
        },
        {"test": "annotation"},
        CertificateFormat.PKCS12,
    )
    assert qr.body == {
        "apiVersion": "v1",
        "data": {
            "keystore.pkcs12.b64": base64.b64encode(
                b"FAKE_BASE64_KEYSTORE_DATA"
            ).decode(),
            "truststore.pkcs12.b64": base64.b64encode(
                b"FAKE_BASE64_TRUSTSTORE_DATA"
            ).decode(),
            "expiration_timestamp": base64.b64encode(b"123456789").decode(),
        },
        "kind": "Secret",
        "metadata": {"name": "pkcs12-secret", "annotations": {"test": "annotation"}},
        "type": "Opaque",
    }


def test_openshift_rhcs_certs__fetch_desired_state_new_certs(
    mocker: MockerFixture,
    mock_rhcs_cert_provider: MagicMock,
    mock_cert_generator: MagicMock,
    namespaces: list[NamespaceV1],
    ri: ResourceInventory,
    query_func: Callable,
) -> None:
    """Test that new rhcs-cert definitions trigger generation"""
    mock_vault = mocker.patch("reconcile.openshift_rhcs_certs.VaultClient.get_instance")
    vault_instance = mock_vault.return_value
    vault_instance.read_all.side_effect = SecretNotFoundError("not found")
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None
    mocker.patch("reconcile.openshift_rhcs_certs.metrics.set_gauge")

    fetch_desired_state(False, namespaces, ri, query_func)

    expected_cert_count = sum(
        1 for ns in namespaces for r in ns.openshift_resources or []
    )

    assert mock_cert_generator.call_count == expected_cert_count
    assert vault_instance.write.call_count == expected_cert_count
    assert_vault_writes_contain_cert_data__new_certs(vault_instance)
    # inline certs + shared certs belonging to this namespace
    assert (
        len(ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"]["desired"])
        == 5
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
        == 5
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
    """Test that valid certificates in vault are reused without regeneration."""
    mock_vault = mocker.patch("reconcile.openshift_rhcs_certs.VaultClient.get_instance")
    vault_instance = mock_vault.return_value
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None
    mocker.patch("reconcile.openshift_rhcs_certs.metrics.set_gauge")

    # Set up vault to return valid, non-expired certificate data for all cert types
    cert_secrets_by_name = {
        "test-cert-1": build_vault_cert_data("PEM", expiring=False),
        "test-cert-2": build_vault_cert_data("PEM", expiring=False),
        "test-cert-shared": build_vault_cert_data("PEM", expiring=False),
        "test-cert-pkcs12": build_vault_cert_data("PKCS12", expiring=False),
        "test-cert-shared-pkcs12": build_vault_cert_data("PKCS12", expiring=False),
    }
    vault_instance.read_all.side_effect = create_vault_read_all_side_effect(
        cert_secrets_by_name
    )

    fetch_desired_state(False, namespaces, ri, query_func)

    # Since all certificates are valid and non-expired, none should be regenerated
    assert mock_cert_generator.call_count == 0
    assert vault_instance.write.call_count == 0
    assert (
        len(ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"]["desired"])
        == 5
    )
    assert "with-different-openshift-resource-providers" not in ri._clusters["cluster"]


def test_openshift_rhcs_certs__fetch_desired_state_expired_cert(
    mocker: MockerFixture,
    mock_rhcs_cert_provider: MagicMock,
    namespaces: list[NamespaceV1],
    ri: ResourceInventory,
    query_func: Callable,
) -> None:
    """Test that only expired certificates are regenerated."""
    mock_vault = mocker.patch("reconcile.openshift_rhcs_certs.VaultClient.get_instance")
    vault_instance = mock_vault.return_value
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None

    # Set up mixed scenario: some expired, some valid certificates
    cert_secrets_by_name = {
        "test-cert-1": build_vault_cert_data("PEM", expiring=True),  # This will expire
        "test-cert-2": build_vault_cert_data("PEM", expiring=False),  # Valid
        "test-cert-shared": build_vault_cert_data("PEM", expiring=False),  # Valid
        "test-cert-pkcs12": build_vault_cert_data("PKCS12", expiring=False),  # Valid
        "test-cert-shared-pkcs12": build_vault_cert_data(
            "PKCS12", expiring=False
        ),  # Valid
    }
    vault_instance.read_all.side_effect = create_vault_read_all_side_effect(
        cert_secrets_by_name
    )

    new_cert = RhcsV2CertPem(
        certificate="NEW_CERT",
        private_key="NEW_KEY",
        ca_cert="CA_CERT",
        expiration_timestamp=int(time.time()) + 86400 * 90,
    )
    mock_cert_generator = mocker.patch(
        "reconcile.openshift_rhcs_certs.generate_cert", return_value=new_cert
    )

    mocker.patch("reconcile.openshift_rhcs_certs.metrics.set_gauge")

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
    shared_ns = ns_by_name["cert-from-shared-resources"]

    assert "with-openshift-rhcs-certs" in ns_by_name
    assert shared_ns.openshift_resources, "shared resources not aggregated"
    assert any(r for r in shared_ns.openshift_resources), (
        "RHCS-cert not propagated from sharedResources"
    )


def test_openshift_rhcs_certs__early_exit_desired_state(
    query_func: Callable[[Any], Mapping[str, Any]],
) -> None:
    result = rhcs_certs.early_exit_desired_state(
        query_func=query_func,
        cluster_name="test-cluster",
    )

    assert "namespace" in result
    assert isinstance(result["namespace"], list)
    assert len(result["namespace"]) == 2
