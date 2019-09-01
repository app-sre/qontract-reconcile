from subprocess import PIPE, Popen


def certificate_matches_host(certificate, host):
    common_name = get_certificate_common_name(certificate)
    return host.endswith(common_name.replace('*.', ''))


def get_certificate_common_name(certificate):
    proc = Popen(
        ['openssl', 'x509', '-noout', '-subject'],
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE
    )
    out, err = proc.communicate(certificate)

    return out.split('/CN=')[1].strip()
