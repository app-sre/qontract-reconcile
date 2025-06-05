import base64
import time
from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

import reconcile.openshift_rhcs_certs as rhcs_certs
from reconcile.gql_definitions.rhcs.certs import NamespaceV1
from reconcile.openshift_rhcs_certs import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
    construct_rhcs_cert_oc_secret,
    fetch_desired_state,
    get_namespaces_with_rhcs_certs,
)
from reconcile.test.fixtures import Fixtures
from reconcile.typed_queries.rhcs_provider_settings import RhcsProviderSettingsV1
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.rhcsv2_certs import RhcsV2Cert
from reconcile.utils.vault import SecretNotFound


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
        url="https://ca.example.com/submit",
        vaultBasePath="app-interface/integrations-output",
    )
    return mocker.patch.object(
        rhcs_certs, "get_rhcs_provider_settings", return_value=mock_provider
    )


@pytest.fixture
def mock_cert_generator(mocker: MockerFixture) -> MagicMock:
    fake_cert = RhcsV2Cert(
        certificate="PEM_ENCODED_CERTIFICATE",
        private_key="PEM_ENCODED_PRIVATE_KEY",
        expiration_timestamp=123456789,
    )
    return mocker.patch(
        "reconcile.openshift_rhcs_certs.generate_cert", return_value=fake_cert
    )


def test_openshift_rhcs_certs__construct_rhcs_cert_secret_oc_resource() -> None:
    qr = construct_rhcs_cert_oc_secret(
        "foobar",
        {
            "certificate": "PEM_ENCODED_CERTIFICATE",
            "private_key": "PEM_ENCODED_PRIVATE_KEY",
            "expiration_timestamp": 123456789,
        },
        {"foo": "bar"},
    )
    assert qr.body == {
        "apiVersion": "v1",
        "data": {
            "certificate": base64.b64encode(b"PEM_ENCODED_CERTIFICATE").decode(),
            "private_key": base64.b64encode(b"PEM_ENCODED_PRIVATE_KEY").decode(),
            "expiration_timestamp": base64.b64encode(b"123456789").decode(),
        },
        "kind": "Secret",
        "metadata": {"name": "foobar", "annotations": {"foo": "bar"}},
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
    mock_vault = mocker.patch("reconcile.openshift_rhcs_certs.VaultClient")
    vault_instance = mock_vault.return_value
    vault_instance.read_all.side_effect = SecretNotFound("not found")
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None

    mocker.patch("reconcile.openshift_rhcs_certs.metrics.set_gauge")

    fetch_desired_state(False, namespaces, ri, query_func)

    expected_vault_write_paths = {
        "test-cert-1": f"app-interface/integrations-output/{QONTRACT_INTEGRATION}/cluster/with-openshift-rhcs-certs/test-cert-1",
        "test-cert-2": f"app-interface/integrations-output/{QONTRACT_INTEGRATION}/cluster/with-openshift-rhcs-certs/test-cert-2",
    }
    assert mock_cert_generator.call_count == 2
    assert vault_instance.write.call_count == 2
    calls = vault_instance.write.call_args_list
    for call_ in calls:
        _args, kwargs = call_
        secret = kwargs["secret"]
        assert "certificate" in secret["data"]
        assert "expiration_timestamp" in secret["data"]
        assert "path" in secret

        secret_name = secret["path"].split("/")[-1]
        assert secret["path"] == expected_vault_write_paths[secret_name], (
            f"Unexpected path for {secret_name}: {secret['path']}"
        )
    assert (
        len(
            ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"][
                "desired"
            ].keys()
        )
        == 2
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
    vault_instance.read_all.side_effect = SecretNotFound("not found")
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None

    mocker.patch("reconcile.openshift_rhcs_certs.metrics.set_gauge")

    fetch_desired_state(False, namespaces, ri, query_func)
    assert vault_instance.write.not_called()
    assert mock_cert_generator.not_called()

    assert (
        len(
            ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"][
                "desired"
            ].keys()
        )
        == 2
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
                "certificate": "PEM_ENCODED_CERTIFICATE",
                "private_key": "PEM_ENCODED_PRIVATE_KEY",
                "expiration_timestamp": "123456789",
            },
            "kind": "Secret",
            "metadata": {"name": "test-cert-1"},
            "type": "Opaque",
        },
    )

    fetch_desired_state(False, namespaces, ri, query_func)
    assert vault_instance.write.called_once()
    assert mock_cert_generator.called_once()
    assert (
        len(
            ri._clusters["cluster"]["with-openshift-rhcs-certs"]["Secret"][
                "desired"
            ].keys()
        )
        == 2
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
        "certificate": "EXPIRED_CERT",
        "private_key": "EXPIRED_KEY",
        "expiration_timestamp": str(int(time.time()) + 86400),  # 1 day from now
    }
    valid_cert = {
        "certificate": "VALID_CERT",
        "private_key": "VALID_KEY",
        "expiration_timestamp": str(int(time.time()) + 86400 * 120),  # 120 days
    }

    mock_vault = mocker.patch("reconcile.openshift_rhcs_certs.VaultClient")
    vault_instance = mock_vault.return_value

    # Simulate returning [expiring_cert, valid_cert] for cert-1 and cert-2 respectively
    def read_all_side_effect(secret: dict) -> dict[str, str]:
        path = secret["path"]
        if path.endswith("test-cert-1"):
            return expiring_cert
        elif path.endswith("test-cert-2"):
            return valid_cert
        raise ValueError(f"Unexpected path: {path}")

    vault_instance.read_all.side_effect = read_all_side_effect
    vault_instance.read.return_value = "FAKE_SA_PASSWORD"
    vault_instance.write.return_value = None

    new_cert = RhcsV2Cert(
        certificate="NEW_CERT",
        private_key="NEW_KEY",
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
                    "certificate": "PEM_ENCODED_CERTIFICATE",
                    "private_key": "PEM_ENCODED_PRIVATE_KEY",
                    "expiration_timestamp": "123456789",
                },
                "kind": "Secret",
                "metadata": {"name": cert_name},
                "type": "Opaque",
            },
        )

    fetch_desired_state(False, namespaces, ri, query_func)

    # Only the expiring cert should be regenerated and written
    assert mock_cert_generator.call_count == 1
    assert vault_instance.write.call_count == 1

    # Assert correct data was written to Vault
    secret_data = vault_instance.write.call_args[1]["secret"]["data"]
    assert secret_data["certificate"] == "NEW_CERT"
    assert secret_data["private_key"] == "NEW_KEY"
