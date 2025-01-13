from dns import resolver


def get_nameservers(domain: str) -> list[str]:
    return [rdata.to_text() for rdata in resolver.query(domain, "NS")]


def get_a_records(host: str) -> list[str]:
    return [rdata.to_text() for rdata in resolver.query(host, "A")]
