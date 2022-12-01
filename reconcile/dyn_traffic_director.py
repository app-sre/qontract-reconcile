# Dirty hack for Python 3.10 to overcome
# ImportError: cannot import name 'Iterable' from 'collections'
# when importing from dyn.tm
import collections.abc
import logging
import warnings
from collections.abc import Mapping
from typing import Any

from reconcile import queries
from reconcile.utils.config import (
    ConfigNotFound,
    get_config,
)
from reconcile.utils.helpers import toggle_logger
from reconcile.utils.secret_reader import SecretReader

collections.Iterable = collections.abc.Iterable  # type: ignore[misc]

# Dirty hack to silence annoying SyntaxWarnings present as of dyn==1.8.1
# which will pollute our CLI output
# PR for fix upstream: https://github.com/dyninc/dyn-python/pull/140
# This is unlikely to be ever fixed as this repo has not been updated in 4 yrs
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from dyn.tm import services as dyn_services
    from dyn.tm import session as dyn_session
    from dyn.tm import zones as dyn_zones
    from dyn.tm.services.dsf import (
        DSFCNAMERecord,
        DSFFailoverChain,
        DSFRecordSet,
        DSFResponsePool,
        DSFRuleset,
        TrafficDirector,
    )
    from dyn.tm.zones import Node

QONTRACT_INTEGRATION = "dyn-traffic-director"

DEFAULT_TD_TTL = 30
DEFAULT_WEIGHT = 100


class InvalidRecord(Exception):
    pass


class UnsupportedRecordType(Exception):
    pass


class DynResourceNotFound(Exception):
    pass


class CreateTrafficDirectorError(Exception):
    pass


class DeleteTrafficDirectorError(Exception):
    pass


class UpdateTrafficDirectorError(Exception):
    pass


def _get_dyn_node(name: str) -> Node:
    """Retrieve a Dyn DNS Node using the Dyn API

    NOTE: A Dyn Session (dyn.tm.session.DynectSession) must have been
          initialized prior to using this method. DynectSession is a singleton
          that does not require to be passed around to call APIs
    """
    zones = dyn_zones.get_all_zones()
    for z in zones:
        for n in z.get_all_nodes():
            if n.fqdn == name:
                return n

    raise DynResourceNotFound(f"could not find a DNS node named {name}")


def _get_dyn_traffic_director_service(name: str) -> TrafficDirector:
    """Retrieve a Dyn Traffic Director Service using the Dyn API

    NOTE: A Dyn Session (dyn.tm.session.DynectSession) must have been
          initialized prior to using this method. DynectSession is a singleton
          that does not require to be passed around to call APIs
    """
    for td in dyn_services.get_all_dsf_services():
        if td.label == name:
            return td

    raise DynResourceNotFound(f"could not find a Traffic Director service named {name}")


def _new_dyn_cname_record(hostname: str, weight: int = 100) -> DSFCNAMERecord:
    """Instantiate an opinionated DSFCNAMERecord object"""
    return DSFCNAMERecord(hostname, weight=weight, label="", automation="manual")


def _new_dyn_traffic_director_service(
    name, ttl=DEFAULT_TD_TTL, records=None, attach_nodes=None
) -> TrafficDirector:
    """Creates an opinionated Dyn Traffic Director service

    - Creates a CNAME recordset
    - Expects all records to be DSFCNAMERecord type
    - Creates a single failover chain pointing to the recordset
    - Creates a single pool pointing to the failover chain
    - Creates a single ruleset that always responds and points to the pool

    NOTE: The dyn module TrafficDirector constructor has side effects and calls
          the Dyn API multiple times. It is possible that Dyn resources are
          created even if the constructor failed
    """

    if records is None:
        records = []
    if attach_nodes is None:
        attach_nodes = []

    try:
        record_set = DSFRecordSet(
            "CNAME", label=name, automation="manual", records=records
        )
        failover_chain = DSFFailoverChain(label=name, record_sets=[record_set])
        rpool = DSFResponsePool(label=name, rs_chains=[failover_chain])
        ruleset = DSFRuleset(label=name, criteria_type="always", response_pools=[rpool])

        # Constructor does the actual resource creation and checking for
        # creation completion.
        # It returns returns a resource ID which we don't need
        return TrafficDirector(name, ttl=ttl, rulesets=[ruleset], nodes=attach_nodes)
    except Exception as e:
        raise CreateTrafficDirectorError(
            f"Exception caught during creation of Traffic Director: {name} "
            f"The exception was: {e}"
        )


