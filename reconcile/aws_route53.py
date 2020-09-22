import logging
import re
import semver
import sys

import reconcile.queries as queries

from reconcile.status import ExitCodes
from utils.aws_api import AWSApi

from utils.aws.route53 import State, Account, Record, Zone
from utils.aws.route53 import DuplicateException


QONTRACT_INTEGRATION = 'aws-route53'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)

DEFAULT_RECORD_TTL = 300


def create_zone(dry_run, awsapi, account, zone):
    """
    Create a DNS zone (callable action)

    :param dry_run: Do not execute for real
    :param awsapi: the AWS api object to use to call AWS
    :param account: the aws account to operate on
    :param zone: the DNS zone to create
    :type dry_run: bool
    :type awsapi: AWSApi
    :type account: Account
    :type zone: Zone
    """
    logging.info(f'[{account.name}] Create {zone}')
    if not dry_run:
        awsapi.create_route53_zone(account.name, zone.name)


def delete_zone(dry_run, awsapi, account, zone):
    """
    Delete a DNS zone (callable action)

    :param dry_run: Do not execute for real
    :param awsapi: the AWS api object to use to call AWS
    :param account: the aws account to operate on
    :param zone: the DNS zone to delete
    :type dry_run: bool
    :type awsapi: AWSApi
    :type account: Account
    :type zone: Zone
    """
    logging.info(f'[{account.name}] Delete {zone}')
    if not dry_run:
        awsapi.delete_route53_zone(account.name, zone.data.get('Id'))


def create_record(dry_run, awsapi, account, zone, record):
    """
    Create a DNS record (callable action)

    :param dry_run: Do not execute for real
    :param awsapi: the AWS api object to use to call AWS
    :param account: the aws account to operate on
    :param zone: the DNS zone to operate on
    :param record: the DNS record to delete
    :type dry_run: bool
    :type awsapi: AWSApi
    :type account: Account
    :type zone: Zone
    :type record: Record
    """
    logging.info(f'[{account.name}] Create {record} in {zone}')

    zone_id = zone.data.get('Id')
    if not zone_id:
        logging.error(
            f'[{account.name}] Cannot create {record} in {zone}: '
            f'missing Id key in zone data'
        )
        return

    if not dry_run:
        awsapi.upsert_route53_record(
            account.name,
            zone_id,
            {
                'Name': f'{record.name}.{zone.name}',
                'Type': record.type,
                'TTL': record.ttl,
                'ResourceRecords': [{'Value': v} for v in record.values]
            }
        )


def update_record(dry_run, awsapi, account, zone, recordset):
    """
    Update a DNS record (callable action)

    :param dry_run: Do not execute for real
    :param awsapi: the AWS api object to use to call AWS
    :param account: the aws account to operate on
    :param zone: the DNS zone to operate on
    :param recordset: a tuple comprised of the desired and current record
    :type dry_run: bool
    :type awsapi: AWSApi
    :type account: Account
    :type zone: Zone
    :type recordset: (Record, Record)
    """
    desired_record = recordset[0]
    current_record = recordset[1]
    logging.info(f'[{account.name}] Update {current_record} in {zone}')
    logging.info(f'  Current: {current_record.name} {current_record.type} '
                 f'{current_record.ttl} {current_record.values}')
    logging.info(f'  Desired: {desired_record.name} {desired_record.type} '
                 f'{desired_record.ttl} {desired_record.values}')

    zone_id = zone.data.get('Id')
    if zone_id is None:
        logging.error(
            f'[{account.name}] Cannot update {current_record} in {zone}: '
            f'missing Id key in zone data'
        )
        return

    if not dry_run:
        awsapi.upsert_route53_record(
            account.name,
            zone_id,
            {
                'Name': f'{desired_record.name}.{zone.name}',
                'Type': desired_record.type,
                'TTL': desired_record.ttl,
                'ResourceRecords': [
                    {'Value': v} for v in desired_record.values
                ]
            }
        )


