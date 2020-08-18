import unittest

from utils.aws.route53 import _octal_replace
from utils.aws.route53 import Account, Record, State, Zone
from utils.aws.route53 import DuplicateException, InvalidRecordData
from utils.aws.route53 import InvalidRecordType


class TestAWSRoute53OctalReplace(unittest.TestCase):
    def test_octal_replace_wildcard(self):
        """Replace \\052 with a * character"""
        a = '\052.foo.bar'
        b = _octal_replace(a)
        self.assertEqual(b, '*.foo.bar')


class TestAWSRoute53State(unittest.TestCase):
    def test_state_name(self):
        """State can return it's name"""
        state = State('test-state')
        self.assertEqual(state.name, 'test-state')

    def test_add_account_to_state(self):
        """State can add account"""
        state = State('test-state')
        account = Account('test-account')
        state.add_account(account)
        self.assertEqual(state.accounts.get('test-account'), account)

    def test_get_account_from_state(self):
        """State can retrieve account by name"""
        state = State('test-state')
        account = Account('test-account')
        state.add_account(account)
        self.assertEqual(state.get_account('test-account'), account)

    def test_state_cant_have_duplicate_accounts(self):
        """State cant have multiple accounts of the same name"""
        state = State('test-state')
        state.add_account(Account('test-account'))
        with self.assertRaises(DuplicateException):
            state.add_account(Account('test-account'))

    def test_state_returns_list_of_accounts(self):
        """State can return a list of accounts"""
        state = State('test-state')
        a_account = Account('a-account')
        b_account = Account('b-account')
        c_account = Account('c-account')
        state.add_account(a_account)
        state.add_account(b_account)
        state.add_account(c_account)

        self.assertEqual(state.accounts, {
            'a-account': a_account,
            'b-account': b_account,
            'c-account': c_account,
        })

    def test_state_repr(self):
        """State can return a representation of itself"""
        state = State('test-state')
        self.assertEqual(f'{state}', 'State<test-state>')


class TestAWSRoute53Account(unittest.TestCase):
    def test_account_name(self):
        """Account can return it's name"""
        account = Account('test-account')
        self.assertEqual(account.name, 'test-account')

    def test_add_zone_to_account(self):
        """Account can add zone"""
        account = Account('test-account')
        zone = Zone('test.example.com')
        account.add_zone(zone)
        self.assertEqual(account.zones.get('test.example.com'), zone)

    def test_get_zone_from_account(self):
        """Account can retrieve zone"""
        account = Account('test-account')
        zone = Zone('test.example.com')
        account.add_zone(zone)
        self.assertEqual(account.get_zone('test.example.com'), zone)

    def test_account_cant_have_duplicate_zones(self):
        """Account cannot have multiple zones with the same name"""
        account = Account('test-account')
        account.add_zone(Zone('test.example.com'))
        with self.assertRaises(DuplicateException):
            account.add_zone(Zone('test.example.com'))

    def test_account_returns_list_of_zones(self):
        """Account can return a list of zones"""
        account = Account('test-account')
        a_zone = Zone('azone.com')
        b_zone = Zone('bzone.com')
        c_zone = Zone('czone.com')
        account.add_zone(a_zone)
        account.add_zone(b_zone)
        account.add_zone(c_zone)

        self.assertDictEqual(account.zones, {
            'azone.com': a_zone,
            'bzone.com': b_zone,
            'czone.com': c_zone,
        })

    def test_account_repr(self):
        """Account can return a representation of itself"""
        account = Account('test-account')
        self.assertEqual(f'{account}', 'Account<test-account>')


class TestAWSRoute53Zone(unittest.TestCase):
    def test_zone_name(self):
        """Zone can return it's name"""
        zone = Zone('test.example.com')
        self.assertEqual(zone.name, 'test.example.com')

    def test_add_record_to_zone(self):
        """Zone can add a record to zone and return it"""
        zone = Zone('test.example.com')
        record = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        zone.add_record(record)
        self.assertEqual(zone.records.get('test-record'), record)

    def test_zone_cant_have_duplicate_records(self):
        """Zone cannot add multiple records with same name"""
        zone = Zone('test.example.com')
        recordA = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        recordB = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        zone.add_record(recordA)
        with self.assertRaises(DuplicateException):
            zone.add_record(recordB)

    def test_add_multiple_records_to_zone(self):
        """Zone can add multiple records with different names"""
        zone = Zone('test.example.com')
        recordA = Record(zone, 'test-recorda', {'type': 'A', 'ttl': 300})
        recordB = Record(zone, 'test-recordb', {'type': 'A', 'ttl': 300})
        zone.add_record(recordA)
        zone.add_record(recordB)
        self.assertDictEqual(zone.records, {
            'test-recorda': recordA,
            'test-recordb': recordB,
        })

    def test_compare_zone_equal(self):
        """Zone with same names are equal"""
        zoneA = Zone('zonea.example.com')
        zoneB = Zone('zonea.example.com')
        self.assertEqual(zoneA, zoneB)

    def test_compare_zone_not_equal(self):
        """Zone with different names are not equal"""
        zoneA = Zone('zonea.example.com')
        zoneB = Zone('zoneb.example.com')
        self.assertNotEqual(zoneA, zoneB)

    def test_zone_repr(self):
        """Zone can return a representation of itself"""
        zone = Zone('example.com')
        self.assertEqual(f'{zone}', 'Zone<example.com>')


