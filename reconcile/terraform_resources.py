import logging
import sys
import tempfile
import shutil
import random
import string
import base64
import semver

import utils.gql as gql
import utils.vault_client as vault_client
import reconcile.openshift_resources as openshift_resources

from utils.oc import OC, StatusCodeError
from utils.config import get_config
from utils.openshift_resource import ResourceInventory

from python_terraform import *
from terrascript import Terrascript, provider, terraform, backend, output
from terrascript.aws.r import aws_db_instance

TF_QUERY = """
{
  namespaces {
    name
    terraformResources {
      provider
      ... on NamespaceTerraformResourceRDS_v1 {
        identifier
        name
        engine
        engine_version
        username
      }
    }
    cluster {
      name
      serverUrl
      automationToken {
        path
        field
        format
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'terraform_resources'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)

_working_dir = None


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super(UnknownProviderError, self).__init__(
            "unknown provider error: " + str(msg)
        )


def get_vault_tf_secret(type):
    config = get_config()
    secrets_path = config['terraform']['secrets_path']
    return vault_client.read_all(secrets_path + '/' + type)


def bootstrap_config():
    config = get_vault_tf_secret('config')
    ts = Terrascript()
    ts += provider('aws',
                   access_key=config['aws_access_key_id'],
                   secret_key=config['aws_secret_access_key'],
                   version=config['aws_provider_version'],
                   region=config['region'])
    b = backend("s3",
                access_key=config['aws_access_key_id'],
                secret_key=config['aws_secret_access_key'],
                bucket=config['bucket'],
                key=config['key'],
                region=config['region'])
    ts += terraform(backend=b)

    return ts


def adjust_tf_query(tf_query):
    out_tf_query = []
    for namespace_info in tf_query:
        tf_resources = namespace_info.get('terraformResources')
        # Skip if namespace has no terraformResources
        if not tf_resources:
            continue
        # adjust to match openshift_resources functions
        namespace_info['managedResourceTypes'] = ['Secret']
        out_tf_query.append(namespace_info)

    return out_tf_query


def get_spec_by_namespace(state_specs, namespace_info):
    cluster = namespace_info['cluster']['name']
    namespace = namespace_info['name']
    specs = [s for s in state_specs \
        if s.cluster == cluster and s.namespace == namespace]
    # since we exactly one combination of cluster/namespace
    # we can return the first (and only) item in the list
    return specs[0]


def fetch_existing_oc_resource(spec, resource_name):
    try:
        return spec.oc.get(spec.namespace, spec.resource, resource_name)
    except StatusCodeError as e:
        if e.message.startswith('Error from server (NotFound):'):
            msg = 'Secret {} does not exist.'.format(resource_name)
            logging.debug(msg)
    return None


def generate_random_password(string_length=20):
    """Generate a random string of letters and digits """
    letters_and_digits = string.ascii_letters + string.digits
    return ''.join(random.choice(letters_and_digits) \
        for i in range(string_length))


def determine_rds_db_password(spec, existing_resource):
    password = generate_random_password()
    if existing_resource is not None:
        enc_password = existing_resource['data']['db.password']
        password = base64.b64decode(enc_password)
    return password

    # TODO: except KeyError?
    # a KeyError will indicate that this secret
    # exists, but the db.password field is missing.
    # this could indicate that a secret with this
    # this name is 'taken', or that the secret
    # was updated manually. at this point, it may
    # be better to let the exception stop the process.
    # for now, we assume a happy path, where there is
    # no competition over secret names, but we should
    # circle back here at a later point.


def fetch_tf_resource_rds(resource, spec):
    # get values from gql query
    # deafult engine is postgres
    # the engine is also the default name and username
    identifier = resource['identifier']
    re = resource['engine']
    engine = 'postgres' if re is None else re
    rn = resource['name']
    name = engine if rn is None else rn
    ru = resource['username']
    username = engine if ru is None else ru
    engine_version = resource['engine_version']
    output_resource_name = identifier + '-rds'
    # get values from vault tf secret
    variables = get_vault_tf_secret('variables')
    db_subnet_group_name = variables['rds-subnet-group']
    vpc_security_group_ids = variables['rds-security-groups'].split(',')

    existing_oc_resource = \
        fetch_existing_oc_resource(spec, output_resource_name)
    password = determine_rds_db_password(spec, existing_oc_resource)

    kwargs = {
        # default values
        # these can be later exposed to users
        'instance_class': 'db.t2.small',
        'allocated_storage': 20,
        'storage_encrypted': True,
        'auto_minor_version_upgrade': False,
        'skip_final_snapshot': True,
        'backup_retention_period': 7,
        'storage_type': 'gp2',
        'multi_az': False,
        # calculated values
        'identifier': identifier,
        'engine': engine,
        'name': name,
        'username': username,
        'password': password,
        'db_subnet_group_name': db_subnet_group_name,
        'vpc_security_group_ids': vpc_security_group_ids,
    }
    if engine_version is not None:
        kwargs['engine_version'] = engine_version

    tf_resource = aws_db_instance(identifier, **kwargs)

    tf_outputs = []
    tf_outputs.append(output(output_resource_name + \
        '[db.host]', value='${' + tf_resource.fullname + '.address}'))
    tf_outputs.append(output(output_resource_name + \
        '[db.port]', value='${' + tf_resource.fullname + '.port}'))
    tf_outputs.append(output(output_resource_name \
        + '[db.name]', value=name))
    tf_outputs.append(output(output_resource_name + \
        '[db.user]', value=username))
    tf_outputs.append(output(output_resource_name + \
        '[db.password]', value=password))
    return tf_resource, tf_outputs, existing_oc_resource


def fetch_tf_resource(resource, spec):
    provider = resource['provider']
    if provider == 'rds':
        tf_resource, tf_outputs, oc_resource = \
            fetch_tf_resource_rds(resource, spec)
    else:
        raise UnknownProviderError(provider)

    return tf_resource, tf_outputs, oc_resource


def add_resources(ts, ri):
    gqlapi = gql.get_api()
    tf_query = gqlapi.query(TF_QUERY)['namespaces']
    tf_query = adjust_tf_query(tf_query)

    state_specs = \
        openshift_resources.init_specs_to_fetch(ri, {}, tf_query)

    for namespace_info in tf_query:
        spec = get_spec_by_namespace(state_specs, namespace_info)
        tf_resources = namespace_info.get('terraformResources')
        for resource in tf_resources:
            tf_resource, tf_outputs, oc_resource = \
                fetch_tf_resource(resource, spec)
            ts.add(tf_resource)
            for tf_output in tf_outputs:
                ts.add(tf_output)
            if oc_resource is None:
                continue
            openshift_resource = openshift_resources.OR(oc_resource)
            ri.add_current(
                spec.cluster,
                spec.namespace,
                spec.resource,
                openshift_resource.name,
                openshift_resource
            )


def write_to_tmp_file(ts):
    global _working_dir

    _working_dir = tempfile.mkdtemp()
    with open(_working_dir + '/config.tf', 'w') as f:
        f.write(ts.dump())


def setup():
    ts = bootstrap_config()
    ri = ResourceInventory()
    add_resources(ts, ri)
    ts.validate()
    write_to_tmp_file(ts)
    print(ts.dump())


def check_tf_output(return_code, stdout, stderr):
    for line in stdout.split('\n'):
        if len(line) == 0:
            continue
        logging.debug(line)
    if return_code != 0 and len(stderr) != 0:
        for line in stderr.split('\n'):
            if len(line) == 0:
                continue
            logging.error(stderr)
        cleanup()
        sys.exit(return_code)


def log_diff(stdout):
    for line in stdout.split('\n'):
        if line.startswith('+ aws'):
            line_split = line.replace('+ ', '').split('.')
            logging.info(['create', line_split[0], line_split[1]])
        if line.startswith('- aws'):
            line_split = line.replace('- ', '').split('.')
            logging.info(['destroy', line_split[0], line_split[1]])
        if line.startswith('~ aws'):
            line_split = line.replace('~ ', '').split('.')
            logging.info(['update', line_split[0], line_split[1]])


def tf_init():
    global _working_dir

    tf = Terraform(working_dir=_working_dir)
    return_code, stdout, stderr = tf.init()
    check_tf_output(return_code, stdout, stderr)

    return tf


def tf_plan(tf):
    return_code, stdout, stderr = tf.plan(detailed_exitcode=False)
    check_tf_output(return_code, stdout, stderr)
    log_diff(stdout)


def tf_apply(tf):
    return_code, stdout, stderr = tf.apply(auto_approve=True)
    check_tf_output(return_code, stdout, stderr)


def cleanup():
    global _working_dir

    shutil.rmtree(_working_dir)


def run(dry_run=False):
    setup()
    tf = tf_init()
    tf_plan(tf)
    return

    if not dry_run:
        tf_apply(tf)

    cleanup()
