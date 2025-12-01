import base64
import re
from datetime import UTC
from enum import StrEnum

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pydantic import BaseModel, Field


class CertificateFormat(StrEnum):
    PEM = "PEM"
    PKCS12 = "PKCS12"


class RhcsV2CertPem(BaseModel, validate_by_name=True, validate_by_alias=True):
    certificate: str = Field(alias="tls.crt")
    private_key: str = Field(alias="tls.key")
    ca_cert: str = Field(alias="ca.crt")
    expiration_timestamp: int


class RhcsV2CertPkcs12(BaseModel, validate_by_name=True, validate_by_alias=True):
    pkcs12_keystore: str = Field(alias="keystore.pkcs12.b64")
    pkcs12_truststore: str = Field(alias="truststore.pkcs12.b64")
    expiration_timestamp: int


def extract_cert(text: str) -> re.Match:
    # The CA webform returns an HTML page with inline JS that builds an array of “outputList”
    # objects. Each object looks roughly like:
    #   outputList = new Object;
    #   outputList.outputId = "pretty_cert";
    #   outputList.outputSyntax = "pretty_print";
    #   outputList.outputVal = "    Certificate:\n ... Not  After: ...";
    #   outputListSet[0] = outputList;
    #
    #   outputList = new Object;
    #   outputList.outputId = "b64_cert";
    #   outputList.outputSyntax = "pretty_print";
    #   outputList.outputVal = "-----BEGIN CERTIFICATE-----\n...base64...\n-----END CERTIFICATE-----\n";
    #   outputListSet[1] = outputList;
    #
    # We must extract the PEM from the *b64_cert* block (the pretty_cert block contains prose
    # and formatting and is not reliable for parsing).
    #
    # The regex below:
    # - Anchors on `outputId = "b64_cert"` so we only consider the base64 block.
    # - Tolerates arbitrary whitespace around `=` and `.` (services sometimes reformat JS).
    # - Jumps non-greedily over whatever properties sit between outputId and outputVal.
    # - Captures only the PEM body (BEGIN…END), excluding any trailing newline/escape junk.
    # - Accepts multiple terminators after the closing quote: literal "\\r\\n", literal "\\n",
    #   or a real newline (`\r?\n`), followed by optional whitespace and the semicolon.
    # - Uses DOTALL so `.` spans line breaks inside the JS/HTML blob.

    cert_pem = re.search(
        r'outputList\s*\.\s*outputId\s*=\s*"b64_cert".*?'
        r'outputList\s*\.\s*outputVal\s*=\s*"'
        r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)"
        r"(?:\\r\\n|\\n|\r?\n)?\s*",
        text,
        re.DOTALL,
    )
    if not cert_pem:
        raise ValueError("Could not extract certificate PEM from response")
    return cert_pem


def get_cert_expiry_timestamp(js_escaped_pem: str) -> int:
    """Extract certificate expiry timestamp from JavaScript-escaped PEM."""

    # Convert JavaScript-escaped PEM to proper format: .encode() is needed because
    # unicode_escape decoder only works on bytes, then decode JS escape sequences
    pem_raw = js_escaped_pem.encode().decode("unicode_escape").replace("\\/", "/")
    cert = x509.load_pem_x509_certificate(pem_raw.encode())
    dt_expiry = cert.not_valid_after.replace(tzinfo=UTC)
    return int(dt_expiry.timestamp())


def _format_pem(
    private_key: rsa.RSAPrivateKey,
    cert_pem: str,
    ca_pem: str,
    cert_expiry_timestamp: int,
) -> RhcsV2CertPem:
    """Generate RhcsV2Cert with PEM components."""
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return RhcsV2CertPem(
        private_key=private_key_pem,
        certificate=cert_pem.encode().decode("unicode_escape").replace("\\/", "/"),
        ca_cert=ca_pem,
        expiration_timestamp=cert_expiry_timestamp,
    )


def _format_pkcs12(
    private_key: rsa.RSAPrivateKey,
    cert_pem: str,
    ca_pem: str,
    uid: str,
    pwd: str,
    cert_expiry_timestamp: int,
) -> RhcsV2CertPkcs12:
    """Generate PKCS#12 keystore and truststore components, returns base64-encoded strings."""
    clean_cert_pem = cert_pem.encode().decode("unicode_escape").replace("\\/", "/")
    cert_obj = x509.load_pem_x509_certificate(clean_cert_pem.encode())
    ca_obj = x509.load_pem_x509_certificate(ca_pem.encode())
    keystore_p12 = pkcs12.serialize_key_and_certificates(
        name=uid.encode("utf-8"),
        key=private_key,
        cert=cert_obj,
        cas=[ca_obj],
        encryption_algorithm=serialization.BestAvailableEncryption(pwd.encode("utf-8")),
    )
    truststore_p12 = pkcs12.serialize_key_and_certificates(
        name=b"ca-trust",
        key=None,
        cert=None,
        cas=[ca_obj],
        encryption_algorithm=serialization.NoEncryption(),
    )
    return RhcsV2CertPkcs12(
        pkcs12_keystore=base64.b64encode(keystore_p12).decode("utf-8"),
        pkcs12_truststore=base64.b64encode(truststore_p12).decode("utf-8"),
        expiration_timestamp=cert_expiry_timestamp,
    )


def generate_cert(
    issuer_url: str,
    uid: str,
    pwd: str,
    ca_url: str,
    cert_format: CertificateFormat = CertificateFormat.PEM,
) -> RhcsV2CertPem | RhcsV2CertPkcs12:
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
    response = requests.post(issuer_url, data=data, timeout=30)
    response.raise_for_status()
    cert_pem = extract_cert(response.text).group(1)
    cert_expiry_timestamp = get_cert_expiry_timestamp(cert_pem)

    response = requests.get(ca_url, timeout=30)
    response.raise_for_status()
    ca_pem = response.text

    match cert_format:
        case CertificateFormat.PKCS12:
            return _format_pkcs12(
                private_key, cert_pem, ca_pem, uid, pwd, cert_expiry_timestamp
            )
        case CertificateFormat.PEM:
            return _format_pem(private_key, cert_pem, ca_pem, cert_expiry_timestamp)
