import pytest
from OpenSSL import crypto

from reconcile.utils.openssl import (
    certificate_matches_host,
    get_certificate_common_name,
)


def _generate_cert(cn: str) -> bytes:
    """Generate a self-signed PEM certificate with the given CN."""
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 2048)
    cert = crypto.X509()
    cert.get_subject().CN = cn
    cert.set_serial_number(1)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(365 * 24 * 60 * 60)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)
    cert.sign(key, "sha256")
    return crypto.dump_certificate(crypto.FILETYPE_PEM, cert)


@pytest.fixture
def exact_cert() -> bytes:
    return _generate_cert("example.com")


@pytest.fixture
def wildcard_cert() -> bytes:
    return _generate_cert("*.example.com")


@pytest.mark.parametrize(
    ("cn", "expected"),
    [
        ("example.com", "example.com"),
        ("*.example.com", "*.example.com"),
        ("sub.domain.example.com", "sub.domain.example.com"),
    ],
)
def test_get_certificate_common_name(cn: str, expected: str) -> None:
    cert = _generate_cert(cn)
    assert get_certificate_common_name(cert) == expected


def test_get_certificate_common_name_invalid_pem() -> None:
    with pytest.raises(crypto.Error):
        get_certificate_common_name(b"not-a-certificate")


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("example.com", True),
        ("sub.example.com", False),
        ("other.com", False),
        ("notexample.com", False),
    ],
)
def test_certificate_matches_host_exact(
    exact_cert: bytes, host: str, expected: bool
) -> None:
    assert certificate_matches_host(exact_cert, host) == expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("foo.example.com", True),
        ("bar.example.com", True),
        ("example.com", False),
        ("foo.other.com", False),
        ("other.com", False),
    ],
)
def test_certificate_matches_host_wildcard(
    wildcard_cert: bytes, host: str, expected: bool
) -> None:
    assert certificate_matches_host(wildcard_cert, host) == expected
