import time

from reconcile.gql_definitions.rhcs.certs import (
    VaultSecretV1_VaultSecretV1,
)
from reconcile.openshift_rhcs_certs import (
    OpenshiftRhcsCert,
    create_or_update_certs,
    delete_certs,
)
from reconcile.utils.rhcsv2_certs import RhcsV2Cert
from reconcile.utils.vault import SecretNotFound


def test_create_or_update_certs_new_secret(monkeypatch, mocker):
    desired_cert = OpenshiftRhcsCert(
        name="cert-1",
        namespace="app-sre-dev",
        cluster="appsre01",
        sa_name="app-sre-dev-sa",
        sa_password=VaultSecretV1_VaultSecretV1(
            path="app-sre/creds/serviceaccounts/app-sre-dev-sa",
            field="password",
            version=1,
        ),
        auto_renew_threshold_days=5,
    )
    provider = mocker.Mock(
        vault_base_path="app-interface/integrations-output",
        url="https://ca.example.com",
    )
    vault = mocker.Mock()
    vault.read_all.side_effect = SecretNotFound()
    vault.read.return_value = "pwd123"

    gen_time = time.time()
    generated_cert = RhcsV2Cert(
        certificate="foo", private_key="bar", expiration_timestamp=int(gen_time)
    )
    monkeypatch.setattr(
        "reconcile.openshift_rhcs_certs.generate_cert",
        lambda url, uid, pwd: generated_cert,
    )
    state = mocker.Mock()

    create_or_update_certs(
        dry_run=False,
        state=state,
        vault=vault,
        desired_rhcs_certs=[desired_cert],
        cert_provider=provider,
        vault_simulator=None,
    )

    # vault.read_all.side_effect = SecretNotFound() for desired cert triggers creation of new cert
    # expect write to vault with generated cert and update to state
    vault.read_all.assert_called_once_with({
        "path": "app-interface/integrations-output/appsre01/app-sre-dev/cert-1"
    })
    vault.read.assert_called_once_with({
        "path": "app-sre/creds/serviceaccounts/app-sre-dev-sa",
        "field": "password",
        "version": 1,
    })
    vault.write.assert_called_once()
    state.add.assert_called_once_with(
        key="appsre01/app-sre-dev/cert-1", value={"expiration_timestamp": int(gen_time)}
    )


def test_create_or_update_certs_not_needed(monkeypatch, mocker):
    future_ts = int(time.time()) + 1000 * 24 * 3600
    cert = OpenshiftRhcsCert(
        name="cert-2",
        namespace="app-sre-dev",
        cluster="appsre01",
        sa_name="app-sre-dev-sa",
        sa_password=VaultSecretV1_VaultSecretV1(
            path="app-sre/creds/serviceaccounts/app-sre-dev-sa",
            field="password",
            version=1,
        ),
        auto_renew_threshold_days=7,
    )
    provider = mocker.Mock(
        vault_base_path="app-interface/integrations-output",
        url="https://ca.example.com",
    )
    vault = mocker.Mock()
    vault.read_all.return_value = {"expiration_timestamp": future_ts}
    vault.write = mocker.Mock()
    state = mocker.Mock()

    create_or_update_certs(
        dry_run=False,
        state=state,
        vault=vault,
        desired_rhcs_certs=[cert],
        cert_provider=provider,
        vault_simulator=None,
    )

    # vault.read_all should be called, but vault.write/state.add should not because cert exists
    # and is not within expiration threshold
    vault.read_all.assert_called_once()
    vault.write.assert_not_called()
    state.add.assert_not_called()


def test_create_or_update_cert_needed_expiring(monkeypatch, mocker):
    cert = OpenshiftRhcsCert(
        name="cert-3",
        namespace="app-sre-dev",
        cluster="appsre01",
        sa_name="app-sre-dev-sa",
        sa_password=VaultSecretV1_VaultSecretV1(
            path="app-sre/creds/serviceaccounts/app-sre-dev-sa",
            field="password",
            version=1,
        ),
        auto_renew_threshold_days=7,
    )
    provider = mocker.Mock(
        vault_base_path="app-interface/integrations-output",
        url="https://ca.example.com",
    )
    vault = mocker.Mock()
    vault.read_all.return_value = {"expiration_timestamp": int(time.time())}
    vault.write = mocker.Mock()
    state = mocker.Mock()
    vault.read_all.side_effect = SecretNotFound()
    vault.read.return_value = "pwd123"

    gen_time = time.time()
    generated_cert = RhcsV2Cert(
        certificate="foo", private_key="bar", expiration_timestamp=int(gen_time)
    )
    monkeypatch.setattr(
        "reconcile.openshift_rhcs_certs.generate_cert",
        lambda url, uid, pwd: generated_cert,
    )

    create_or_update_certs(
        dry_run=False,
        state=state,
        vault=vault,
        desired_rhcs_certs=[cert],
        cert_provider=provider,
        vault_simulator=None,
    )

    # cert existed but expiration was within threshold
    # expect write to vault with new cert and state update with new cert expiration
    vault.read_all.assert_called_once_with({
        "path": "app-interface/integrations-output/appsre01/app-sre-dev/cert-3"
    })
    vault.read.assert_called_once_with({
        "path": "app-sre/creds/serviceaccounts/app-sre-dev-sa",
        "field": "password",
        "version": 1,
    })
    vault.write.assert_called_once()
    state.add.assert_called_once_with(
        key="appsre01/app-sre-dev/cert-3", value={"expiration_timestamp": int(gen_time)}
    )


def test_delete_cert(mocker):
    cert = OpenshiftRhcsCert(
        name="cert-4",
        namespace="app-sre-dev",
        cluster="appsre01",
        sa_name="",
        sa_password=VaultSecretV1_VaultSecretV1(path="", field="", version=1),
        auto_renew_threshold_days=1,
    )
    provider = mocker.Mock(
        vault_base_path="app-interface/integrations-output",
        url="https://ca.example.com",
    )
    state = mocker.Mock()
    state.ls.return_value = [
        "/appsre01/app-sre-dev/cert-4",
        "/appsre01/app-sre-dev/delete-me-cert",
    ]
    vault = mocker.Mock()
    delete_certs(
        dry_run=False,
        state=state,
        vault=vault,
        desired_rhcs_certs=[cert],
        cert_provider=provider,
    )
    vault.delete.assert_called_once()
    vault.delete.assert_called_once_with(
        "app-interface/integrations-output/appsre01/app-sre-dev/delete-me-cert"
    )
    state.rm.assert_called_once_with("/appsre01/app-sre-dev/delete-me-cert")


def test_delete_certs_dry_run(monkeypatch, mocker):
    cert = OpenshiftRhcsCert(
        name="cert-4",
        namespace="app-sre-dev",
        cluster="appsre01",
        sa_name="",
        sa_password=VaultSecretV1_VaultSecretV1(path="", field="", version=1),
        auto_renew_threshold_days=1,
    )
    provider = mocker.Mock(
        vault_base_path="app-interface/integrations-output",
        url="https://ca.example.com",
    )
    state = mocker.Mock()
    state.ls.return_value = [
        "/appsre01/app-sre-dev/cert-4",
        "/appsre01/app-sre-dev/delete-me-cert",
    ]
    vault = mocker.Mock()
    delete_certs(
        dry_run=True,
        state=state,
        vault=vault,
        desired_rhcs_certs=[cert],
        cert_provider=provider,
    )

    vault.delete.assert_not_called()
    state.rm.assert_not_called()
