from dns import resolver


def get_nameservers(domain):
    records = []
    answers = resolver.query(domain, 'NS')
    for rdata in answers:
        records.append(rdata.to_text())
    return records
