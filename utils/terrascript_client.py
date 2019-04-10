import tempfile
import random
import string
import base64
import json
import anymarkup
import logging

import utils.gql as gql
import utils.vault_client as vault_client

from utils.config import get_config
from utils.oc import StatusCodeError

from terrascript import Terrascript, provider, terraform, backend, output
from terrascript.aws.r import (aws_db_instance, aws_s3_bucket, aws_iam_user,
                               aws_iam_access_key, aws_iam_user_policy)
from multiprocessing.dummy import Pool as ThreadPool
from threading import Lock


class FetchResourceError(Exception):
    def __init__(self, msg):
        super(FetchResourceError, self).__init__(
            "error fetching resource: " + str(msg)
        )


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super(UnknownProviderError, self).__init__(
            "unknown provider error: " + str(msg)
        )


class TerrascriptClient(object):
    def __init__(self, integration, integration_prefix,
                 oc_map, thread_pool_size):
        self.integration = integration
        self.integration_prefix = integration_prefix
        self.oc_map = oc_map
        self.thread_pool_size = thread_pool_size
        self.populate_configs_and_vars_from_vault()
        tss = {}
        locks = {}
        for name, config in self.configs.items():
            # Ref: https://github.com/mjuenema/python-terrascript#example
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
            locks[name] = Lock()
        self.tss = tss
        self.locks = locks

    def populate_configs_and_vars_from_vault(self):
        self.init_accounts()

        vault_specs = self.init_vault_tf_secret_specs()
        pool = ThreadPool(self.thread_pool_size)
        results = pool.map(self.get_vault_tf_secrets, vault_specs)

        self.configs = {}
        self.variables = {}
        for account_name, type, secret in results:
            if type == 'config':
                self.configs[account_name] = secret
            if type == 'variables':
                self.variables[account_name] = secret

    def init_accounts(self):
        config = get_config()
        accounts = config['terraform']
        self.accounts = accounts.items()

    class InitSpec(object):
        def __init__(self, account, data, type):
            self.account = account
            self.data = data
            self.type = type

    def init_vault_tf_secret_specs(self):
        vault_specs = []
        for account_name, data in self.accounts:
            for type in ('config', 'variables'):
                init_spec = self.InitSpec(account_name, data, type)
                vault_specs.append(init_spec)
        return vault_specs

    def get_vault_tf_secrets(self, init_spec):
        account = init_spec.account
        data = init_spec.data
        type = init_spec.type
        secrets_path = data['secrets_path']
        secret = vault_client.read_all(secrets_path + '/' + type)
        return (account, type, secret)

    def populate(self, tf_query):
        populate_specs = self.init_populate_specs(tf_query)

        pool = ThreadPool(self.thread_pool_size)
        pool.map(self.populate_tf_resources, populate_specs)

        self.validate()

    class PopulateSpec(object):
        def __init__(self, resource, namespace_info):
            self.resource = resource
            self.namespace_info = namespace_info

    def init_populate_specs(self, tf_query):
        populate_specs = []
        for namespace_info in tf_query:
            # Skip if namespace has no terraformResources
            tf_resources = namespace_info.get('terraformResources')
            if not tf_resources:
                continue
            for resource in tf_resources:
                populate_spec = self.PopulateSpec(resource, namespace_info)
                populate_specs.append(populate_spec)
        return populate_specs

    def populate_tf_resources(self, populate_spec):
        resource = populate_spec.resource
        namespace_info = populate_spec.namespace_info
        provider = resource['provider']
        if provider == 'rds':
            self.populate_tf_resource_rds(resource, namespace_info)
        elif provider == 's3':
            self.populate_tf_resource_s3(resource, namespace_info)
        else:
            raise UnknownProviderError(provider)

    def populate_tf_resource_rds(self, resource, namespace_info):
        account, identifier, values, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_resource_name)

        # rds instance
        # Ref: https://www.terraform.io/docs/providers/aws/r/db_instance.html
        try:
            variables = self.variables[account]
            values['db_subnet_group_name'] = variables['rds-subnet-group']
            values['vpc_security_group_ids'] = \
                variables['rds-security-groups'].split(',')
        except KeyError as e:
            logging.error("could not get an account variable: " + e.msg)
            return
        values['password'] = \
            self.determine_rds_db_password(namespace_info,
                                           output_resource_name)

        tf_resource = aws_db_instance(identifier, **values)
        tf_resources.append(tf_resource)
        # rds outputs
        # we want the outputs to be formed into an OpenShift Secret
        # with the following fields
        # db.host
        output_name = output_resource_name + '[db.host]'
        output_value = '${' + tf_resource.fullname + '.address}'
        tf_resources.append(output(output_name, value=output_value))
        # db.port
        output_name = output_resource_name + '[db.port]'
        output_value = '${' + tf_resource.fullname + '.port}'
        tf_resources.append(output(output_name, value=output_value))
        # db.name
        output_name = output_resource_name + '[db.name]'
        output_value = values['name']
        tf_resources.append(output(output_name, value=output_value))
        # db.user
        output_name = output_resource_name + '[db.user]'
        output_value = values['username']
        tf_resources.append(output(output_name, value=output_value))
        # db.password
        output_name = output_resource_name + '[db.password]'
        output_value = values['password']
        tf_resources.append(output(output_name, value=output_value))

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def determine_rds_db_password(self, namespace_info, output_resource_name):
        existing_oc_resource = \
            self.fetch_existing_oc_resource(namespace_info,
                                            output_resource_name)
        if existing_oc_resource is not None:
            enc_password = existing_oc_resource['data']['db.password']
            return base64.b64decode(enc_password)
        return self.generate_random_password()

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

    def fetch_existing_oc_resource(self, namespace_info, resource_name):
        cluster, namespace = self.unpack_namespace_info(namespace_info)
        try:
            oc = self.oc_map[cluster]
            return oc.get(namespace, 'Secret', resource_name)
        except StatusCodeError as e:
            if e.message.startswith('Error from server (NotFound):'):
                msg = 'Secret {} does not exist.'.format(resource_name)
                logging.debug(msg)
        return None

    def generate_random_password(self, string_length=20):
        """Generate a random string of letters and digits """
        letters_and_digits = string.ascii_letters + string.digits
        return ''.join(random.choice(letters_and_digits)
                       for i in range(string_length))

    def populate_tf_resource_s3(self, resource, namespace_info):
        account, identifier, common_values, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_resource_name)

        # s3 bucket
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/s3_bucket.html
        values = {}
        values['bucket'] = identifier
        values['versioning'] = {'enabled': True}
        values['tags'] = common_values['tags']
        bucket_tf_resource = aws_s3_bucket(identifier, **values)
        tf_resources.append(bucket_tf_resource)
        output_name = output_resource_name + '[bucket]'
        output_value = '${' + bucket_tf_resource.fullname + '.bucket}'
        tf_resources.append(output(output_name, value=output_value))

        # iam resources
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/iam_access_key.html

        # iam user for bucket
        values = {}
        values['name'] = identifier
        values['tags'] = common_values['tags']
        values['depends_on'] = [bucket_tf_resource]
        user_tf_resource = aws_iam_user(identifier, **values)
        tf_resources.append(user_tf_resource)

        # iam access key for user
        values = {}
        values['user'] = identifier
        values['depends_on'] = [user_tf_resource]
        tf_resource = aws_iam_access_key(identifier, **values)
        tf_resources.append(tf_resource)
        output_name = output_resource_name + '[aws_access_key_id]'
        output_value = '${' + tf_resource.fullname + '.id}'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_resource_name + '[aws_secret_access_key]'
        output_value = '${' + tf_resource.fullname + '.secret}'
        tf_resources.append(output(output_name, value=output_value))

        # iam user policy for bucket
        values = {}
        values['user'] = identifier
        values['name'] = identifier
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "ListObjectsInBucket",
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket"],
                    "Resource": ["arn:aws:s3:::{0}".format(identifier)]
                },
                {
                    "Sid": "AllObjectActions",
                    "Effect": "Allow",
                    "Action": "s3:*Object",
                    "Resource": ["arn:aws:s3:::{0}/*".format(identifier)]
                }
            ]
        }
        values['policy'] = json.dumps(policy, sort_keys=True)
        values['depends_on'] = [user_tf_resource]
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def add_resource(self, account, tf_resource):
        with self.locks[account]:
            self.tss[account].add(tf_resource)

    def validate(self):
        for _, ts in self.tss.items():
            ts.validate()

    def dump(self, print_only=False):
        working_dirs = {}
        for name, ts in self.tss.items():
            if print_only:
                print('##### {} #####'.format(name))
                print(ts.dump())
                continue
            wd = tempfile.mkdtemp()
            with open(wd + '/config.tf', 'w') as f:
                f.write(ts.dump())
            working_dirs[name] = wd
        return working_dirs

    def init_values(self, resource, namespace_info):
        account = resource['account']
        provider = resource['provider']
        identifier = resource['identifier']
        defaults_path = resource['defaults']
        overrides = resource['overrides']

        values = self.get_values(defaults_path)
        self.override_values(values, overrides)
        values['identifier'] = identifier
        values['tags'] = self.get_resource_tags(namespace_info)

        output_resource_name = '{}-{}'.format(identifier, provider)

        return account, identifier, values, output_resource_name

    def override_values(self, base, overrides):
        if overrides is None:
            return
        data = json.loads(overrides)
        for k, v in data.items():
            base[k] = v

    def init_common_outputs(self, tf_resources, namespace_info, name):
        cluster, namespace = self.unpack_namespace_info(namespace_info)
        output_name = name + '[{}.cluster]'.format(self.integration_prefix)
        output_value = cluster
        tf_resources.append(output(output_name, value=output_value))
        output_name = name + '[{}.namespace]'.format(self.integration_prefix)
        output_value = namespace
        tf_resources.append(output(output_name, value=output_value))
        output_name = name + '[{}.resource]'.format(self.integration_prefix)
        output_value = 'Secret'
        tf_resources.append(output(output_name, value=output_value))

    def get_values(self, path):
        gqlapi = gql.get_api()
        try:
            raw_values = gqlapi.get_resource(path)
        except gql.GqlApiError as e:
            raise FetchResourceError(e.message)
        try:
            values = anymarkup.parse(
                raw_values['content'],
                force_types=None
            )
        except anymarkup.AnyMarkupError:
            e_msg = "Could not parse data. Skipping resource: {}"
            raise FetchResourceError(e_msg.format(path))
        return values

    def get_resource_tags(self, namespace_info):
        cluster, namespace = self.unpack_namespace_info(namespace_info)
        return {
            'managed_by_integration': self.integration,
            'cluster': cluster,
            'namespace': namespace
        }

    def unpack_namespace_info(self, namespace_info):
        cluster = namespace_info['cluster']['name']
        namespace = namespace_info['name']
        return cluster, namespace
