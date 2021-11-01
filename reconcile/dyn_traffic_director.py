import logging
from typing import Dict, List, Union
import warnings

from reconcile import queries
from reconcile.utils.config import ConfigNotFound, get_config
from reconcile.utils.secret_reader import SecretReader

# Dirty hack to silence annoying SyntaxWarnings present as of dyn==1.8.1
# which will pollute our CLI output
# PR for fix upstream: https://github.com/dyninc/dyn-python/pull/140
# This is unlikely to be ever fixed as this repo has not been updated in 4 yrs
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    from dyn.tm import session as dyn_session  # type: ignore
    from dyn.tm import services as dyn_services  # type: ignore
    from dyn.tm import zones as dyn_zones  # type: ignore
    from dyn.tm.services.dsf import DSFCNAMERecord  # type: ignore
    from dyn.tm.services.dsf import DSFFailoverChain  # type: ignore
    from dyn.tm.services.dsf import DSFRecordSet  # type: ignore
    from dyn.tm.services.dsf import DSFResponsePool  # type: ignore
    from dyn.tm.services.dsf import DSFRuleset  # type: ignore
    from dyn.tm.services.dsf import TrafficDirector  # type: ignore

QONTRACT_INTEGRATION = 'dyn-traffic-director'

DEFAULT_TD_TTL = 30
DEFAULT_WEIGHT = 100


class InvalidRecord(Exception):
    pass


class UnsupportedRecordType(Exception):
    pass


def fetch_current_state() -> Dict[str, Dict]:
    state: dict = {
        'tds': {},
    }

    for td in dyn_services.get_all_dsf_services():
        td_name: str = td.label
        td_nodes: List[str] = [node['fqdn'] for node in td.nodes
                               if 'fqdn' in node]
        td_ttl: int = td.ttl

        records: List[Dict[str, Union[str, int]]] = []
        # Need to follow the hierarchy, even though the one we create/manage
        # is flat (only one of each)
        # TD <- Ruleset -> ResponsePool <- FailoverChain <- RecordSet <- Record
        for ruleset in td.rulesets:
            for pool in ruleset.response_pools:
                for chain in pool.rs_chains:
                    for recordset in chain.record_sets:
                        for record in recordset.records:
                            rdata = record.rdata()
                            if 'cname_rdata' not in rdata:
                                raise UnsupportedRecordType(
                                    f'record type {type(record)} is not '
                                    f'supported: {record}'
                                )

                            cname_rdata = record.rdata()['cname_rdata']
                            if 'cname' not in cname_rdata:
                                raise UnsupportedRecordType(
                                    f'record missing a cname field: {record}'
                                )

                            records.append({
                                'hostname':
                                # strip trailing dot added by Dyn
                                cname_rdata['cname'].rstrip('.'),
                                'weight':
                                int(cname_rdata.get('weight', DEFAULT_WEIGHT)),
                            })

        # need to be sorted for comparison later
        records.sort(key=lambda d: d['hostname'])

        state['tds'][td_name] = {
            'name': td_name,
            'nodes': td_nodes,
            'ttl': td_ttl,
            'records': records,
        }

    return state


def fetch_desired_state() -> Dict[str, Dict]:
    dyn_tds = queries.get_dyn_traffic_directors()

    state: dict = {
        'tds': {},
    }

    for td in dyn_tds:
        td_name: str = td['name']
        td_records: List[Dict] = td.get('records', [])
        td_ttl: int = td.get('ttl', DEFAULT_TD_TTL)

        records: List[Dict[str, Union[str, int]]] = []
        for record in td_records:
            if record['cluster']:
                hostname = record['cluster']['elbFQDN']
            elif record['hostname']:
                hostname = record['hostname']
            else:
                raise InvalidRecord('either cluster or hostname must '
                                    f'be defined on a record. Got: {record}')
            records.append({
                'hostname': hostname.rstrip('.'),
                'weight': record['weight'],
            })

        # need to be sorted for comparison later
        records.sort(key=lambda d: d['hostname'])

        state['tds'][td_name] = {
            'name': td_name,
            'nodes': [td_name],
            'ttl': td_ttl,
            'records': records,
        }

    return state


