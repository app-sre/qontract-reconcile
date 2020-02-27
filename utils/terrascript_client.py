import tempfile
import random
import string
import base64
import json
import anymarkup
import logging
import re

import utils.gql as gql
import utils.threaded as threaded
import utils.secret_reader as secret_reader

from utils.oc import StatusCodeError
from utils.gpg import gpg_key_valid
from reconcile.exceptions import FetchResourceError

from threading import Lock
from terrascript import Terrascript, provider, terraform, backend, output
from terrascript.aws.r import (aws_db_instance, aws_db_parameter_group,
                               aws_s3_bucket, aws_iam_user,
                               aws_iam_access_key, aws_iam_user_policy,
                               aws_iam_group, aws_iam_group_policy_attachment,
                               aws_iam_user_group_membership,
                               aws_iam_user_login_profile, aws_iam_policy,
                               aws_iam_role, aws_iam_role_policy_attachment,
                               aws_elasticache_replication_group,
                               aws_elasticache_parameter_group,
                               aws_iam_user_policy_attachment,
                               aws_sqs_queue, aws_dynamodb_table,
                               aws_ecr_repository, aws_s3_bucket_policy,
                               aws_cloudfront_origin_access_identity,
                               aws_cloudfront_distribution)


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super(UnknownProviderError, self).__init__(
            "unknown provider error: " + str(msg)
        )


