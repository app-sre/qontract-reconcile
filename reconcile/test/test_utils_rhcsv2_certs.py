from collections.abc import Callable
from pathlib import Path

import pytest

from reconcile.utils.rhcsv2_certs import extract_cert


@pytest.fixture
def fx() -> Callable:
    def _fx(name: str) -> str:
        return (Path(__file__).parent / "fixtures" / "rhcsv2_certs" / name).read_text()

    return _fx


def test_extract_cert_valid_response(fx: Callable) -> None:
    html_response = fx("valid_response.html")
    result = extract_cert(html_response)
    # Verify the certificate PEM was extracted correctly
    expected_cert_pem = "-----BEGIN CERTIFICATE-----\\nMIIDXTCCAkWgAwIBAgIJAKoK/heBjcOuMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNV\\nBAYTAkFVMRMwEQYDVQQIDApTb21lLVN0YXRlMSEwHwYDVQQKDBhJbnRlcm5ldCBX\\naWRnaXRzIFB0eSBMdGQwHhcNMTcwNTE4MTAzNzI3WhcNMTgwNTE4MTAzNzI3WjBF\\nMQswCQYDVQQGEwJBVTETMBEGA1UECAwKU29tZS1TdGF0ZTEhMB8GA1UECgwYSW50\\nZXJuZXQgV2lkZ2l0cyBQdHkgTHRkMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIB\\nCgKCAQEA4f5wg5l2hKsTeNem/V41fGnJm6gOdrj8ym3rFkEjWT2btNioBpGU1qKo\\n-----END CERTIFICATE-----"
    assert result.group(1) == expected_cert_pem


def test_extract_cert_no_b64_cert_block(fx: Callable) -> None:
    html_response = fx("invalid_response_no_b64_cert.html")
    with pytest.raises(
        ValueError, match="Could not extract certificate PEM from response"
    ):
        extract_cert(html_response)


def test_extract_cert_invalid_cert_format(fx: Callable) -> None:
    html_response = fx("invalid_response_bad_cert.html")
    with pytest.raises(
        ValueError, match="Could not extract certificate PEM from response"
    ):
        extract_cert(html_response)


def test_unicode_escape_processing() -> None:
    # Test the encode().decode("unicode_escape").replace() logic used in generate_cert
    js_escaped_pem = "-----BEGIN CERTIFICATE-----\\nMIIDXTCCAkWgAwIBAgIJAKoK\\/heBjcOuMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNV\\nBAYTAkFVMRMwEQYDVQQIDApTb21lLVN0YXRlMSEwHwYDVQQKDBhJbnRlcm5ldCBX\\naWRnaXRzIFB0eSBMdGQwHhcNMTcwNTE4MTAzNzI3WhcNMTgwNTE4MTAzNzI3WjBF\\n-----END CERTIFICATE-----"
    processed_pem = js_escaped_pem.encode().decode("unicode_escape").replace("\\/", "/")
    expected_pem = "-----BEGIN CERTIFICATE-----\nMIIDXTCCAkWgAwIBAgIJAKoK/heBjcOuMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNV\nBAYTAkFVMRMwEQYDVQQIDApTb21lLVN0YXRlMSEwHwYDVQQKDBhJbnRlcm5ldCBX\naWRnaXRzIFB0eSBMdGQwHhcNMTcwNTE4MTAzNzI3WhcNMTgwNTE4MTAzNzI3WjBF\n-----END CERTIFICATE-----"
    assert processed_pem == expected_pem
    # Verify newlines are properly decoded
    assert "\\n" not in processed_pem
    assert "\n" in processed_pem
    # Verify forward slashes are unescaped
    assert "\\/" not in processed_pem
    assert "/" in processed_pem