def delete_record(dry_run, awsapi, account, zone, record):
    """
    Delete a DNS record (callable action)

    :param dry_run: Do not execute for real
    :param awsapi: the AWS api object to use to call AWS
    :param account: the aws account to operate on
    :param zone: the DNS zone to operate on
    :param record: the DNS record to delete
    :type dry_run: bool
    :type awsapi: AWSApi
    :type account: Account
    :type zone: Zone
    :type record: Record
    """
    logging.info(f'[{account.name}] Delete {record} from {zone}')

    zone_id = zone.data.get('Id')
    if not zone_id:
        logging.error(
            f'[{account.name}] Cannot delete {record} in {zone}: '
            f'missing Id key in zone data'
        )
        return

    if not dry_run:
        awsapi.delete_route53_record(
            account.name, zone_id, record.awsdata
        )


def removesuffix(s, suffix):
    """
    Removes suffix a string

    :param s: string to remove suffix from
    :param suffix: suffix to remove
    :type s: str
    :type suffix: str
    :return: a copy of the string with the suffix removed
    :rtype: str
    """
    return s if not s.endswith(suffix) else s[:-len(suffix)]


def build_current_state(awsapi):
    """
    Build a State object that represents the current state

    :param awsapi: the aws API object to use
    :type awsapi: AWSApi
    :return: returns a tuple that contains the State object and whether there \
        were any errors
    :rtype: (State, bool)
    """
    state = State('aws')
    errors = False

    awsapi.map_route53_resources()
    aws_state = awsapi.get_route53_zones()

    for account_name, zones in aws_state.items():
        account = Account(account_name)
        for zone in zones:
            zone_name = zone['Name']
            new_zone = Zone(zone_name, zone)
            for record in zone['records']:
                # Can't manage SOA records, so ignore it
                if record['Type'] in ['SOA']:
                    continue
                # Can't manage NS records at apex, so ignore them
                if record['Type'] == 'NS' and record['Name'] == zone_name:
                    continue

                record_name = removesuffix(record['Name'], zone_name)
                new_record = Record(new_zone, record_name, {
                    'type': record['Type'],
                    'ttl': record['TTL'],
                    'values': [v['Value'] for v in record['ResourceRecords']],
                }, record)
                new_zone.add_record(new_record)

            account.add_zone(new_zone)

        state.add_account(account)

    return state, errors


def build_desired_state(zones):
    """
    Build a State object that represents the desired state

    :param zones: a representation of DNS zones as retrieved from app-interface
    :type zones: dict
    :return: returns a tuple that contains the State object and whether there \
        were any errors
    :rtype: (State, bool)
    """
    state = State('app-interface')
    errors = False

    for zone in zones:
        account_name = zone['account']['name']

        account = state.get_account(account_name)
        if not account:
            account = Account(account_name)

        new_zone = Zone(zone['name'], zone)

        for record in zone['records']:
            new_record = Record(new_zone, record['name'], {
                'type': record['type'],
                'ttl': record['ttl'] or DEFAULT_RECORD_TTL
            }, record)

            targets = []

            record_target = record.get('target')
            if record_target:
                if record['type'] == 'TXT':
                    # TXT records values need to be enclosed in double quotes
                    targets.append(f'"{record_target}"')
                else:
                    targets.append(record_target)

            record_targets = record.get('targets')
            if record_targets:
                targets.extend(record_targets)

            record_target_cluster = record.get('target_cluster')
            if record_target_cluster:
                cluster = record_target_cluster
                cluster_name = cluster['name']
                elb_fqdn = cluster.get('elbFQDN')
                if not elb_fqdn:
                    logging.error(
                        f'[{account}] elbFQDN not set for cluster '
                        f'{cluster_name}'
                    )
                    errors = True
                    continue
                targets.append(elb_fqdn)

            if not targets:
                logging.error(
                    f'[{account}] no targets found for '
                    f'{new_record} in {new_zone}'
                )
                errors = True
                continue
            new_record.add_targets(targets)
            new_zone.add_record(new_record)

        try:
            account.add_zone(new_zone)
        except DuplicateException as e:
            logging.error(e)
            errors = True

        if not state.get_account(account_name):
            state.add_account(account)

    return state, errors


