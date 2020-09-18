import re


octal_re = re.compile(r'\\(\d\d\d)')


def _octal_replace(s):
    """
    Replace octal characters with the actual ASCII character

    See http://docs.aws.amazon.com/Route53/latest/DeveloperGuide/

    :param s: source string
    :type s: str
    :return updated string
    :rtype str
    """
    return octal_re.sub(lambda m: chr(int(m.group(1), 8)), s)


class DuplicateException(Exception):
    pass


class InvalidRecordData(AttributeError):
    pass


class InvalidRecordType(Exception):
    pass


class State(object):
    """
    State represents a state across multiple accounts

    :param name: unique name that describes the state
    :type name: str
    """
    def __init__(self, name):
        self._name = name
        self._accounts = []

    @property
    def name(self):
        """Returns the name of the state"""
        return self._name

    @property
    def accounts(self):
        """
        Returns the accounts within the state

        :return: mapping of accounts by name
        :rtype: dict of (str, Account)
        """
        return {a.name: a for a in self._accounts}

    def add_account(self, account):
        """
        Add an account to the state

        :param account: the account to add
        :type account: Account
        :raises DuplicateException: if an account by that name already exists
        """
        if self.accounts.get(account.name):
            raise DuplicateException(
                f"Refusing to add duplicate {account} to {self}")
        self._accounts.append(account)

    def get_account(self, name):
        """
        Retrieve an account from the state

        :return: an account
        :rtype: Account
        """
        return self.accounts.get(name)

    def __str__(self):
        return f"State<{self.name}>"


class Account(object):
    """
    Account represents an account and its DNS Zones

    :param name: unique name that describes the account
    :type name: str
    """
    def __init__(self, name):
        self._name = name
        self._zones = []

    @property
    def name(self):
        """Returns the name of the account"""
        return self._name

    @property
    def zones(self):
        """
        Returns the DNS zones managed under the account

        :return: list of DNS zones
        :rtype: list of Zone
        """
        return {a.name: a for a in self._zones}

    def add_zone(self, zone):
        """
        Add a zone to the account

        :param zone: DNS zone to add
        :type zone: Zone
        :raises DuplicateException: if a zone by that name already exists
        """
        if self.zones.get(zone.name):
            raise DuplicateException(
                f"Refusing to add duplicate {zone} to {self}")
        self._zones.append(zone)

    def get_zone(self, name):
        """
        Retrieve a zone by name

        :param name: Zone name to retrieve
        :type name: str
        :return: DNS zone
        :rtype: Zone
        """
        return self.zones.get(name)

    def __str__(self):
        return f"Account<{self.name}>"


class Zone(object):
    """
    Zone represents a DNS zone

    :param name: DNS domain name
    :param data: DNS zone data
    :type name: str
    :type data: dict
    """
    def __init__(self, name, data=None):
        self._name = name.lower().rstrip('.')
        self._records = []
        if data is None:
            self._data = {}
        else:
            self._data = data

    @property
    def data(self):
        """Returns the zone data"""
        return self._data

    @property
    def name(self):
        """Returns the zone name"""
        return self._name

    @property
    def records(self):
        """Return DNS records"""
        return {f"{r.name}": r for r in self._records}

    def add_record(self, record):
        """
        Add a record to the zone

        :param record: the record to add
        :type record: Record
        :raises DuplicateException: if a record by that name already exists
        """
        if self.records.get(record.name):
            raise DuplicateException(
                f"Refusing to add duplicate {record} to {self}")
        self._records.append(record)

    def remove_record(self, record_name):
        """
        Remove a record to the zone based on the record name

        :param record_name: name of the record to remove
        :type record: str
        """
        for record in self._records:
            if record.name == record_name:
                self._records.remove(record)

    def __eq__(self, other):
        if not isinstance(other, Zone):
            return False
        return (self.name == other.name and
                self.records == other.records)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return f"Zone<{self.name}>"


class Record(object):
    """
    Record represents a DNS record

    :param zone: the zone the record belongs to
    :param name: the record name
    :param data: the record data
    :param awsdata: the original aws data for a dns record
    :type zone: Zone
    :type name: str
    :type data: dict
    :type awsdata: dict
    """

    SUPPORTED_TYPES = ['A', 'CNAME', 'NS', 'TXT']

    def __init__(self, zone, name, data, awsdata=None):
        self._zone = zone
        self._name = _octal_replace(name).lower().rstrip('.')

        try:
            self._type = data['type']
            self._ttl = int(data['ttl'])
        except KeyError as e:
            raise InvalidRecordData(f"missing key {e} in Record data")

        if self._type not in self.SUPPORTED_TYPES:
            raise InvalidRecordType(f"Type {self._type} is not supported")

        self._values = data.get('values', [])
        self._data = data
        if awsdata is None:
            self._awsdata = {}
        else:
            self._awsdata = awsdata

    @property
    def data(self):
        """Returns the record data"""
        return self._data

    @property
    def fqdn(self):
        """Returns the record's FQDN"""
        return f"{self.name}.{self.zone.name}"

    @property
    def name(self):
        """Returns the record name"""
        return self._name

    @property
    def awsdata(self):
        """Returns the record's awsdata"""
        return self._awsdata

    @property
    def ttl(self):
        """Returns the record TTL"""
        return self._ttl

    @property
    def type(self):
        """Returns the record type"""
        return self._type

    @property
    def zone(self):
        """Returns the parent zone"""
        return self._zone

    @property
    def values(self):
        """Returns the values for the record"""
        return sorted(self._values)

    def add_targets(self, values):
        """
        Add a list of targets to the record

        :param values: a list of values to add
        :type values: list of str
        """
        self._values.extend(values)

    def __eq__(self, other):
        if not isinstance(other, Record):
            return False
        return (self.name == other.name and
                self.ttl == other.ttl and
                self.type == other.type and
                self.values == other.values)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        if self.name:
            return f"Record<{self.type}, {self.name}>"
        return f"Record<{self.type}>"
