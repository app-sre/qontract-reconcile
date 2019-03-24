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
from terrascript import Terrascript, provider, terraform, backend
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


def bootstrap_config():
    config = get_config()
    secrets_path = config['terraform']['secrets_path']
    secret = vault_client.read_all(secrets_path + '/config')
    ts = Terrascript()
    ts += provider('aws',
                   access_key=secret['aws_access_key_id'],
                   secret_key=secret['aws_secret_access_key'],
                   version=secret['aws_provider_version'],
                   region=secret['region'])
    b = backend("s3",
                access_key=secret['aws_access_key_id'],
                secret_key=secret['aws_secret_access_key'],
                bucket=secret['bucket'],
                key=secret['key'],
                region=secret['region'])
    ts += terraform(backend=b)

    return ts


def generateRandomPassword(stringLength=20):
    """Generate a random string of letters and digits """
    lettersAndDigits = string.ascii_letters + string.digits
    return ''.join(random.choice(lettersAndDigits) for i in range(stringLength))


def fetch_tf_resource_rds(resource, spec, ri):
    config = get_config()
    secrets_path = config['terraform']['secrets_path']
    variables = vault_client.read_all(secrets_path + '/variables')
    
    identifier = resource['identifier']
    re = resource['engine']
    # deafult engine is postgres
    # the engine is also the default name and username
    engine = 'postgres' if re is None else re
    rn = resource['name']
    name = rn if rn is not None else engine
    engine_version = resource['engine_version']
    ru = resource['username']
    username = ru if ru is not None else engine

    output_secret_name = identifier + '-rds'
    password = None
    try:
        output_secret = \
            spec.oc.get(spec.namespace, spec.resource, output_secret_name)
        enc_password = output_secret['data']['db.password']
        password = base64.b64decode(enc_password)
        openshift_resource = openshift_resources.OR(output_secret)
        ri.add_current(
            spec.cluster,
            spec.namespace,
            spec.resource,
            openshift_resource.name,
            openshift_resource
        )
    except StatusCodeError as e:
        if e.message.startswith('Error from server (NotFound):'):
            msg = 'Secret {} does not exist.'.format(output_secret_name)
            logging.debug(msg)
            password = generateRandomPassword()
        else:
            # TODO: determine what to do here
            raise e
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

    kwargs = {
        'engine': engine,
        'name': name,
        'username': username,
        # default values
        'instance_class': 'db.t2.small',
        'allocated_storage': 20,
        'storage_encrypted': True,
        'final_snapshot_identifier': \
            identifier + '-final-snapshot',
        'auto_minor_version_upgrade': False,
        'backup_retention_period': 7,
        'storage_type': 'gp2',
        'multi_az': False,
        # generate password unless secret with password exists
        'password': password,
        # grab secret variables from vault
        'db_subnet_group_name': variables['rds-subnet-group'],
        'vpc_security_group_ids': \
            variables['rds-security-groups'].split(','),
    }
    if engine_version is not None:
        kwargs['engine_version'] = engine_version

    return aws_db_instance(identifier, **kwargs)


def fetch_tf_resource(resource, spec, ri):
    provider = resource['provider']
    if provider == 'rds':
        return fetch_tf_resource_rds(resource, spec, ri)


def add_resources(ts):
    gqlapi = gql.get_api()
    tf_query = gqlapi.query(TF_QUERY)['namespaces']

    ri = ResourceInventory()
    for namespace_info in tf_query:
        tf_resources = namespace_info.get('terraformResources')
        # Skip if namespace has no terraformResources
        if not tf_resources:
            continue
        namespace_info['managedResourceTypes'] = ['Secret']
    state_specs = \
        openshift_resources.init_specs_to_fetch(ri, {}, tf_query)

    for namespace_info in tf_query:
        tf_resources = namespace_info.get('terraformResources')
        # Skip if namespace has no terraformResources
        if not tf_resources:
            continue
        cluster = namespace_info['cluster']['name']
        namespace = namespace_info['name']
        for resource in tf_resources:
            spec = [s for s in state_specs \
                if s.cluster == cluster and s.namespace == namespace][0]
            tf_resource = fetch_tf_resource(resource, spec, ri)
            ts.add(tf_resource)


def write_to_tmp_file(ts):
    global _working_dir

    _working_dir = tempfile.mkdtemp()
    with open(_working_dir + '/config.tf', 'w') as f:
        f.write(ts.dump())


def setup():
    ts = bootstrap_config()
    add_resources(ts)
    ts.validate()
    write_to_tmp_file(ts)


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