def _get_dyn_traffic_director_ruleset(
    td: TrafficDirector, ruleset_label: str
) -> DSFRuleset:
    """Retrieves a ruleset of a TrafficDirector service

    NOTE: A Dyn Session (dyn.tm.session.DynectSession) must have been
          initialized prior to using this method. DynectSession is a singleton
          that does not require to be passed around to call APIs
    """
    for ruleset in td.rulesets:
        if ruleset.label == ruleset_label:
            return ruleset

    raise DynResourceNotFound(
        f"could not find ruleset named {ruleset_label}"
        f"under traffic director service {td.label}"
    )


def _get_dyn_traffic_director_response_pool(
    ruleset: DSFRuleset, rpool_label: str
) -> DSFResponsePool:
    """Retrieves a response pool of a TrafficDirector Ruleset

    NOTE: A Dyn Session (dyn.tm.session.DynectSession) must have been
          initialized prior to using this method. DynectSession is a singleton
          that does not require to be passed around to call APIs
    """
    for rpool in ruleset.response_pools:
        if rpool.label == rpool_label:
            return rpool

    raise DynResourceNotFound(
        f"could not find response pool named {rpool_label}"
        f"under ruleset {ruleset.label}"
    )


def _get_dyn_traffic_director_chain(
    rpool: DSFResponsePool, chain_label: str
) -> DSFFailoverChain:
    """Retrieves a chain of a TrafficDirector Response Pool

    NOTE: A Dyn Session (dyn.tm.session.DynectSession) must have been
          initialized prior to using this method. DynectSession is a singleton
          that does not require to be passed around to call APIs
    """
    for chain in rpool.rs_chains:
        if chain.label == chain_label:
            return chain

    raise DynResourceNotFound(
        f"could not find failover chain named {chain_label}"
        f"under resource pool named {rpool.label}"
    )


def _get_dyn_traffic_director_recordset(
    chain: DSFFailoverChain, rset_label: str
) -> DSFRecordSet:
    """Retrieves a RecordSet of a TrafficDirector Failover Chain

    NOTE: A Dyn Session (dyn.tm.session.DynectSession) must have been
          initialized prior to using this method. DynectSession is a singleton
          that does not require to be passed around to call APIs
    """
    for rset in chain.record_sets:
        if rset.label == rset_label:
            return rset

    raise DynResourceNotFound(
        f"could not find record set named {rset_label}"
        f"under failover chain named {chain.label}"
    )


def _get_dyn_traffic_director_records(
    td: TrafficDirector,
    ruleset_label: str,
    rpool_label: str,
    chain_label: str,
    rset_label: str,
):
    """Retrieves the records of a TrafficDirector service for a given ruleset,
    pool, chain and recordset

    NOTE: A Dyn Session (dyn.tm.session.DynectSession) must have been
          initialized prior to using this method. DynectSession is a singleton
          that does not require to be passed around to call APIs
    """
    # Need to follow the hierarchy
    # TD <- Ruleset -> ResponsePool <- FailoverChain <- RecordSet <- Record
    ruleset = _get_dyn_traffic_director_ruleset(td, ruleset_label)
    rpool = _get_dyn_traffic_director_response_pool(ruleset, rpool_label)
    chain = _get_dyn_traffic_director_chain(rpool, chain_label)
    recordset = _get_dyn_traffic_director_recordset(chain, rset_label)
    return recordset.records


def _update_dyn_traffic_director_records(
    td: TrafficDirector,
    records: list,
    ruleset_label: str,
    rpool_label: str,
    chain_label: str,
    rset_label: str,
):
    """Updates the records of a TrafficDirector service for a given ruleset,
    responsepool and failover chain

    NOTE: This calls the Dyn API to apply the change
    """
    new_rset = DSFRecordSet(
        "CNAME", label=td.label, automation="manual", records=records
    )

    # Need to follow the hierarchy
    # TD <- Ruleset -> ResponsePool <- FailoverChain <- RecordSet <- Record
    ruleset = _get_dyn_traffic_director_ruleset(td, ruleset_label)
    rpool = _get_dyn_traffic_director_response_pool(ruleset, rpool_label)
    chain = _get_dyn_traffic_director_chain(rpool, chain_label)
    current_recordset = _get_dyn_traffic_director_recordset(chain, rset_label)

    new_rset.add_to_failover_chain(chain)

    current_recordset.delete()


