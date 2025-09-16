import re
from datetime import UTC

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

    cert_pem = extract_cert(response.text)
    cert_expiry_timestamp = get_cert_expiry_timestamp(cert_pem.group(1))
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
        expiration_timestamp=cert_expiry_timestamp,
    )
