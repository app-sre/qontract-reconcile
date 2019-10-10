import tempfile
import random
import string
import base64
import json
import anymarkup
import logging

import utils.gql as gql
import utils.threaded as threaded
import utils.vault_client as vault_client

from utils.oc import StatusCodeError
from utils.gpg import gpg_key_valid
from reconcile.exceptions import FetchResourceError

from threading import Lock
from terrascript import Terrascript, provider, terraform, backend, output
from terrascript.aws.r import (aws_db_instance, aws_s3_bucket, aws_iam_user,
                               aws_iam_access_key, aws_iam_user_policy,
                               aws_iam_group, aws_iam_group_policy_attachment,
                               aws_iam_user_group_membership,
                               aws_iam_user_login_profile,
                               aws_elasticache_replication_group,
                               aws_iam_user_policy_attachment)


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super(UnknownProviderError, self).__init__(
            "unknown provider error: " + str(msg)
        )


class TerrascriptClient(object):
    def __init__(self, integration, integration_prefix,
                 thread_pool_size, accounts, oc_map=None):
        self.integration = integration
        self.integration_prefix = integration_prefix
        self.oc_map = oc_map
        self.thread_pool_size = thread_pool_size
        self.populate_configs_from_vault(accounts)
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
                        key=config['{}_key'.format(integration)],
                        region=config['region'])
            ts += terraform(backend=b)
            tss[name] = ts
            locks[name] = Lock()
        self.tss = tss
        self.locks = locks

    def populate_configs_from_vault(self, accounts):
        results = threaded.run(self.get_vault_tf_secrets, accounts,
                               self.thread_pool_size)
        self.configs = {account: secret for account, secret in results}

    @staticmethod
    def get_vault_tf_secrets(account):
        account_name = account['name']
        automation_token = account['automationToken']
        secret = vault_client.read_all(automation_token)
        return (account_name, secret)

    def get_tf_iam_group(self, group_name):
        return aws_iam_group(
            group_name,
            name=group_name
        )

    def get_tf_iam_user(self, user_name):
        return aws_iam_user(
            user_name,
            name=user_name,
            force_destroy=True,
            tags={
                'managed_by_integration': self.integration
            }
        )

    def populate_iam_groups(self, roles):
        groups = {}
        for role in roles:
            users = role['users']
            if len(users) == 0:
                continue

            aws_groups = role['aws_groups']
            for aws_group in aws_groups:
                group_name = aws_group['name']
                group_policies = aws_group['policies']
                account = aws_group['account']
                account_name = account['name']
                if account_name not in groups:
                    groups[account_name] = {}
                if group_name not in groups[account_name]:
                    # Ref: terraform aws iam_group
                    tf_iam_group = self.get_tf_iam_group(group_name)
                    self.add_resource(account_name, tf_iam_group)
                    for policy in group_policies:
                        # Ref: terraform aws iam_group_policy_attachment
                        # this may change in the near future
                        # to include inline policies and not
                        # only managed policies, as it is currently
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

    def populate_iam_users(self, roles):
        for role in roles:
            users = role['users']
            if len(users) == 0:
                continue

            aws_groups = role['aws_groups']
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

                    # Ref: terraform aws iam_user
                    tf_iam_user = self.get_tf_iam_user(user_name)
                    self.add_resource(account_name, tf_iam_user)

                    # Ref: terraform aws iam_group_membership
                    tf_iam_group = self.get_tf_iam_group(group_name)
                    tf_iam_user_group_membership = \
                        aws_iam_user_group_membership(
                            user_name + '-' + group_name,
                            user=user_name,
                            groups=[group_name],
                            depends_on=[tf_iam_user, tf_iam_group]
                        )
                    self.add_resource(account_name,
                                      tf_iam_user_group_membership)

                    # if user does not have a gpg key,
                    # a password will not be created.
                    # a gpg key may be added at a later time,
                    # and a password will be generated
                    user_public_gpg_key = users[iu]['public_gpg_key']
                    if user_public_gpg_key is None:
                        msg = \
                            'user {} does not have a public gpg key ' \
                            'and will be created without a password.'.format(
                                user_name)
                        logging.warning(msg)
                        continue
                    if not gpg_key_valid(user_public_gpg_key):
                        msg = \
                            'user {} has an invalid public gpg key.'.format(
                                user_name)
                        logging.error(msg)
                        error = True
                        return error
                    # Ref: terraform aws iam_user_login_profile
                    tf_iam_user_login_profile = aws_iam_user_login_profile(
                        user_name,
                        user=user_name,
                        pgp_key=user_public_gpg_key,
                        depends_on=[tf_iam_user],
                        lifecycle={
                            'ignore_changes': ["id",
                                               "password_length",
                                               "password_reset_required",
                                               "pgp_key"]
                        }
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

            user_policies = role['user_policies']
            if user_policies is not None:
                for ip in range(len(user_policies)):
                    policy_name = user_policies[ip]['name']
                    account_name = user_policies[ip]['account']['name']
                    account_uid = user_policies[ip]['account']['uid']
                    for iu in range(len(users)):
                        # replace known keys with values
                        user_name = users[iu]['redhat_username']
                        policy = user_policies[ip]['policy']
                        policy = policy.replace('${aws:username}', user_name)
                        policy = \
                            policy.replace('${aws:accountid}', account_uid)

                        # Ref: terraform aws iam_user_policy
                        tf_iam_user = self.get_tf_iam_user(user_name)
                        tf_aws_iam_user_policy = aws_iam_user_policy(
                            user_name + '-' + policy_name,
                            name=user_name + '-' + policy_name,
                            user=user_name,
                            policy=policy,
                            depends_on=[tf_iam_user]
                        )
                        self.add_resource(account_name,
                                          tf_aws_iam_user_policy)

    def populate_users(self, roles):
        self.populate_iam_groups(roles)
        err = self.populate_iam_users(roles)
        if err:
            return err

    def populate_resources(self, namespaces, existing_secrets):
        populate_specs = self.init_populate_specs(namespaces)
        threaded.run(self.populate_tf_resources, populate_specs,
                     self.thread_pool_size,
                     existing_secrets=existing_secrets)

    def init_populate_specs(self, namespaces):
        populate_specs = []
        for namespace_info in namespaces:
            # Skip if namespace has no terraformResources
            tf_resources = namespace_info.get('terraformResources')
            if not tf_resources:
                continue
            for resource in tf_resources:
                populate_spec = {'resource': resource,
                                 'namespace_info': namespace_info}
                populate_specs.append(populate_spec)
        return populate_specs

    def populate_tf_resources(self, populate_spec, existing_secrets):
        resource = populate_spec['resource']
        namespace_info = populate_spec['namespace_info']
        provider = resource['provider']
        if provider == 'rds':
            self.populate_tf_resource_rds(resource, namespace_info,
                                          existing_secrets)
        elif provider == 's3':
            self.populate_tf_resource_s3(resource, namespace_info)
        elif provider == 'elasticache':
            self.populate_tf_resource_elasticache(resource, namespace_info,
                                                  existing_secrets)
        elif provider == 'service-account':
            self.populate_tf_resource_service_account(resource,
                                                      namespace_info)
        else:
            raise UnknownProviderError(provider)

    def populate_tf_resource_rds(self, resource, namespace_info,
                                 existing_secrets):
        account, identifier, values, output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        try:
            password = \
                existing_secrets[account][output_prefix]['db.password']
        except KeyError:
            password = \
                self.determine_db_password(namespace_info,
                                           output_resource_name)
        values['password'] = password

        # rds instance
        # Ref: https://www.terraform.io/docs/providers/aws/r/db_instance.html
        tf_resource = aws_db_instance(identifier, **values)
        tf_resources.append(tf_resource)
        # rds outputs
        # we want the outputs to be formed into an OpenShift Secret
        # with the following fields
        # db.host
        output_name = output_prefix + '[db.host]'
        output_value = '${' + tf_resource.fullname + '.address}'
        tf_resources.append(output(output_name, value=output_value))
        # db.port
        output_name = output_prefix + '[db.port]'
        output_value = '${' + tf_resource.fullname + '.port}'
        tf_resources.append(output(output_name, value=output_value))
        # db.name
        output_name = output_prefix + '[db.name]'
        output_value = values['name']
        tf_resources.append(output(output_name, value=output_value))
        # db.user
        output_name = output_prefix + '[db.user]'
        output_value = values['username']
        tf_resources.append(output(output_name, value=output_value))
        # db.password
        output_name = output_prefix + '[db.password]'
        output_value = values['password']
        tf_resources.append(output(output_name, value=output_value))

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def determine_db_password(self, namespace_info, output_resource_name,
                              secret_key='db.password'):
        existing_oc_resource = \
            self.fetch_existing_oc_resource(namespace_info,
                                            output_resource_name)
        if existing_oc_resource is not None:
            enc_password = existing_oc_resource['data'][secret_key]
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
            oc = self.oc_map.get(cluster)
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
        account, identifier, common_values, \
            output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        # s3 bucket
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/s3_bucket.html
        values = {}
        values['bucket'] = identifier
        values['versioning'] = {'enabled': True}
        values['tags'] = common_values['tags']
        values['acl'] = common_values['acl']
        if common_values.get('lifecycle_rules'):
            # common_values['lifecycle_rules'] is a list of lifecycle_rules
            values['lifecycle_rule'] = common_values['lifecycle_rules']
        bucket_tf_resource = aws_s3_bucket(identifier, **values)
        tf_resources.append(bucket_tf_resource)
        output_name = output_prefix + '[bucket]'
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
        tf_resources.extend(
            self.get_tf_iam_access_key(
                user_tf_resource, identifier, output_prefix))

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

    def populate_tf_resource_elasticache(self, resource, namespace_info,
                                         existing_secrets):
        account, identifier, values, output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)
        values['replication_group_id'] = values['identifier']
        values.pop('identifier', None)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        try:
            auth_token = \
                existing_secrets[account][output_prefix]['db.auth_token']
        except KeyError:
            auth_token = \
                self.determine_db_password(namespace_info,
                                           output_resource_name,
                                           secret_key='db.auth_token')
        values['auth_token'] = auth_token

        # elasticache replication group
        # Ref: https://www.terraform.io/docs/providers/aws/r/
        # elasticache_replication_group.html
        tf_resource = aws_elasticache_replication_group(identifier, **values)
        tf_resources.append(tf_resource)
        # elasticache outputs
        # we want the outputs to be formed into an OpenShift Secret
        # with the following fields
        # db.endpoint
        output_name = output_prefix + '[db.endpoint]'
        output_value = '${' + tf_resource.fullname + \
                       '.configuration_endpoint_address}'
        tf_resources.append(output(output_name, value=output_value))
        # db.port
        output_name = output_prefix + '[db.port]'
        output_value = '${' + tf_resource.fullname + '.port}'
        tf_resources.append(output(output_name, value=output_value))
        # db.auth_token
        output_name = output_prefix + '[db.auth_token]'
        output_value = values['auth_token']
        tf_resources.append(output(output_name, value=output_value))

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def populate_tf_resource_service_account(self, resource, namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        # iam user for bucket
        values = {}
        values['name'] = identifier
        values['tags'] = common_values['tags']
        user_tf_resource = aws_iam_user(identifier, **values)
        tf_resources.append(user_tf_resource)

        # iam access key for user
        tf_resources.extend(
            self.get_tf_iam_access_key(
                user_tf_resource, identifier, output_prefix))

        # iam user policies
        for policy in common_values['policies']:
            tf_iam_user_policy_attachment = \
                aws_iam_user_policy_attachment(
                    identifier + '-' + policy,
                    user=identifier,
                    policy_arn='arn:aws:iam::aws:policy/' + policy,
                    depends_on=[user_tf_resource]
                )
            tf_resources.append(tf_iam_user_policy_attachment)

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    @staticmethod
    def get_tf_iam_access_key(user_tf_resource, identifier, output_prefix):
        tf_resources = []
        values = {}
        values['user'] = identifier
        values['depends_on'] = [user_tf_resource]
        tf_resource = aws_iam_access_key(identifier, **values)
        tf_resources.append(tf_resource)
        output_name = output_prefix + '[aws_access_key_id]'
        output_value = '${' + tf_resource.fullname + '.id}'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_prefix + '[aws_secret_access_key]'
        output_value = '${' + tf_resource.fullname + '.secret}'
        tf_resources.append(output(output_name, value=output_value))

        return tf_resources

    def add_resource(self, account, tf_resource):
        with self.locks[account]:
            self.tss[account].add(tf_resource)

    def dump(self, print_only=False, existing_dirs=None):
        error = False
        if existing_dirs is None:
            working_dirs = {}
        else:
            working_dirs = existing_dirs
        for name, ts in self.tss.items():
            if print_only:
                print('##### {} #####'.format(name))
                print(ts.dump())
                continue
            if existing_dirs is None:
                wd = tempfile.mkdtemp()
            else:
                wd = working_dirs[name]
            with open(wd + '/config.tf', 'w') as f:
                f.write(ts.dump())
            valid = ts.validate(wd)
            if not valid:
                error = not valid
            working_dirs[name] = wd

        return working_dirs, error

    def init_values(self, resource, namespace_info):
        account = resource['account']
        provider = resource['provider']
        identifier = resource['identifier']
        defaults_path = resource.get('defaults', None)
        overrides = resource.get('overrides', None)
        policies = resource.get('policies', None)

        values = self.get_values(defaults_path) if defaults_path else {}
        self.aggregate_values(values)
        self.override_values(values, overrides)
        values['identifier'] = identifier
        values['tags'] = self.get_resource_tags(namespace_info)
        if policies:
            values['policies'] = policies

        output_prefix = '{}-{}'.format(identifier, provider)
        output_resource_name = resource['output_resource_name']
        if output_resource_name is None:
            output_resource_name = output_prefix

        return account, identifier, values, output_prefix, output_resource_name

    def aggregate_values(self, values):
        split_char = '.'
        for k, v in values.items():
            if split_char not in k:
                continue
            k_split = k.split(split_char)
            primary_key = k_split[0]
            secondary_key = k_split[1]
            values.setdefault(primary_key, {})
            values[primary_key][secondary_key] = v
            values.pop(k, None)

    def override_values(self, values, overrides):
        if overrides is None:
            return
        data = json.loads(overrides)
        for k, v in data.items():
            values[k] = v

    def init_common_outputs(self, tf_resources, namespace_info,
                            output_prefix, output_resource_name):
        output_format = '{}[{}.{}]'
        cluster, namespace = self.unpack_namespace_info(namespace_info)
        output_name = output_format.format(
            output_prefix, self.integration_prefix, 'cluster')
        output_value = cluster
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_format.format(
            output_prefix, self.integration_prefix, 'namespace')
        output_value = namespace
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_format.format(
            output_prefix, self.integration_prefix, 'resource')
        output_value = 'Secret'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_format.format(
            output_prefix, self.integration_prefix, 'output_resource_name')
        output_value = output_resource_name
        tf_resources.append(output(output_name, value=output_value))

    def get_values(self, path):
        gqlapi = gql.get_api()
        try:
            raw_values = gqlapi.get_resource(path)
        except gql.GqlGetResourceError as e:
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