class TerrascriptClient(object):
    def __init__(self, integration, integration_prefix,
                 thread_pool_size, accounts, oc_map=None, settings=None):
        self.integration = integration
        self.integration_prefix = integration_prefix
        self.oc_map = oc_map
        self.thread_pool_size = thread_pool_size
        filtered_accounts = self.filter_disabled_accounts(accounts)
        self.populate_configs(filtered_accounts, settings)
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
        self.uids = {a['name']: a['uid'] for a in filtered_accounts}
        self.default_regions = {a['name']: a['resourcesDefaultRegion']
                                for a in filtered_accounts}

    def filter_disabled_accounts(self, accounts):
        filtered_accounts = []
        for account in accounts:
            try:
                disabled_integrations = account['disable']['integrations']
            except (KeyError, TypeError):
                disabled_integrations = []
            integration = self.integration.replace('_', '-')
            if integration not in disabled_integrations:
                filtered_accounts.append(account)
        return filtered_accounts

    def populate_configs(self, accounts, settings):
        results = threaded.run(self.get_tf_secrets, accounts,
                               self.thread_pool_size, settings=settings)
        self.configs = {account: secret for account, secret in results}

    @staticmethod
    def get_tf_secrets(account, settings=None):
        account_name = account['name']
        automation_token = account['automationToken']
        secret = secret_reader.read_all(automation_token, settings)
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

            aws_groups = role['aws_groups'] or []
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

            aws_groups = role['aws_groups'] or []
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
                    user_name = users[iu]['org_username']

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

            user_policies = role['user_policies'] or []
            for ip in range(len(user_policies)):
                policy_name = user_policies[ip]['name']
                account_name = user_policies[ip]['account']['name']
                account_uid = user_policies[ip]['account']['uid']
                for iu in range(len(users)):
                    # replace known keys with values
                    user_name = users[iu]['org_username']
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
        for spec in self.init_populate_specs(namespaces):
            self.populate_tf_resources(spec, existing_secrets)

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
        elif provider == 'sqs':
            self.populate_tf_resource_sqs(resource, namespace_info)
        elif provider == 'dynamodb':
            self.populate_tf_resource_dynamodb(resource, namespace_info)
        elif provider == 'ecr':
            self.populate_tf_resource_ecr(resource, namespace_info)
        elif provider == 's3-cloudfront':
            self.populate_tf_resource_s3_cloudfront(resource, namespace_info)
        else:
            raise UnknownProviderError(provider)

    def populate_tf_resource_rds(self, resource, namespace_info,
                                 existing_secrets):
        account, identifier, values, output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        # we want to allow an empty name, so we
        # only validate names which are not emtpy
        if values['name'] and not self.validate_db_name(values['name']):
            raise FetchResourceError(
                f"[{account}] RDS name must begin with a letter " +
                f"and contain only alphanumeric characters: {values['name']}")

        parameter_group = values.pop('parameter_group')
        if parameter_group:
            pg_values = self.get_values(parameter_group)
            pg_name = pg_values['name']
            pg_identifier = pg_values.pop('identifier', None) or pg_name
            pg_values['parameter'] = pg_values.pop('parameters')
            pg_tf_resource = \
                aws_db_parameter_group(pg_identifier, **pg_values)
            tf_resources.append(pg_tf_resource)
            values['depends_on'] = [pg_tf_resource]
            values['parameter_group_name'] = pg_name

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

    @staticmethod
    def validate_db_name(name):
        """ Handle for Error creating DB Instance:
        InvalidParameterValue: DBName must begin with a letter
        and contain only alphanumeric characters. """
        pattern = r'^[a-zA-Z][a-zA-Z0-9]+$'
        return re.search(pattern, name)

    def determine_db_password(self, namespace_info, output_resource_name,
                              secret_key='db.password'):
        existing_oc_resource = \
            self.fetch_existing_oc_resource(namespace_info,
                                            output_resource_name)
        if existing_oc_resource is not None:
            enc_password = existing_oc_resource['data'][secret_key]
            return base64.b64decode(enc_password).decode('utf-8')
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
            if str(e).startswith('Error from server (NotFound):'):
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
        versioning = common_values.get('versioning') or True
        values['versioning'] = {"enabled": versioning}
        values['tags'] = common_values['tags']
        values['acl'] = common_values.get('acl') or 'private'
        values['server_side_encryption_configuration'] = \
            common_values.get('server_side_encryption_configuration')
        if common_values.get('lifecycle_rules'):
            # common_values['lifecycle_rules'] is a list of lifecycle_rules
            values['lifecycle_rule'] = common_values['lifecycle_rules']
        sc = common_values.get('storage_class')
        if sc:
            rule = {
                "id": sc + "_storage_class",
                "enabled": "true",
                "transition": {
                    "storage_class": sc
                }
            }
            if values.get('lifecycle_rule'):
                values['lifecycle_rule'].append(rule)
            else:
                values['lifecycle_rule'] = rule
        if common_values.get('cors_rules'):
            # common_values['cors_rules'] is a list of cors_rules
            values['cors_rule'] = common_values['cors_rules']
        deps = []
        replication_configs = common_values.get('replication_configurations')
        if replication_configs:
            rc_configs = []
            for config in replication_configs:
                rc_values = {}

                # iam roles
                # Terraform resource reference:
                # https://www.terraform.io/docs/providers/aws/d/iam_role.html
                id = f"{identifier}_{config['rule_name']}"
                rc_values['name'] = config['rule_name'] + "_iam_role"
                role = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Action": "sts:AssumeRole",
                            "Principal": {
                                "Service": "s3.amazonaws.com"
                            },
                            "Effect": "Allow",
                            "Sid": ""
                        }
                    ]
                }
                rc_values['assume_role_policy'] = role
                role_resource = aws_iam_role(id, **rc_values)
                tf_resources.append(role_resource)

                # iam policy
                # Terraform resource reference:
                # https://www.terraform.io/docs/providers/aws/r/iam_policy.html
                rc_values.clear()
                rc_values['name'] = config['rule_name'] + '_iam_policy'
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Action": [
                                "s3:GetReplicationConfiguration",
                                "s3:ListBucket"
                            ],
                            "Effect": "Allow",
                            "Resource": [
                                "${aws_s3_bucket." + identifier + ".arn}"
                            ]
                        },
                        {
                            "Action": [
                                "s3:GetObjectVersion",
                                "s3:GetObjectVersionAcl"
                            ],
                            "Effect": "Allow",
                            "Resource": [
                                "${aws_s3_bucket." + identifier + ".arn}/*"
                            ]
                        },
                        {
                            "Action": [
                                "s3:ReplicateObject",
                                "s3:ReplicateDelete"
                            ],
                            "Effect": "Allow",
                            "Resource":
                                "${aws_s3_bucket." +
                                config['destination_bucket_identifier'] +
                                ".arn}/*"
                        }
                    ]
                }
                rc_values['policy'] = policy
                policy_resource = aws_iam_policy(id, **rc_values)
                tf_resources.append(policy_resource)

                # iam role policy attachment
                # Terraform resource reference:
                # https://www.terraform.io/docs/providers/aws/r/iam_policy_attachment.html
                rc_values.clear()
                rc_values['depends_on'] = [role_resource, policy_resource]
                rc_values['role'] = "${aws_iam_role." + id + ".name}"
                rc_values['policy_arn'] = "${aws_iam_policy." + id + ".arn}"
                tf_resource = aws_iam_role_policy_attachment(id, **rc_values)
                tf_resources.append(tf_resource)

                # Define the replication configuration.  Use a unique role for
                # each replication configuration for easy cleanup/modification
                deps.append(role_resource)
                rc_values.clear()
                rc_values['role'] = "${aws_iam_role." + id + ".arn}"
                rc_values['rules'] = {
                    'id': config['rule_name'],
                    'status': config['status'],
                    'destination': {
                        'bucket':
                            "${aws_s3_bucket." +
                            config['destination_bucket_identifier'] + ".arn}",
                        'storage_class': config.get('storage_class') or
                        "standard"
                    }
                }
                rc_configs.append(rc_values)
            values['replication_configuration'] = rc_configs
        if len(deps) > 0:
            values['depends_on'] = deps
        bucket_tf_resource = aws_s3_bucket(identifier, **values)
        tf_resources.append(bucket_tf_resource)
        output_name = output_prefix + '[bucket]'
        output_value = '${' + bucket_tf_resource.fullname + '.bucket}'
        tf_resources.append(output(output_name, value=output_value))
        region = common_values['region'] or self.default_regions.get(account)
        output_name = output_prefix + '[aws_region]'
        tf_resources.append(output(output_name, value=region))
        endpoint = 's3.{}.amazonaws.com'.format(region)
        output_name = output_prefix + '[endpoint]'
        tf_resources.append(output(output_name, value=endpoint))

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

        return bucket_tf_resource

    def populate_tf_resource_elasticache(self, resource, namespace_info,
                                         existing_secrets):
        account, identifier, values, output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)
        values.setdefault('replication_group_id', values['identifier'])
        values.pop('identifier', None)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        parameter_group = values['parameter_group']
        if parameter_group:
            pg_values = self.get_values(parameter_group)
            pg_identifier = pg_values['name']
            pg_values['parameter'] = pg_values.pop('parameters')
            pg_tf_resource = \
                aws_elasticache_parameter_group(pg_identifier, **pg_values)
            tf_resources.append(pg_tf_resource)
            values['depends_on'] = [pg_tf_resource]
            values['parameter_group_name'] = pg_identifier
            values.pop('parameter_group', None)

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
                       '.primary_endpoint_address}'
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
        for policy in common_values['policies'] or []:
            tf_iam_user_policy_attachment = \
                aws_iam_user_policy_attachment(
                    identifier + '-' + policy,
                    user=identifier,
                    policy_arn='arn:aws:iam::aws:policy/' + policy,
                    depends_on=[user_tf_resource]
                )
            tf_resources.append(tf_iam_user_policy_attachment)

        user_policy = common_values['user_policy']
        if user_policy:
            variables = common_values['variables']
            # variables are replaced in the user_policy
            # and also added to the output resource
            if variables:
                data = json.loads(variables)
                for k, v in data.items():
                    to_replace = '${' + k + '}'
                    user_policy = user_policy.replace(to_replace, v)
                    output_name = output_prefix + '[{}]'.format(k)
                    tf_resources.append(output(output_name, value=v))
            tf_aws_iam_user_policy = aws_iam_user_policy(
                identifier,
                name=identifier,
                user=identifier,
                policy=user_policy,
                depends_on=[user_tf_resource]
            )
            tf_resources.append(tf_aws_iam_user_policy)

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def populate_tf_resource_sqs(self, resource, namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)
        uid = self.uids.get(account)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)
        region = common_values['region'] or self.default_regions.get(account)
        specs = common_values['specs']
        all_queues_per_spec = []
        for spec in specs:
            defaults = self.get_values(spec['defaults'])
            queues = spec.pop('queues', [])
            all_queues = []
            for queue_kv in queues:
                queue_key = queue_kv['key']
                queue = queue_kv['value']
                all_queues.append(queue)
                # sqs queue
                # Terraform resource reference:
                # https://www.terraform.io/docs/providers/aws/r/sqs_queue.html
                values = {}
                values['name'] = queue
                values['tags'] = common_values['tags']
                values.update(defaults)
                queue_tf_resource = aws_sqs_queue(queue, **values)
                tf_resources.append(queue_tf_resource)
                output_name = output_prefix + '[aws_region]'
                tf_resources.append(output(output_name, value=region))
                output_name = '{}[{}]'.format(output_prefix, queue_key)
                output_value = \
                    'https://sqs.{}.amazonaws.com/{}/{}'.format(
                        region, uid, queue)
                tf_resources.append(output(output_name, value=output_value))
            all_queues_per_spec.append(all_queues)

        # iam resources
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/iam_access_key.html

        # iam user for queue
        values = {}
        values['name'] = identifier
        values['tags'] = common_values['tags']
        user_tf_resource = aws_iam_user(identifier, **values)
        tf_resources.append(user_tf_resource)

        # iam access key for user
        tf_resources.extend(
            self.get_tf_iam_access_key(
                user_tf_resource, identifier, output_prefix))

        # iam policy for queue
        policy_index = 0
        for all_queues in all_queues_per_spec:
            policy_identifier = f"{identifier}-{policy_index}"
            policy_index += 1
            if len(all_queues_per_spec) == 1:
                policy_identifier = identifier
            values = {}
            values['name'] = policy_identifier
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["sqs:*"],
                        "Resource": [
                            "arn:aws:sqs:*:{}:{}".format(uid, q)
                            for q in all_queues
                        ]
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["sqs:ListQueues"],
                        "Resource": "*"
                    }
                ]
            }
            values['policy'] = json.dumps(policy, sort_keys=True)
            policy_tf_resource = aws_iam_policy(policy_identifier, **values)
            tf_resources.append(policy_tf_resource)

            # iam user policy attachment
            values = {}
            values['user'] = identifier
            values['policy_arn'] = \
                '${' + policy_tf_resource.fullname + '.arn}'
            values['depends_on'] = [user_tf_resource, policy_tf_resource]
            tf_resource = \
                aws_iam_user_policy_attachment(policy_identifier, **values)
            tf_resources.append(tf_resource)

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def populate_tf_resource_dynamodb(self, resource, namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)
        uid = self.uids.get(account)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)
        region = common_values['region'] or self.default_regions.get(account)
        specs = common_values['specs']
        all_tables = []
        for spec in specs:
            defaults = self.get_values(spec['defaults'])
            attributes = defaults.pop('attributes')
            tables = spec['tables']
            for table_kv in tables:
                table_key = table_kv['key']
                table = table_kv['value']
                all_tables.append(table)
                # dynamodb table
                # Terraform resource reference:
                # https://www.terraform.io/docs/providers/aws/r/
                # dynamodb_table.html
                values = {}
                values['name'] = table
                values['tags'] = common_values['tags']
                values.update(defaults)
                values['attribute'] = attributes
                table_tf_resource = aws_dynamodb_table(table, **values)
                tf_resources.append(table_tf_resource)
                output_name = '{}[{}]'.format(output_prefix, table_key)
                tf_resources.append(output(output_name, value=table))

        output_name = output_prefix + '[aws_region]'
        tf_resources.append(output(output_name, value=region))
        output_name = output_prefix + '[endpoint]'
        output_value = f"https://dynamodb.{region}.amazonaws.com"
        tf_resources.append(output(output_name, value=output_value))

        # iam resources
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/iam_access_key.html

        # iam user for table
        values = {}
        values['name'] = identifier
        values['tags'] = common_values['tags']
        user_tf_resource = aws_iam_user(identifier, **values)
        tf_resources.append(user_tf_resource)

        # iam access key for user
        tf_resources.extend(
            self.get_tf_iam_access_key(
                user_tf_resource, identifier, output_prefix))

        # iam user policy for queue
        values = {}
        values['user'] = identifier
        values['name'] = identifier
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["dynamodb:*"],
                    "Resource": [
                        "arn:aws:dynamodb:{}:{}:table/{}".format(
                            region, uid, t) for t in all_tables
                    ]
                }
            ]
        }
        values['policy'] = json.dumps(policy, sort_keys=True)
        values['depends_on'] = [user_tf_resource]
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def populate_tf_resource_ecr(self, resource, namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        # ecr repository
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/ecr_repository.html
        values = {}
        values['name'] = identifier
        values['tags'] = common_values['tags']

        ecr_tf_resource = aws_ecr_repository(identifier, **values)
        tf_resources.append(ecr_tf_resource)
        output_name = output_prefix + '[url]'
        output_value = '${' + ecr_tf_resource.fullname + '.repository_url}'
        tf_resources.append(output(output_name, value=output_value))
        region = common_values['region'] or self.default_regions.get(account)
        output_name = output_prefix + '[aws_region]'
        tf_resources.append(output(output_name, value=region))

        # iam resources
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/iam_access_key.html

        # iam user for repository
        values = {}
        values['name'] = identifier
        values['tags'] = common_values['tags']
        values['depends_on'] = [ecr_tf_resource]
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
                    "Sid": "ListImagesInRepository",
                    "Effect": "Allow",
                    "Action": ["ecr:ListImages"],
                    "Resource": "${" + ecr_tf_resource.fullname + ".arn}"
                },
                {
                    "Sid": "GetAuthorizationToken",
                    "Effect": "Allow",
                    "Action": ["ecr:GetAuthorizationToken"],
                    "Resource": "*"
                },
                {
                    "Sid": "ManageRepositoryContents",
                    "Effect": "Allow",
                    "Action": [
                        "ecr:GetAuthorizationToken",
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:GetRepositoryPolicy",
                        "ecr:DescribeRepositories",
                        "ecr:ListImages",
                        "ecr:DescribeImages",
                        "ecr:BatchGetImage",
                        "ecr:InitiateLayerUpload",
                        "ecr:UploadLayerPart",
                        "ecr:CompleteLayerUpload",
                        "ecr:PutImage"
                    ],
                    "Resource": "${" + ecr_tf_resource.fullname + ".arn}"
                }
            ]
        }
        values['policy'] = json.dumps(policy, sort_keys=True)
        values['depends_on'] = [user_tf_resource]
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def populate_tf_resource_s3_cloudfront(self, resource, namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        bucket_tf_resource = \
            self.populate_tf_resource_s3(resource, namespace_info)

        tf_resources = []

        # cloudfront origin access identity
        values = {}
        values['comment'] = f'{identifier}-cf-identity'
        cf_oai_tf_resource = \
            aws_cloudfront_origin_access_identity(identifier, **values)
        tf_resources.append(cf_oai_tf_resource)

        # bucket policy for cloudfront
        values = {}
        values['bucket'] = identifier
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "Grant access to CloudFront Origin Identity",
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": "${" +
                               cf_oai_tf_resource.fullname +
                               ".iam_arn}"
                    },
                    "Action": "s3:GetObject",
                    "Resource":
                        [f"arn:aws:s3:::{identifier}/{enable_dir}/*"
                         for enable_dir
                         in common_values.get('get_object_enable_dirs', [])]
                }
            ]
        }
        values['policy'] = json.dumps(policy, sort_keys=True)
        values['depends_on'] = [bucket_tf_resource]
        bucket_policy_tf_resource = aws_s3_bucket_policy(identifier, **values)
        tf_resources.append(bucket_policy_tf_resource)

        # cloud front distribution
        values = common_values.get('distribution_config', {})
        values['tags'] = common_values['tags']
        values.setdefault(
            'default_cache_behavior', {}).setdefault(
                'target_origin_id', 'default')
        origin = {
            'domain_name':
                '${' + bucket_tf_resource.fullname +
                '.bucket_domain_name}',
            'origin_id':
                values['default_cache_behavior']['target_origin_id'],
            's3_origin_config': {
                'origin_access_identity':
                    'origin-access-identity/cloudfront/' +
                    '${' + cf_oai_tf_resource.fullname + '.id}'
                    }
        }
        values['origin'] = [origin]
        cf_distribution_tf_resource = \
            aws_cloudfront_distribution(identifier, **values)
        tf_resources.append(cf_distribution_tf_resource)

        # outputs
        output_name = output_prefix + \
            '[cloud_front_origin_access_identity_id]'
        output_value = '${' + cf_oai_tf_resource.fullname + \
            '.id}'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_prefix + \
            '[s3_canonical_user_id]'
        output_value = '${' + cf_oai_tf_resource.fullname + \
            '.s3_canonical_user_id}'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_prefix + \
            '[distribution_domain]'
        output_value = '${' + cf_distribution_tf_resource.fullname + \
            '.domain_name}'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_prefix + \
            '[origin_access_identity]'
        output_value = 'origin-access-identity/cloudfront/' + \
            '${' + cf_oai_tf_resource.fullname + '.id}'
        tf_resources.append(output(output_name, value=output_value))

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
        if account not in self.locks:
            logging.warning(
                'integration {} is disabled for account {}. '
                'can not add resource'.format(self.integration, account))
            return
        with self.locks[account]:
            self.tss[account].add(tf_resource)

    def dump(self, print_only=False, existing_dirs=None):
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
            working_dirs[name] = wd

        return working_dirs

    def init_values(self, resource, namespace_info):
        account = resource['account']
        provider = resource['provider']
        identifier = resource['identifier']
        defaults_path = resource.get('defaults', None)
        overrides = resource.get('overrides', None)
        variables = resource.get('variables', None)
        policies = resource.get('policies', None)
        user_policy = resource.get('user_policy', None)
        region = resource.get('region', None)
        queues = resource.get('queues', None)
        specs = resource.get('specs', None)
        parameter_group = resource.get('parameter_group', None)

        values = self.get_values(defaults_path) if defaults_path else {}
        self.aggregate_values(values)
        self.override_values(values, overrides)
        values['identifier'] = identifier
        values['tags'] = self.get_resource_tags(namespace_info)
        values['variables'] = variables
        values['policies'] = policies
        values['user_policy'] = user_policy
        values['region'] = region
        values['queues'] = queues
        values['specs'] = specs
        values['parameter_group'] = parameter_group

        output_prefix = '{}-{}'.format(identifier, provider)
        output_resource_name = resource['output_resource_name']
        if output_resource_name is None:
            output_resource_name = output_prefix

        return account, identifier, values, output_prefix, output_resource_name

    def aggregate_values(self, values):
        split_char = '.'
        copy = values.copy()
        for k, v in copy.items():
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
            raise FetchResourceError(str(e))
        try:
            values = anymarkup.parse(
                raw_values['content'],
                force_types=None
            )
            values.pop('$schema', None)
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