def process_tds(current: dict, desired: dict,
                dry_run: bool = True, enable_deletion: bool = False) -> bool:
    errors = False

    added: List[str] = [name for name in desired if name not in current]
    removed: List[str] = [name for name in current if name not in desired]
    changed: List[str] = [
        dname
        for dname, d in desired.items()
        for cname, c in current.items()
        if dname == cname if d != c
    ]

    # Process removed TD services
    for name in removed:
        td_name = current[name]['name']
        msg = ['delete_td']
        msg.append(name)
        logging.info(msg)

        if not enable_deletion:
            logging.info('deletion action is disabled. '
                         'Delete manually or enable deletion.')

        if dry_run:
            continue

        if not enable_deletion:
            continue

        for curtd in dyn_services.get_all_dsf_services():
            if curtd.label == td_name:
                curtd.delete()

    # Process added TD services
    for name in added:
        td_name = desired[name]['name']
        td_ttl = desired[name]['ttl']
        td_records = desired[name]['records']

        msg = ['create_td']
        msg.append(name)
        logging.info(msg)

        records = []
        for record in td_records:
            records.append(
                DSFCNAMERecord(record['hostname'], label='',
                               automation='manual', weight=record['weight'])
            )

        attach_node = None
        zones = dyn_zones.get_all_zones()
        for zone in zones:
            for node in zone.get_all_nodes():
                if node.fqdn == td_name:
                    attach_node = node

        if not attach_node:
            logging.error(
                f"Could not find a DNS node named '{name}' to attach to"
            )
            errors = True

        if dry_run:
            continue

        record_set = DSFRecordSet('CNAME', label=td_name,
                                  automation='manual', records=records)
        failover_chain = DSFFailoverChain(label=td_name,
                                          record_sets=[record_set])
        rpool = DSFResponsePool(label=td_name, rs_chains=[failover_chain])
        ruleset = DSFRuleset(label=td_name, criteria_type='always',
                             response_pools=[rpool])
        TrafficDirector(td_name, ttl=td_ttl, rulesets=[ruleset],
                        nodes=[attach_node])

    # Process updated TD services
    for name in changed:
        # Find TD service to update
        update_td: TrafficDirector = None
        for td in dyn_services.get_all_dsf_services():
            if td.label == name:
                update_td = td

        # Check if ttl need to be updated
        if current[name]['ttl'] != desired[name]['ttl']:
            msg = ['update_td_ttl']
            msg.append(name)
            msg.append(desired[name]['ttl'])
            logging.info(msg)

            if not dry_run:
                update_td.ttl = desired[name]['ttl']

        # Check if records need to be updated
        if current[name]['records'] != desired[name]['records']:
            msg = ['update_td_records']
            msg.append(name)
            msg.append(desired[name]['records'])
            logging.info(msg)

            if not dry_run:
                # Generate a new list of CNAME records
                records = []
                for record in desired[name]['records']:
                    records.append(
                        DSFCNAMERecord(record['hostname'], label='',
                                       automation='manual',
                                       weight=record['weight'])
                    )

                # Generate a new recordset
                new_rset = DSFRecordSet('CNAME', label=desired[name]['name'],
                                        automation='manual',
                                        records=records)
                # ... must follow the hierarchy
                # TD <- Ruleset -> ResponsePool <- FailoverChain <- RecordSet
                for ruleset in update_td.rulesets:
                    for pool in ruleset.response_pools:
                        for chain in pool.rs_chains:
                            for rset in chain.record_sets:
                                if rset.label == desired[name]['name']:
                                    new_rset.add_to_failover_chain(chain)
                                    rset.delete()

        # Check if node attachment need to be updated
        if current[name]['nodes'] != desired[name]['nodes']:
            msg = ['update_td_node']
            msg.append(name)
            msg.append(desired[name]['nodes'])
            logging.info(msg)

            if not dry_run:
                # Find the DNS node to attach the TD service to
                attach_node = None
                zones = dyn_zones.get_all_zones()
                for zone in zones:
                    for node in zone.get_all_nodes():
                        if node.fqdn == desired[name]['name']:
                            attach_node = node

                if not attach_node:
                    logging.error(
                        f"Could not find a node named '{name}' to attach to"
                    )
                    errors = True

                update_td.nodes = [attach_node]

    return errors


def run(dry_run: bool, enable_deletion: bool):
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)

    creds_path = get_config().get('dyn', {}).get('secrets_path', None)
    if not creds_path:
        raise ConfigNotFound("Dyn config missing from config file")

    creds = secret_reader.read_all({'path': creds_path})
    dyn_session.DynectSession(creds['customer'],
                              creds['dyn_id'],
                              creds['password'])

    desired = fetch_desired_state()
    current = fetch_current_state()

    process_tds(current['tds'], desired['tds'],
                dry_run=dry_run,
                enable_deletion=enable_deletion)