def fetch_current_state() -> dict[str, dict]:
    state: dict = {
        "tds": {},
    }

    traffic_directors = dyn_services.get_all_dsf_services()
    for td in traffic_directors:
        td_name = td.label
        td_nodes = [node["fqdn"] for node in td.nodes]
        td_ttl = td.ttl
        td_records = _get_dyn_traffic_director_records(
            td,
            ruleset_label=td_name,
            rpool_label=td_name,
            chain_label=td_name,
            rset_label=td_name,
        )

        records: list[dict[str, Any]] = []
        for record in td_records:
            rdata = record.rdata()
            if "cname_rdata" not in rdata:
                raise UnsupportedRecordType(
                    f"record type {type(record)} is not " f"supported: {record}"
                )

            cname_rdata = record.rdata()["cname_rdata"]
            if "cname" not in cname_rdata:
                raise UnsupportedRecordType(f"record missing a cname field: {record}")

            records.append(
                {
                    # strip trailing dot added by Dyn
                    "hostname": cname_rdata["cname"].rstrip("."),
                    "weight": int(cname_rdata.get("weight", DEFAULT_WEIGHT)),
                }
            )

        # need to be sorted for comparison later
        records.sort(key=lambda d: d["hostname"])

        state["tds"][td_name] = {
            "name": td_name,
            "nodes": td_nodes,
            "ttl": td_ttl,
            "records": records,
        }

    return state


def fetch_desired_state() -> dict[str, dict]:
    dyn_tds = queries.get_dyn_traffic_directors()

    state: dict = {
        "tds": {},
    }

    for td in dyn_tds:
        td_name: str = td["name"]
        td_records: list[dict] = td.get("records", [])
        td_ttl: int = td.get("ttl", DEFAULT_TD_TTL)

        records: list[dict[str, Any]] = []
        for record in td_records:
            if record["cluster"]:
                hostname = record["cluster"]["elbFQDN"]
            elif record["hostname"]:
                hostname = record["hostname"]
            else:
                raise InvalidRecord(
                    "either cluster or hostname must "
                    f"be defined on a record. Got: {record}"
                )
            records.append(
                {
                    "hostname": hostname.rstrip("."),
                    "weight": record["weight"],
                }
            )

        # need to be sorted for comparison later
        records.sort(key=lambda d: d["hostname"])

        state["tds"][td_name] = {
            "name": td_name,
            "nodes": [td_name],
            "ttl": td_ttl,
            "records": records,
        }

    return state


def create_td(name: str, ttl: int, records: list[dict[str, Any]], dry_run: bool):
    """Create a new Traffic Director service

    Returns whether errors have been encountered during processing
    """
    logging.info(["create_td", name])

    # Generate list of Dyn records from the desired records
    td_records = [
        _new_dyn_cname_record(r["hostname"], weight=r["weight"]) for r in records
    ]

    # Find the DNS node to attach to
    attach_node = _get_dyn_node(name)

    if dry_run:
        return

    # Create the new TD service
    td = _new_dyn_traffic_director_service(
        name, ttl=ttl, records=td_records, attach_nodes=[attach_node]
    )
    if not td:
        raise CreateTrafficDirectorError(f"Could not create Traffic Director {name}")


def delete_td(name: str, dry_run: bool, enable_deletion=False):
    logging.info(["delete_td", name])

    if not enable_deletion:
        logging.info(
            "deletion action is disabled. " "Delete manually or enable deletion."
        )
        return

    if dry_run:
        return

    # Find the TD service to delete and delete it
    td = _get_dyn_traffic_director_service(name)
    if not td:
        raise DeleteTrafficDirectorError(
            f"Could not find Traffic Director service: {name}"
        )

    td.delete()


