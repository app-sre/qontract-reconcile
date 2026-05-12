from OpenSSL import crypto


def certificate_matches_host(certificate: bytes, host: str) -> bool:
    if not (cn := get_certificate_common_name(certificate)):
        return False
    if cn.startswith("*."):
        domain = cn.removeprefix("*.")
        return host != domain and host.endswith(f".{domain}")
    return host == cn


def get_certificate_common_name(certificate: bytes) -> str:
    cert = crypto.load_certificate(crypto.FILETYPE_PEM, certificate)
    subject = cert.get_subject()
    return subject.CN
