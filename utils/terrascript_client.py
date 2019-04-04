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
                               aws_iam_access_key, aws_iam_user_policy,
                               aws_iam_group, aws_iam_group_policy_attachment,
                               aws_iam_user_group_membership,
                               aws_iam_user_login_profile)
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
    def __init__(self, integration, integration_prefix, oc_map):
        self.integration = integration
        self.integration_prefix = integration_prefix
        self.oc_map = oc_map
        self.lock = Lock()
        self.populate_configs_and_vars_from_vault()
        tss = {}
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
        self.tss = tss

    def populate_configs_and_vars_from_vault(self):
        self.init_accounts()
        self.configs = self.get_vault_tf_secrets('config')
        self.variables = self.get_vault_tf_secrets('variables')

    def init_accounts(self):
        config = get_config()
        accounts = config['terraform']
        self.accounts = accounts.items()

    def get_vault_tf_secrets(self, type):
        secrets = {}
        for name, data in self.accounts:
            secrets_path = data['secrets_path']
            secret = vault_client.read_all(secrets_path + '/' + type)
            secrets[name] = secret
        return secrets

    def populate_iam_groups(self, tf_query):
        groups = {}
        for role in tf_query:
            aws_groups = role['aws_groups']
            for aws_group in aws_groups:
                group_name = aws_group['name']
                group_policies = aws_group['policies']
                account = aws_group['account']
                account_name = account['name']
                if account_name not in groups:
                    groups[account_name] = {}
                if group_name not in groups[account_name]:
                    # Ref: https://www.terraform.io/docs/providers/aws/r/iam_group.html
                    tf_iam_group = aws_iam_group(
                        group_name,
                        name=group_name
                    )
                    self.add_resource(account_name, tf_iam_group)
                    for policy in group_policies:
                        # Ref: https://www.terraform.io/docs/providers/aws/r/iam_group_policy_attachment.html
                        # this may change in the near future to include inline policies
                        # and not only managed policies, as it is currently
                        tf_iam_group_policy_attachment = \
                            aws_iam_group_policy_attachment(
                                group_name + '-' + policy,
                                group=group_name,
                                policy_arn='arn:aws:iam::aws:policy/' + policy,
                                depends_on=[tf_iam_group]
                            )
                        self.add_resource(account_name,
                                          tf_iam_group_policy_attachment)
                    groups[account_name][group_name] = 'Done'
        return groups

    def populate_iam_users(self, tf_query):
        for role in tf_query:
            aws_groups = role['aws_groups']
            users = role['users']
            for ig in range(len(aws_groups)):
                group_name = aws_groups[ig]['name']
                account_name = aws_groups[ig]['account']['name']
                account_console_url = aws_groups[ig]['account']['consoleUrl']

                # we want to include the console url in the outputs
                # to be used later to generate the email invitations
                output_name = '{}.console-urls[{}]'.format(
                    self.integration_prefix, account_name
                )
                output_value = account_console_url
                tf_output = output(output_name, value=output_value)
                self.add_resource(account_name, tf_output)

                for iu in range(len(users)):
                    user_name = users[iu]['redhat_username']
                    user_public_gpg_key = users[iu]['public_gpg_key']
                    if user_public_gpg_key is None:
                        msg = \
                            'user {} does not have a public gpg key.'.format(
                                user_name)
                        logging.info(msg)
                        continue

                    # Ref: https://www.terraform.io/docs/providers/aws/r/iam_user.html
                    tf_iam_user = aws_iam_user(
                        user_name,
                        name=user_name,
                        force_destroy=True,
                        tags = {
                            'managed_by_integration': self.integration
                        }
                    )
                    self.add_resource(account_name, tf_iam_user)

                    # Ref: https://www.terraform.io/docs/providers/aws/r/iam_group_membership.html
                    tf_iam_user_group_membership = \
                        aws_iam_user_group_membership(
                            user_name + '-' + group_name,
                            user=user_name,
                            groups=[group_name],
                            depends_on=[tf_iam_user]
                        )
                    self.add_resource(account_name, tf_iam_user_group_membership)

                    # Ref: https://www.terraform.io/docs/providers/aws/r/iam_user_login_profile.html
                    tf_iam_user_login_profile = aws_iam_user_login_profile(
                        user_name,
                        user=user_name,
                        pgp_key=user_public_gpg_key,
                        depends_on=[tf_iam_user]
                    )
                    self.add_resource(account_name, tf_iam_user_login_profile)

                    # we want the outputs to be formed into a mail invitation
                    # for each new user. we form an output of the form
                    # 'qrtf.enc-passwords[user_name] = <encrypted password>
                    output_name = '{}.enc-passwords[{}]'.format(
                        self.integration_prefix, user_name)
                    output_value = '${' + tf_iam_user_login_profile.fullname \
                        + '.encrypted_password}'
                    tf_output = output(output_name, value=output_value)
                    self.add_resource(account_name, tf_output)

    def populate_iam(self, tf_query):
        self.populate_iam_groups(tf_query)
        self.populate_iam_users(tf_query)

    def populate_resources(self, tf_query):
        for namespace_info in tf_query:
            # Skip if namespace has no terraformResources
            tf_resources = namespace_info.get('terraformResources')
            if not tf_resources:
                continue
            for resource in tf_resources:
                self.populate_tf_resources(resource, namespace_info)
        self.validate()

    def populate_tf_resources(self, resource, namespace_info):
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
        self.lock.acquire()
        self.tss[account].add(tf_resource)
        self.lock.release()

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