def update_td(
    name: str, current: Mapping[str, Any], desired: Mapping[str, Any], dry_run: bool
):
    # Find TD service to update
    td = _get_dyn_traffic_director_service(name)
    if not td:
        raise UpdateTrafficDirectorError(
            f"Could not find Traffic Director service: {name}"
        )

    # Check if ttl need to be updated
    current_ttl = current["ttl"]
    desired_ttl = desired["ttl"]
    if current_ttl != desired_ttl:
        logging.info(["update_td_ttl", name, desired_ttl])

        if not dry_run:
            td.ttl = desired_ttl

    # Check if records need to be updated
    current_records = current["records"]
    desired_records = desired["records"]
    if current_records != desired_records:
        logging.info(["update_td_records", name, desired_records])

        if not dry_run:
            # Generate a new list of CNAME records
            records = [
                _new_dyn_cname_record(r["hostname"], weight=r["weight"])
                for r in desired_records
            ]

            _update_dyn_traffic_director_records(
                td,
                records,
                ruleset_label=name,
                rpool_label=name,
                chain_label=name,
                rset_label=name,
            )

    # Check if node attachment need to be updated
    current_nodes = current["nodes"]
    desired_nodes = desired["nodes"]
    if current_nodes != desired_nodes:
        logging.info(["update_td_node", name, desired_nodes])

        if not dry_run:
            # Find the DNS node to attach the TD service to
            attach_node = _get_dyn_node(name)
            if not attach_node:
                raise UpdateTrafficDirectorError(f"Could not find DNS node {name}")
            td.nodes = [attach_node]


def process_tds(
    current: Mapping[str, Mapping[str, Any]],
    desired: Mapping[str, Mapping[str, Any]],
    dry_run: bool = True,
    enable_deletion: bool = False,
) -> None:
    added = list(desired.keys() - current.keys())
    removed = list(current.keys() - desired.keys())
    changed = [
        dname
        for dname, d in desired.items()
        for cname, c in current.items()
        if dname == cname
        if d != c
    ]

    # Process added TD services
    for name in added:
        try:
            create_td(name, desired[name]["ttl"], desired[name]["records"], dry_run)
        except Exception as e:
            # We do not want to proceed with deleting or updating TD services
            # if we failed to create new ones. This is because renaming a TD
            # service essentially is a "create new & delete old" operation
            logging.exception(e)
            logging.error(
                "Errors occurred during creation of new Traffic Director. "
                "Aborting before delete and update phases"
            )
            return

    # Process removed TD services
    for name in removed:
        delete_td(name, dry_run, enable_deletion)

    # Process updated TD services
    for name in changed:
        update_td(name, current[name], desired[name], dry_run)


def run(dry_run: bool, enable_deletion: bool):
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)

    creds_path = get_config().get("dyn", {}).get("secrets_path", None)
    if not creds_path:
        raise ConfigNotFound("Dyn config missing from config file")

    creds = secret_reader.read_all({"path": creds_path})
    # avoid logging these info messages
    # INFO Establishing SSL connection to api.dynect.net:443
    # INFO DynectSession Authentication Successful
    try:
        with toggle_logger():
            dyn_session.DynectSession(
                creds["customer"], creds["dyn_id"], creds["password"]
            )

        desired = fetch_desired_state()
        current = fetch_current_state()

        process_tds(
            current["tds"],
            desired["tds"],
            dry_run=dry_run,
            enable_deletion=enable_deletion,
        )

    # Dyn client internally uses singleton per thread, this means SessionEngine is initialized once and cached for
    # later use. The client it uses HTTPSConnection (part of http library) and only initializes it once.
    # A singleton HTTPSConnection object is responsible for only creating a single underlying socket connection.
    # The HTTPSConnection object keeps track state with values such
    #   - _CS_IDLE (indicates idle connection)
    #   - _CS_REQ_STARTED (indicates request started. used when sending initial headers)
    #   - _CS_REQ_SENT (initial headers sent)
    # More info on this can be found in client.py

    # So when Dyn API is unavailable, the http client sends a request but runs into `OSError: [Errno 101] Network is
    # unreachable`. This exception is not caught anywhere (blame send_command method within SessionEngine.execute() )
    # So the 1st reconciliation run fails. At this point the HTTPSConnection state is _CS_REQ_SENT. When the 2nd
    # reconciliation run starts, the SessionEngine object is reused. And when it's time to send request Dyn client
    # internally ends up calling put HTTPConnection.putrequest() which throws error (CannotSendRequest) if state is
    # not _CS_IDLE.

    # This is why we need to catch IOError/OSError and make sure we delete the singleton and recreate it on next run
    # to avoid manual pod restart.

    except IOError as e:
        logging.warning(e)
        logging.debug(
            "Deleting Dyn client singleton because of IOError. The next reconciliation run will recreate it."
        )
        dyn_session.DynectSession.close_session()


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    return {
        "traffic_directors": queries.get_dyn_traffic_directors(),
    }
