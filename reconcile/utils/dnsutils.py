from dns import resolver


def get_nameservers(domain):
    records = []
    answers = resolver.query(domain, "NS")
    for rdata in answers:
        records.append(rdata.to_text())
    return records


def get_a_records(host):
    records = []
    answers = resolver.query(host, "A")
    for rdata in answers:
        records.append(rdata.to_text())
    return records
