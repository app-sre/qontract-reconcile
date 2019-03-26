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

from utils.oc import StatusCodeError
from utils.config import get_config
from utils.openshift_resource import OpenshiftResource, ResourceInventory

from python_terraform import Terraform
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
        account
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
QONTRACT_TF_PREFIX = 'qrtf'

_working_dirs = {}


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super(UnknownProviderError, self).__init__(
            "unknown provider error: " + str(msg)
        )


class ConstructResourceError(Exception):
    def __init__(self, msg):
        super(ConstructResourceError, self).__init__(
            "error construction openshift resource: " + str(msg)
        )


class OR(OpenshiftResource):
    def __init__(self, body):
        super(OR, self).__init__(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )


def get_vault_tf_secrets(type, account_name=""):
    config = get_config()
    accounts = config['terraform']
    secrets = {}
    for name, data in accounts.items():
        if account_name != "" and account_name != name:
            continue
        secrets_path = data['secrets_path']
        secret = vault_client.read_all(secrets_path + '/' + type)
        secrets[name] = secret
    return secrets


def bootstrap_configs():
    configs = get_vault_tf_secrets('config')
    tss = {}
    for name, config in configs.items():
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
        tss[name] = ts

    return tss


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
    specs = [s for s in state_specs
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
    return ''.join(random.choice(letters_and_digits)
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


def get_resource_tags(spec):
    return {
        'managed_by_integration': QONTRACT_INTEGRATION,
        'cluster': spec.cluster,
        'namespace': spec.namespace
    }


def fetch_tf_resources_rds(resource, spec):
    tf_resources = []
    # get values from gql query
    # the engine is the default name and username
    identifier = resource['identifier']
    engine = resource['engine']
    rn = resource['name']
    name = engine if rn is None else rn
    ru = resource['username']
    username = engine if ru is None else ru
    engine_version = resource['engine_version']
    output_resource_name = identifier + '-rds'
    # get values from vault tf secret
    ra = resource['account']
    account = 'app-sre' if ra is None else ra
    variables = get_vault_tf_secrets('variables', account)[account]
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
        'tags': get_resource_tags(spec)
    }
    if engine_version is not None:
        kwargs['engine_version'] = engine_version

    tf_resource = aws_db_instance(identifier, **kwargs)
    tf_resources.append(tf_resource)

    tf_outputs = []
    output_name = output_resource_name + '[db.host]'
    output_value = '${' + tf_resource.fullname + '.address}'
    tf_outputs.append(output(output_name, value=output_value))
    output_name = output_resource_name + '[db.port]'
    output_value = '${' + tf_resource.fullname + '.port}'
    tf_outputs.append(output(output_name, value=output_value))
    output_name = output_resource_name + '[db.name]'
    output_value = name
    tf_outputs.append(output(output_name, value=output_value))
    output_name = output_resource_name + '[db.user]'
    output_value = username
    tf_outputs.append(output(output_name, value=output_value))
    output_name = output_resource_name + '[db.password]'
    output_value = password
    tf_outputs.append(output(output_name, value=output_value))
    output_name = output_resource_name + \
        '[{}.cluster]'.format(QONTRACT_TF_PREFIX)
    output_value = spec.cluster
    tf_outputs.append(output(output_name, value=output_value))
    output_name = output_resource_name +\
        '[{}.namespace]'.format(QONTRACT_TF_PREFIX)
    output_value = spec.namespace
    tf_outputs.append(output(output_name, value=output_value))
    output_name = output_resource_name +\
        '[{}.resource]'.format(QONTRACT_TF_PREFIX)
    output_value = spec.resource
    tf_outputs.append(output(output_name, value=output_value))
    return account, tf_resources, tf_outputs, existing_oc_resource


def fetch_tf_resources(resource, spec):
    provider = resource['provider']
    if provider == 'rds':
        account, tf_resources, tf_outputs, oc_resource = \
            fetch_tf_resources_rds(resource, spec)
    else:
        raise UnknownProviderError(provider)

    return account, tf_resources, tf_outputs, oc_resource


def add_resources(tss):
    gqlapi = gql.get_api()
    tf_query = gqlapi.query(TF_QUERY)['namespaces']
    tf_query = adjust_tf_query(tf_query)

    ri = ResourceInventory()
    oc_map = {}
    state_specs = \
        openshift_resources.init_specs_to_fetch(ri, oc_map, tf_query)

    for namespace_info in tf_query:
        spec = get_spec_by_namespace(state_specs, namespace_info)
        tf_resources = namespace_info.get('terraformResources')
        for resource in tf_resources:
            account, tf_resources, tf_outputs, oc_resource = \
                fetch_tf_resources(resource, spec)
            for tf_resource in tf_resources:
                tss[account].add(tf_resource)
            for tf_output in tf_outputs:
                tss[account].add(tf_output)
            if oc_resource is None:
                continue
            openshift_resource = OR(oc_resource)
            ri.add_current(
                spec.cluster,
                spec.namespace,
                spec.resource,
                openshift_resource.name,
                openshift_resource
            )
    return ri, oc_map


def validate_tss(tss):
    for name, ts in tss.items():
        ts.validate()


def write_to_tmp_files(tss):
    global _working_dirs

    for name, ts in tss.items():
        wd = tempfile.mkdtemp()
        with open(wd + '/config.tf', 'w') as f:
            f.write(ts.dump())
        _working_dirs[name] = wd


def setup():
    tss = bootstrap_configs()
    ri, oc_map = add_resources(tss)
    validate_tss(tss)
    write_to_tmp_files(tss)

    return ri, oc_map


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


def log_plan_diff(name, stdout):
    for line in stdout.split('\n'):
        if line.startswith('+ aws'):
            line_split = line.replace('+ ', '').split('.')
            logging.info(['create', name, line_split[0], line_split[1]])
        if line.startswith('- aws'):
            line_split = line.replace('- ', '').split('.')
            logging.info(['destroy', name, line_split[0], line_split[1]])
        if line.startswith('~ aws'):
            line_split = line.replace('~ ', '').split('.')
            logging.info(['update', name, line_split[0], line_split[1]])


def tf_init():
    global _working_dirs

    tfs = {}
    for name, wd in _working_dirs.items():
        tf = Terraform(working_dir=wd)
        return_code, stdout, stderr = tf.init()
        check_tf_output(return_code, stdout, stderr)
        tfs[name] = tf

    return tfs


def tf_plan(tfs):
    for name, tf in tfs.items():
        return_code, stdout, stderr = tf.plan(detailed_exitcode=False)
        check_tf_output(return_code, stdout, stderr)
        log_plan_diff(name, stdout)


def tf_apply(tfs):
    for name, tf in tfs.items():
        return_code, stdout, stderr = tf.apply(auto_approve=True)
        check_tf_output(return_code, stdout, stderr)


def tf_refresh(tfs):
    for name, tf in tfs.items():
        return_code, stdout, stderr = tf.refresh()
        check_tf_output(return_code, stdout, stderr)


def format_data(output):
    # data is a dictionary of dictionaries
    data = {}
    for k, v in output:
        if '[' not in k or ']' not in k:
            continue
        k_split = k.split('[')
        resource_name = k_split[0]
        field_key = k_split[1][:-1]
        field_value = v['value']
        if resource_name not in data:
            data[resource_name] = {}
        data[resource_name][field_key] = field_value
    return data


def contruct_oc_resource(name, data):
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": name,
        },
        "data": {}
    }

    for k, v in data.items():
        if QONTRACT_TF_PREFIX in k:
            continue
        body['data'][k] = base64.b64encode(v)

    openshift_resource = OR(body)

    try:
        openshift_resource.verify_valid_k8s_object()
    except (KeyError, TypeError) as e:
        k = e.__class__.__name__
        e_msg = "Invalid data ({}). Skipping resource: {}"
        raise ConstructResourceError(e_msg.format(k, name))

    return openshift_resource


def tf_output(tfs, ri):
    for name, tf in tfs.items():
        output = tf.output()
        formatted_data = format_data(output.items())

        for name, data in formatted_data.items():
            oc_resource = contruct_oc_resource(name, data)
            ri.add_desired(
                data['{}.cluster'.format(QONTRACT_TF_PREFIX)],
                data['{}.namespace'.format(QONTRACT_TF_PREFIX)],
                data['{}.resource'.format(QONTRACT_TF_PREFIX)],
                name,
                oc_resource
            )


def cleanup():
    global _working_dirs

    for _, wd in _working_dirs.items():
        shutil.rmtree(wd)


def run(dry_run=False):
    ri, oc_map = setup()
    tfs = tf_init()
    tf_plan(tfs)

    if not dry_run:
        tf_apply(tfs)
    else:
        tf_refresh(tfs)

    tf_output(tfs, ri)
    openshift_resources.realize_data(dry_run, oc_map, ri)

    cleanup()
