from OpenSSL import crypto


def certificate_matches_host(certificate: bytes, host: str) -> bool:
    if cn := get_certificate_common_name(certificate):
        domain = cn.replace("*.", "")
        return host == domain or host.endswith(f".{domain}")
    return False


def get_certificate_common_name(certificate: bytes) -> str:
    cert = crypto.load_certificate(crypto.FILETYPE_PEM, certificate)
    subject = cert.get_subject()
    return subject.CN
