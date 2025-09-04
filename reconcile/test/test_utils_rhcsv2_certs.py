from collections.abc import Callable
from pathlib import Path

import pytest

from reconcile.utils.rhcsv2_certs import extract_cert, get_cert_expiry_timestamp


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


def test_get_cert_expiry() -> None:
    # Test certificate with known expiry: Jan 1 00:00:00 2025 GMT (1735689600 Unix timestamp)
    # Base certificate generated with openssl:
    #   openssl req -x509 -newkey rsa:2048 -keyout /tmp/test.key -out /tmp/test.crt \
    #       -days 365 -nodes -subj "/CN=test" -not_after 250101000000Z
    # Cert then manually escaped with \\n and \\/ to simulate JavaScript string format that get_cert_expiry() processes
    js_escaped_pem = (
        "-----BEGIN CERTIFICATE-----\\n"
        "MIIC\\/zCCAeegAwIBAgIUZPQGpczjoiAs+tzGIz38A8FUTZowDQYJKoZIhvcNAQEL\\n"
        "BQAwDzENMAsGA1UEAwwEdGVzdDAeFw0yNDAxMDEwMDAwMDBaFw0yNTAxMDEwMDAw\\n"
        "MDBaMA8xDTALBgNVBAMMBHRlc3QwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEK\\n"
        "AoIBAQCnJ1a9BckG+Dfz2e\\/CrODiPeMO7iMNbfuQ6Kt3r+H8x9OPfUH4IT8q21jT\\n"
        "\\/at4HrRCEl2M5tNYDtZP7L84a6knuv26k32aV2jteGzMNTUGJRiINYpjclX\\/mzuF\\n"
        "DqFRU48qK1+0nbl0WoR4YV3c7wKh\\/FIeHTEnX65Z1A\\/u9h8WZXLkcgIqgboV3cig\\n"
        "F5D0fbZU+ja65MQOwPIP5dMnGGpMeEa5ff4L4RCEkgjyroaTMXGY8OJN2M6shvH4\\n"
        "tklev+i\\/YV3lFHIgY0gKGuhvKTc4E\\/3xbSPUfjBhs9JxGy6Sczcc+WgtRwP40Fmp\\n"
        "vU23DZXJZ3Goqs5FJi7Xy+KSAOAFAgMBAAGjUzBRMB0GA1UdDgQWBBSljiHERi1z\\n"
        "isMheQpV+V2sdBOHQjAfBgNVHSMEGDAWgBSljiHERi1zisMheQpV+V2sdBOHQjAP\\n"
        "BgNVHRMBAf8EBTADAQH\\/MA0GCSqGSIb3DQEBCwUAA4IBAQAdvod\\/6\\/kOUJ+ykJCC\\n"
        "yx5BOkhTkwV3QMlFbXnY\\/jUFiU8BAE6h3+dVZDwBemVb1Omd8\\/K1iKMYijQZROIY\\n"
        "ZG9\\/BkbJdosgxRMUzyfRg9wwY2uDoBesQflnvkBsigIKje6HAzxmBHRWPseQ2Xar\\n"
        "SXPHZlV+imH6TrND1abJZEYMd6VyAlpm+VaW1HesimEFCQWgWTlo54gcKUY1ZnLU\\n"
        "ztKuQT7G\\/ME05hIZn46TvgwVmUMog87qUzT5Kee3rATffGf7rYdgZndpnB\\/2UONl\\n"
        "DWWkEFYeUvmrVfHsOJjKiDxQnGRdFIVzG26s31kNTiDJip8e3jC1\\/HlSzh\\/afUtV\\n"
        "FSI2\\n"
        "-----END CERTIFICATE-----"
    )
    expected_expiry = 1735689600
    expiry_timestamp = get_cert_expiry_timestamp(js_escaped_pem)
    # confirm get_cert_expiry was able to handle js string encoding and extract the expiration
    assert expiry_timestamp == expected_expiry
