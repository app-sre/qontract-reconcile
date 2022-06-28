from typing import Any

import pytest

from reconcile.utils.smtp_client import SmtpClient


@pytest.fixture
def patch_env(monkeypatch):
    # do not mess around with SSL and certificates
    monkeypatch.setenv("SMTPD_SSL_CERTS_PATH", "/do-not-create-a-certificate")


@pytest.fixture
def patch_secret_reader(mocker, patch_env, smtpd):
    # Instead of mocking smtplib.SMTP, we are using a real testing SMTP server
    # (https://github.com/bebleo/smtpdfix) via pytest fixture (smtpd).

    # do not mess around with SSL and certificates
    smtpd.config.use_ssl = False
    return mocker.patch(
        "reconcile.utils.secret_reader.SecretReader.read_all",
        return_value={
            "server": smtpd.hostname,
            "port": smtpd.port,
            "username": smtpd.config.login_username,
            "password": smtpd.config.login_password,
            "require_tls": smtpd.config.use_ssl,
        },
        autospec=True,
    )


@pytest.fixture
def settings(mocker):
    return {"smtp": {"mailAddress": "mailAddress.com", "credentials": "foobar"}}


@pytest.fixture
def smtp_client(settings: dict[str, Any], patch_secret_reader):
    return SmtpClient(settings)


def test_smtp_client_init_and_getting_smtp_config(smtp_client: SmtpClient, smtpd):
    assert smtp_client.host == smtpd.hostname
    assert smtp_client.user == smtpd.config.login_username
    assert smtp_client.passwd == smtpd.config.login_password
    assert smtp_client.port == smtpd.port
    assert smtp_client.mail_address == "mailAddress.com"
    assert smtp_client.timeout == 30


def test_smtp_client_get_recipient(smtp_client: SmtpClient):
    assert smtp_client.get_recipient("benturner") == "benturner@mailAddress.com"


def test_smtp_client_send_mail(smtp_client: SmtpClient, smtpd):
    smtp_client.send_mail(["benturner"], "subject_subject", "body_body_body")
    assert len(smtpd.messages) == 1
    msg = smtpd.messages[0]
    assert "subject_subject" == msg.get("subject")
    assert "benturner@mailAddress.com" == msg.get("to")
    assert "\nbody_body_body" in msg.as_string()


def test_smtp_client_send_mails(smtp_client: SmtpClient, smtpd):
    smtp_client.send_mails(
        [
            ("benturner", "subject_subject", "body_body_body"),
            ("2benturner2", "2subject_subject2", "2body_body_body2"),
        ]
    )
    assert len(smtpd.messages) == 2

    msg = smtpd.messages[0]
    assert "subject_subject" == msg.get("subject")
    assert "benturner@mailAddress.com" == msg.get("to")
    assert "\nbody_body_body" in msg.as_string()

    msg = smtpd.messages[1]
    assert "2subject_subject2" == msg.get("subject")
    assert "2benturner2@mailAddress.com" == msg.get("to")
    assert "\n2body_body_body2" in msg.as_string()