class TestAWSRoute53Record(unittest.TestCase):
    def test_record_name(self):
        """Record can return it's name"""
        zone = Zone('test.example.com')
        record = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        self.assertEqual(record.name, 'test-record')

    def test_record_fqdn(self):
        """Record can return it's fqdn"""
        zone = Zone('test.example.com')
        record = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        self.assertEqual(record.fqdn, 'test-record.test.example.com')

    def test_record_without_type_should_fail(self):
        """Record data without a type should fail"""
        zone = Zone('test.example.com')
        with self.assertRaises(InvalidRecordData) as e:
            Record(zone, 'test-record', {'ttl': 300})
        self.assertEqual('missing key \'type\' in Record data',
                         str(e.exception))

    def test_record_without_ttl_should_fail(self):
        """Record data without a ttl should fail"""
        zone = Zone('test.example.com')
        with self.assertRaises(InvalidRecordData) as e:
            Record(zone, 'test-record', {'type': 'A'})
        self.assertEqual('missing key \'ttl\' in Record data',
                         str(e.exception))

    def test_record_with_invalid_type_should_fail(self):
        """Record can only have a supported type"""
        zone = Zone('test.example.com')
        with self.assertRaises(InvalidRecordType) as e:
            Record(zone, 'test-record', {'type': 'FOO', 'ttl': 300})
        self.assertEqual('Type FOO is not supported', str(e.exception))

    def test_record_without_values(self):
        """Record can have no values"""
        zone = Zone('test.example.com')
        record = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        self.assertListEqual(record.values, [])

    def test_record_returns_values(self):
        """Record can return it's values"""
        zone = Zone('test.example.com')
        record = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        record.add_targets(['1.1.1.1', '2.2.2.2', '3.3.3.3'])
        self.assertListEqual(record.values, ['1.1.1.1', '2.2.2.2', '3.3.3.3'])

    def test_record_eq_record(self):
        """Record with the same type, ttl and values are equal"""
        zone = Zone('test.example.com')
        record_current = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        record_desired = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        self.assertTrue(record_current == record_desired)

    def test_record_eq_record_different_ttl(self):
        """Record with a different TTL is not equal"""
        zone = Zone('test.example.com')
        record_current = Record(zone, 'test-record', {'type': 'A', 'ttl': 30})
        record_desired = Record(zone, 'test-record', {'type': 'A', 'ttl': 300})
        self.assertTrue(record_current != record_desired)

    def test_record_eq_record_different_values(self):
        """Record with different values is not equal"""
        zone = Zone('test.example.com')
        data = {'type': 'A', 'ttl': 30, 'values': ['1.1.1.1', '2.2.2.2']}
        record_current = Record(zone, 'test-record', data)
        data = {'type': 'A', 'ttl': 30, 'values': ['1.1.1.1', '3.3.3.3']}
        record_desired = Record(zone, 'test-record', data)
        self.assertTrue(record_current != record_desired)

    def test_record_eq_record_different_values_order(self):
        """Record with same values in different order is still equal"""
        zone = Zone('test.example.com')
        data = {'type': 'A', 'ttl': 30, 'values': ['1.1.1.1', '2.2.2.2']}
        record_current = Record(zone, 'test-record', data)
        data = {'type': 'A', 'ttl': 30, 'values': ['2.2.2.2', '1.1.1.1']}
        record_desired = Record(zone, 'test-record', data)
        self.assertTrue(record_current == record_desired)

    def test_repr(self):
        """Record is represented properly"""
        zone = Zone('test.example.com')
        record = Record(zone, "test-record", {'type': 'A', 'ttl': 300})
        self.assertEqual(f'{record}', 'Record<A, test-record>')

    def test_repr_apex(self):
        """Record at the apex (empty name) is represented properly"""
        zone = Zone('test.example.com')
        record = Record(zone, '', {'type': 'A', 'ttl': 300})
        self.assertEqual(f'{record}', 'Record<A>')
