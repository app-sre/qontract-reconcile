import re
from datetime import UTC, datetime

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import BaseModel, Field


class RhcsV2Cert(BaseModel):
    certificate: str = Field(alias="tls.crt")
    private_key: str = Field(alias="tls.key")
    ca_cert: str = Field(alias="ca.crt")
    expiration_timestamp: int

    class Config:
        allow_population_by_field_name = True


def generate_cert(issuer_url: str, uid: str, pwd: str, ca_url: str) -> RhcsV2Cert:
    private_key = rsa.generate_private_key(65537, 4096)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(
            x509.Name([
                x509.NameAttribute(NameOID.USER_ID, uid),
            ])
        )
        .sign(private_key, hashes.SHA256())
    )
    data = {
        "uid": uid,
        "pwd": pwd,
        "cert_request_type": "pkcs10",
        "cert_request": csr.public_bytes(serialization.Encoding.PEM).decode(),
        "profileId": "caDirAppUserCert",
        "renewal": "false",
        "xmlOutput": "false",
    }
    response = requests.post(issuer_url, data=data)
    response.raise_for_status()

    cert_pem = re.search(
        r'outputList\.outputVal="(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----(?:\\n|\r?\n)?)";',
        response.text,
        re.DOTALL,
    )
    if not cert_pem:
        raise ValueError("Could not extract certificate PEM from response")
    cert_expiry = re.search(r"Not\s+After:\s+(.*?UTC)(?:\\n|\r?\n)?", response.text)
    if not cert_expiry:
        raise ValueError("Could not extract expiration date from response")
    # Weekday, Month Day, Year HH:MM:SS PM/AM Timezone
    dt_expiry = datetime.strptime(cert_expiry.group(1), "%A, %B %d, %Y %I:%M:%S %p %Z")
    dt_expiry = dt_expiry.replace(tzinfo=UTC)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    response = requests.get(ca_url)
    response.raise_for_status()
    ca_pem = response.text

    return RhcsV2Cert(
        private_key=private_key_pem,
        certificate=cert_pem.group(1)
        .encode()
        .decode("unicode_escape")
        .replace("\\/", "/"),
        ca_cert=ca_pem,
        expiration_timestamp=int(dt_expiry.timestamp()),
    )