def diff_sets(desired, current):
    """
    Diff two state dictionaries by key

    :param desired: the desired state
    :param current: the current state
    :type desired: dict
    :type current: dict
    :return: returns a tuple that contains lists of added, removed and \
        changed elements from the desired dict
    :rtype: (list, list, list)
    """
    added = [desired[item] for item in desired if item not in current]
    removed = [current[item] for item in current if item not in desired]

    changed = []
    common = [(desired[item], current[item])
              for item in current if item in desired]
    for item in common:
        if not item[0] == item[1]:
            # Append the desired item set to changed zones list
            changed.append(item)

    return added, removed, changed


def reconcile_state(current_state, desired_state):
    """
    Reconcile the state between current and desired State objects

    :param current_state: the current state
    :param desired_state: the desired_state state
    :type desired: State
    :type current: State
    :return: a list of AWS API actions to run and whether there were any errors
    :rtype: (list, bool)
    """
    actions = []
    errors = False

    for desired_account in desired_state.accounts.values():
        current_account = current_state.get_account(desired_account.name)

        new_zones = []
        add, rem, _ = diff_sets(desired_account.zones, current_account.zones)
        for zone in rem:
            # Removed zones
            for _, record in zone.records.items():
                actions.append((delete_record, current_account, zone, record))
            actions.append((delete_zone, current_account, zone))
        for zone in add:
            # New zones
            new_zones.append(zone.name)
            actions.append((create_zone, current_account, zone))

        for _, zone in desired_account.zones.items():
            current_zone = current_account.get_zone(zone.name)

            if not zone.records:
                # No records defined, so we skip it (and don't manage records)
                continue

            if zone.name in new_zones and current_zone is None:
                # This is a new zone to be created and thus we don't have
                # a Route53 zone ID yet. Skip creating the records for now,
                # they will be created on the next run
                # TODO: Find a way to create the records on the same run?
                continue

            # Check if we have unmanaged_record_names (urn) and compile them
            # all as regular expressions
            urn_compiled = []
            if 'unmanaged_record_names' in zone.data:
                for urn in zone.data['unmanaged_record_names']:
                    urn_compiled.append(re.compile(urn))

            for record in zone.records.values():
                for regex in urn_compiled:
                    if regex.fullmatch(record.name):
                        logging.debug(f'{desired_account} excluding unmanaged '
                                      f'record {record} because it matched '
                                      f'unmanaged_record_names pattern '
                                      f'\'{regex.pattern}\'')
                        zone.remove_record(record.name)
                        current_zone.remove_record(record.name)

            add, remove, update = diff_sets(zone.records, current_zone.records)
            for record in remove:
                # Removed records
                actions.append(
                    (delete_record, current_account, current_zone, record))
            for record in add:
                # New records
                actions.append(
                    (create_record, current_account, current_zone, record))
            for recordset in update:
                # Updated records
                actions.append(
                    (update_record, current_account, current_zone, recordset))

    return actions, errors


def run(dry_run=False, thread_pool_size=10):
    settings = queries.get_app_interface_settings()
    zones = queries.get_dns_zones()

    desired_state, err = build_desired_state(zones)
    if err:
        sys.exit(ExitCodes.ERROR)

    participating_accounts = [z['account'] for z in zones]
    awsapi = AWSApi(thread_pool_size, participating_accounts, settings)
    current_state, err = build_current_state(awsapi)
    if err:
        sys.exit(ExitCodes.ERROR)

    actions, err = reconcile_state(current_state, desired_state)
    if err:
        sys.exit(ExitCodes.ERROR)

    for action in actions:
        err = action[0](dry_run, awsapi, *action[1:])
        if err:
            sys.exit(ExitCodes.ERROR)
