import tempfile
import random
import string
import base64
import json
import anymarkup
import logging
import re
import requests
import os

import utils.gql as gql
import utils.threaded as threaded
from utils.secret_reader import SecretReader
from reconcile.github_org import get_config

from utils.oc import StatusCodeError
from utils.gpg import gpg_key_valid
from reconcile.exceptions import FetchResourceError
from utils.elasticsearch_exceptions \
  import (ElasticSearchResourceNameInvalidError,
          ElasticSearchResourceMissingSubnetIdError,
          ElasticSearchResourceVersionInvalidError,
          ElasticSearchResourceZoneAwareSubnetInvalidError)

from threading import Lock
from terrascript import Terrascript, provider, terraform, backend, output, data
from terrascript.aws.d import aws_sqs_queue as data_aws_sqs_queue
from terrascript.aws.r import (aws_db_instance, aws_db_parameter_group,
                               aws_s3_bucket, aws_iam_user,
                               aws_s3_bucket_notification,
                               aws_iam_access_key, aws_iam_user_policy,
                               aws_iam_group, aws_iam_group_policy_attachment,
                               aws_iam_user_group_membership,
                               aws_iam_user_login_profile, aws_iam_policy,
                               aws_iam_role, aws_iam_role_policy,
                               aws_iam_role_policy_attachment,
                               aws_elasticache_replication_group,
                               aws_elasticache_parameter_group,
                               aws_iam_user_policy_attachment,
                               aws_sqs_queue, aws_dynamodb_table,
                               aws_ecr_repository, aws_s3_bucket_policy,
                               aws_cloudfront_origin_access_identity,
                               aws_cloudfront_distribution,
                               aws_vpc_peering_connection,
                               aws_vpc_peering_connection_accepter,
                               aws_route,
                               aws_cloudwatch_log_group, aws_kms_key,
                               aws_kms_alias,
                               aws_elasticsearch_domain,
                               aws_iam_service_linked_role,
                               aws_lambda_function, aws_lambda_permission,
                               aws_cloudwatch_log_subscription_filter,
                               aws_acm_certificate,
                               aws_kinesis_stream)

GH_BASE_URL = os.environ.get('GITHUB_API', 'https://api.github.com')
LOGTOES_RELEASE = 'repos/app-sre/logs-to-elasticsearch-lambda/releases/latest'


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
        self.secret_reader = SecretReader(settings=settings)
        self.populate_configs(filtered_accounts)
        tss = {}
        locks = {}
        for name, config in self.configs.items():
            # Ref: https://github.com/mjuenema/python-terrascript#example
            ts = Terrascript()
            supported_regions = config['supportedDeploymentRegions']
            if supported_regions is not None:
                for region in supported_regions:
                    ts += provider('aws',
                                   access_key=config['aws_access_key_id'],
                                   secret_key=config['aws_secret_access_key'],
                                   version=config['aws_provider_version'],
                                   region=region,
                                   alias=region)

            # Add default region, which will always be region in the secret
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
        self.logtoes_zip = ''

    def get_logtoes_zip(self, release_url):
        if not self.logtoes_zip:
            self.logtoes_zip = self.download_logtoes_zip(LOGTOES_RELEASE)
        if release_url == LOGTOES_RELEASE:
            return self.logtoes_zip
        else:
            return self.download_logtoes_zip(release_url)

    def download_logtoes_zip(self, release_url):
        token = get_config()['github']['app-sre']['token']
        headers = {'Authorization': 'token ' + token}
        r = requests.get(GH_BASE_URL + '/' + release_url, headers=headers)
        r.raise_for_status()
        data = r.json()
        zip_url = data['assets'][0]['browser_download_url']
        zip_file = '/tmp/LogsToElasticsearch-' + data['tag_name'] + '.zip'
        if not os.path.exists(zip_file):
            r = requests.get(zip_url)
            r.raise_for_status()
            open(zip_file, 'wb').write(r.content)
        return zip_file

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

    def populate_configs(self, accounts):
        results = threaded.run(self.get_tf_secrets, accounts,
                               self.thread_pool_size)
        self.configs = {account: secret for account, secret in results}

    def get_tf_secrets(self, account):
        account_name = account['name']
        automation_token = account['automationToken']
        secret = self.secret_reader.read_all(automation_token)
        secret['supportedDeploymentRegions'] = \
            account['supportedDeploymentRegions']
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
                                group_name + '-' + policy.replace('/', '_'),
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
                    ok, error_message = gpg_key_valid(user_public_gpg_key)
                    if not ok:
                        msg = \
                            'invalid public gpg key for user {}: {}'.format(
                                user_name, error_message)
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

    def populate_additional_providers(self, accounts):
        for account in accounts:
            account_name = account['name']
            assume_role = account['assume_role']
            # arn:aws:iam::12345:role/role-1 --> 12345
            alias = assume_role.split(':')[4]
            ts = self.tss[account_name]
            config = self.configs[account_name]
            ts += provider('aws',
                           access_key=config['aws_access_key_id'],
                           secret_key=config['aws_secret_access_key'],
                           version=config['aws_provider_version'],
                           region=account['assume_region'],
                           alias=alias,
                           assume_role={'role_arn': assume_role})

    def populate_vpc_peerings(self, desired_state):
        for item in desired_state:
            if item['deleted']:
                continue

            connection_provider = item['connection_provider']
            connection_name = item['connection_name']
            requester = item['requester']
            accepter = item['accepter']

            req_account = requester['account']
            req_account_name = req_account['name']
            # arn:aws:iam::12345:role/role-1 --> 12345
            req_alias = req_account['assume_role'].split(':')[4]

            # Requester's side of the connection - the cluster's account
            identifier = f"{requester['vpc_id']}-{accepter['vpc_id']}"
            values = {
                # adding the alias to the provider will add this resource
                # to the cluster's AWS account
                'provider': 'aws.' + req_alias,
                'vpc_id': requester['vpc_id'],
                'peer_vpc_id': accepter['vpc_id'],
                'peer_region': accepter['region'],
                'peer_owner_id': req_account['uid'],
                'auto_accept': False,
                'tags': {
                    'managed_by_integration': self.integration,
                    # <accepter account uid>-<accepter account vpc id>
                    'Name': connection_name
                }
            }
            req_peer_owner_id = requester.get('peer_owner_id')
            if req_peer_owner_id:
                values['peer_owner_id'] = req_peer_owner_id
            tf_resource = aws_vpc_peering_connection(identifier, **values)
            self.add_resource(req_account_name, tf_resource)

            # add routes to existing route tables
            route_table_ids = requester.get('route_table_ids')
            if route_table_ids:
                for route_table_id in route_table_ids:
                    values = {
                        'provider': 'aws.' + req_alias,
                        'route_table_id': route_table_id,
                        'destination_cidr_block': accepter['cidr_block'],
                        'vpc_peering_connection_id':
                            '${aws_vpc_peering_connection.' +
                            identifier + '.id}'
                    }
                    route_identifier = f'{identifier}-{route_table_id}'
                    tf_resource = aws_route(route_identifier, **values)
                    self.add_resource(req_account_name, tf_resource)

            acc_account = accepter['account']
            acc_account_name = acc_account['name']
            # arn:aws:iam::12345:role/role-1 --> 12345
            acc_alias = acc_account['assume_role'].split(':')[4]

            # Accepter's side of the connection.
            values = {
                'vpc_peering_connection_id':
                    '${aws_vpc_peering_connection.' + identifier + '.id}',
                'auto_accept': True,
                'tags': {
                    'managed_by_integration': self.integration,
                    # <requester account uid>-<requester account vpc id>
                    'Name': connection_name
                }
            }
            if connection_provider == 'account-vpc':
                if self._multiregion_account_(acc_account_name):
                    values['provider'] = 'aws.' + accepter['region']
            else:
                values['provider'] = 'aws.' + acc_alias
            tf_resource = \
                aws_vpc_peering_connection_accepter(identifier, **values)
            self.add_resource(acc_account_name, tf_resource)

            # add routes to existing route tables
            route_table_ids = accepter.get('route_table_ids')
            if route_table_ids:
                for route_table_id in route_table_ids:
                    values = {
                        'route_table_id': route_table_id,
                        'destination_cidr_block': requester['cidr_block'],
                        'vpc_peering_connection_id':
                            '${aws_vpc_peering_connection_accepter.' +
                            identifier + '.id}'
                    }
                    if connection_provider == 'account-vpc':
                        if self._multiregion_account_(acc_account_name):
                            values['provider'] = 'aws.' + accepter['region']
                    else:
                        values['provider'] = 'aws.' + acc_alias
                    route_identifier = f'{identifier}-{route_table_id}'
                    tf_resource = aws_route(route_identifier, **values)
                    self.add_resource(acc_account_name, tf_resource)

    def populate_resources(self, namespaces, existing_secrets, account_name):
        self.init_populate_specs(namespaces, account_name)
        for specs in self.account_resources.values():
            for spec in specs:
                self.populate_tf_resources(spec, existing_secrets)

    def init_populate_specs(self, namespaces, account_name):
        self.account_resources = {}
        for namespace_info in namespaces:
            # Skip if namespace has no terraformResources
            tf_resources = namespace_info.get('terraformResources')
            if not tf_resources:
                continue
            for resource in tf_resources:
                populate_spec = {'resource': resource,
                                 'namespace_info': namespace_info}
                account = resource['account']
                # Skip if account_name is specified
                if account_name and account != account_name:
                    continue
                if account not in self.account_resources:
                    self.account_resources[account] = []
                self.account_resources[account].append(populate_spec)

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
        elif provider == 'aws-iam-service-account':
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
        elif provider == 's3-sqs':
            self.populate_tf_resource_s3_sqs(resource, namespace_info)
        elif provider == 'cloudwatch':
            self.populate_tf_resource_cloudwatch(resource, namespace_info)
        elif provider == 'kms':
            self.populate_tf_resource_kms(resource, namespace_info)
        elif provider == 'elasticsearch':
            self.populate_tf_resource_elasticsearch(resource, namespace_info,
                                                    existing_secrets)
        elif provider == 'acm':
            self.populate_tf_resource_acm(resource, namespace_info,
                                          existing_secrets)
        elif provider == 'kinesis':
            self.populate_tf_resource_kinesis(resource, namespace_info)
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
        # only validate names which are not empty
        if values.get('name') and not self.validate_db_name(values['name']):
            raise FetchResourceError(
                f"[{account}] RDS name must contain 1 to 63 letters, " +
                f"numbers, or underscores. RDS name must begin with a " +
                f"letter. Subsequent characters can be letters, " +
                f"underscores, or digits (0-9): {values['name']}")

        az = values.get('availability_zone')
        provider = ''
        if az is not None and self._multiregion_account_(account):
            values['availability_zone'] = az
            # To get the provider we should use, we get the region
            # and use that as an alias in the provider definition
            provider = 'aws.' + self._region_from_availability_zone_(az)
            values['provider'] = provider

        deps = []
        parameter_group = values.pop('parameter_group')
        if parameter_group:
            pg_values = self.get_values(parameter_group)
            # Parameter group name is not required by terraform.
            # However, our integration has it marked as required.
            # If user does not provide a name, we will use the rds identifier
            # as the name. This will allow us to reuse parameter group config
            # for multiple RDS instances.
            pg_name = pg_values.get('name', values['identifier'] + "-pg")
            pg_identifier = pg_values.pop('identifier', None) or pg_name
            pg_values['name'] = pg_name
            pg_values['parameter'] = pg_values.pop('parameters')
            if self._multiregion_account_(account) and len(provider) > 0:
                pg_values['provider'] = provider
            pg_tf_resource = \
                aws_db_parameter_group(pg_identifier, **pg_values)
            tf_resources.append(pg_tf_resource)
            deps = [pg_tf_resource]
            values['parameter_group_name'] = pg_name

        enhanced_monitoring = values.pop('enhanced_monitoring')

        # monitoring interval should only be set if enhanced monitoring
        # is true
        if (
            not enhanced_monitoring and
            values.get('monitoring_interval', None)
        ):
            values.pop('monitoring_interval')

        if enhanced_monitoring:
            # Set monitoring interval to 60s if it is not set.
            values['monitoring_interval'] = \
                values.get('monitoring_interval', 60)

            assume_role_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Action": "sts:AssumeRole",
                        "Principal": {
                            "Service": "monitoring.rds.amazonaws.com"
                        },
                        "Effect": "Allow"
                    }
                ]
            }
            em_identifier = f"{identifier}-enhanced-monitoring"
            em_values = {
                'name': em_identifier,
                'assume_role_policy':
                    json.dumps(assume_role_policy, sort_keys=True)
            }
            role_tf_resource = aws_iam_role(em_identifier, **em_values)
            tf_resources.append(role_tf_resource)

            em_values = {
                'role':
                    "${" + role_tf_resource.fullname + ".name}",
                'policy_arn':
                    "arn:aws:iam::aws:policy/service-role/" +
                    "AmazonRDSEnhancedMonitoringRole",
                'depends_on': [role_tf_resource]
            }
            tf_resource = \
                aws_iam_role_policy_attachment(em_identifier, **em_values)
            tf_resources.append(tf_resource)

            values['monitoring_role_arn'] = \
                "${" + role_tf_resource.fullname + ".arn}"

        reset_password_current_value = values.pop('reset_password', None)
        if self._db_needs_auth_(values):
            reset_password = self._should_reset_password(
                reset_password_current_value,
                existing_secrets,
                account,
                output_prefix
            )
            if reset_password:
                password = self.generate_random_password()
            else:
                try:
                    existing_secret = existing_secrets[account][output_prefix]
                    password = \
                        existing_secret['db.password']
                except KeyError:
                    password = \
                        self.determine_db_password(namespace_info,
                                                   output_resource_name)
        else:
            password = ""
        values['password'] = password

        region = self._region_from_availability_zone_(
            az) or self.default_regions.get(account)
        replica_source = values.pop('replica_source', None)
        if replica_source:
            if 'replicate_source_db' in values:
                raise ValueError(
                    f"only one of replicate_source_db or replica_source " +
                    "can be defined")
            source_info = self._find_resource_(account, replica_source, 'rds')
            if source_info:
                values['backup_retention_period'] = 0
                deps.append("aws_db_instance." +
                            source_info['resource']['identifier'])
                replica_az = source_info.get('availability_zone', None)
                if replica_az and len(replica_az) > 1:
                    replica_region = self._region_from_availability_zone_(
                        replica_az)
                else:
                    replica_region = self.default_regions.get(account)
                _, _, source_values, _, _ = self.init_values(
                    source_info['resource'], source_info['namespace_info'])
                if replica_region == region:
                    # replica is in the same region as source
                    values['replicate_source_db'] = replica_source
                    # Should only be set for read replica if source is in
                    # another region
                    values.pop('db_subnet_group_name', None)
                else:
                    # replica is in different region from source
                    values['replicate_source_db'] = "${aws_db_instance." + \
                        replica_source + ".arn}"

                    # db_subnet_group_name must be defined for a source db
                    # in a different region
                    if 'db_subnet_group_name' not in values:
                        raise ValueError(
                            f"db_subnet_group_name must be defined if " +
                            "read replica source in different region")

                    # storage_encrypted is ignored for cross-region replicas
                    encrypt = values.get('storage_encrypted', None)
                    if encrypt and 'kms_key_id' not in values:
                        raise ValueError(
                            f"storage_encrypted ignored for cross-region " +
                            "read replica.  Set kms_key_id")

                # Read Replicas shouldn't set these values as they come from
                # the source db
                remove_params = ['allocated_storage',
                                 'engine', 'password', 'username']
                for param in remove_params:
                    values.pop(param, None)

                # Source RDS must have these parameters set
                source_brp = source_values.get('backup_retention_period', 0)
                if source_brp <= 0:
                    raise ValueError(
                        f"can not use {replica_source} as replica_source " +
                        "because backup_retention_period must be greater " +
                        "than 0")
            else:
                raise FetchResourceError(
                    f"source {replica_source} for read replica " +
                    f"{identifier} not found")

        kms_key_id = values.pop('kms_key_id', None)
        if kms_key_id:
            if not kms_key_id.startswith("arn:", 0):
                kms_key = self._find_resource_(account, kms_key_id, 'kms')
                if kms_key:
                    res = kms_key['resource']
                    values['kms_key_id'] = "${aws_kms_key." + \
                        res['identifier'] + ".arn}"
                    deps.append("aws_kms_key." + res['identifier'])
                else:
                    raise ValueError(f"failed to find kms key {kms_key_id}")

        if len(deps) > 0:
            values['depends_on'] = deps

        # pop alternate db name from value before creating the db instance
        # this will only affect the output Secret
        output_resource_db_name = values.pop('output_resource_db_name', None)

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
        output_value = output_resource_db_name or values.get('name', '')
        tf_resources.append(output(output_name, value=output_value))
        # only set db user/password if not a replica or creation from snapshot
        if self._db_needs_auth_(values):
            # db.user
            output_name = output_prefix + '[db.user]'
            output_value = values['username']
            tf_resources.append(output(output_name, value=output_value))
            # db.password
            output_name = output_prefix + '[db.password]'
            output_value = values['password']
            tf_resources.append(output(output_name, value=output_value))
            # only add reset_password key to the terraform state
            # if reset_password_current_value is defined.
            # this means that if the reset_password field is removed
            # from the rds definition in app-interface, the key will be
            # removed from the state and from the output resource,
            # leading to a recycle of the pods using this resource.
            if reset_password_current_value:
                output_name = output_prefix + '[reset_password]'
                output_value = reset_password_current_value
                tf_resources.append(output(output_name, value=output_value))

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    @staticmethod
    def _should_reset_password(current_value, existing_secrets,
                               account, output_prefix):
        """
        If the current value (graphql) of reset_password
        is different from the existing value (terraform state)
        password should be reset.
        """
        if current_value:
            try:
                existing_secret = existing_secrets[account][output_prefix]
                existing_value = \
                    existing_secret['reset_password']
            except KeyError:
                existing_value = None
            if current_value != existing_value:
                return True
        return False

    def _multiregion_account_(self, name):
        if name not in self.configs:
            return False

        if self.configs[name]['supportedDeploymentRegions'] is not None:
            return True

        return False

    def _find_resource_(self, account, source, provider):
        if account not in self.account_resources:
            return None

        for res in self.account_resources[account]:
            r = res['resource']
            if r['identifier'] == source and r['provider'] == provider:
                return res
        return None

    @staticmethod
    def _region_from_availability_zone_(az):
        # Find the region by removing the last character from the
        # availability zone. Availability zone is defined like
        # us-east-1a, us-east-1b, etc.  If there is no availability
        # zone, return emmpty string
        if az and len(az) > 1:
            return az[:-1]
        return None

    @staticmethod
    def _db_needs_auth_(config):
        if 'replicate_source_db' not in config and \
           config.get('replica_source', None) is None:
            return True
        return False

    @staticmethod
    def validate_db_name(name):
        """ Handle for Error creating DB Instance:
        InvalidParameterValue: DBName must begin with a letter
        and contain only alphanumeric characters. """
        pattern = r'^[a-zA-Z][a-zA-Z0-9_]+$'
        return re.search(pattern, name) and len(name) < 64

    def determine_db_password(self, namespace_info, output_resource_name,
                              secret_key='db.password'):
        existing_oc_resource = \
            self.fetch_existing_oc_resource(namespace_info,
                                            output_resource_name)
        if existing_oc_resource is not None:
            enc_password = existing_oc_resource['data'].get(secret_key)
            if enc_password:
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
            if not self.oc_map:
                return None
            oc = self.oc_map.get(cluster)
            if not oc:
                logging.log(level=oc.log_level, msg=oc.message)
                return None
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
        if versioning:
            lrs = values.get('lifecycle_rule', [])
            expiration_rule = False
            for lr in lrs:
                if "noncurrent_version_expiration" in lr:
                    expiration_rule = True
                    break
            if not expiration_rule:
                # Add a default noncurrent object expiration rule if
                # if one isn't already set
                rule = {
                    "id": "expire_noncurrent_versions",
                    "enabled": "true",
                    "noncurrent_version_expiration": {
                        "days": 30
                    }
                }
                if len(lrs) > 0:
                    lrs.append(rule)
                else:
                    lrs = rule
        sc = common_values.get('storage_class')
        if sc:
            sc = sc.upper()
            days = "1"
            if sc.endswith("_IA"):
                # Infrequent Access storage class has minimum 30 days
                # before transition
                days = "30"
            rule = {
                "id": sc + "_storage_class",
                "enabled": "true",
                "transition": {
                    "days": days,
                    "storage_class": sc
                },
                "noncurrent_version_transition": {
                    "days": days,
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
                rc_values['assume_role_policy'] = json.dumps(
                    role, sort_keys=True)
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
                rc_values['policy'] = json.dumps(policy, sort_keys=True)
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
                status = config['status']
                sc = config.get('storage_class') or "standard"
                rc_values.clear()
                rc_values['role'] = "${aws_iam_role." + id + ".arn}"
                rc_values['rules'] = {
                    'id': config['rule_name'],
                    'status': status.capitalize(),
                    'destination': {
                        'bucket':
                            "${aws_s3_bucket." +
                            config['destination_bucket_identifier'] + ".arn}",
                        'storage_class': sc.upper()
                    }
                }
                rc_configs.append(rc_values)
            values['replication_configuration'] = rc_configs
        if len(deps) > 0:
            values['depends_on'] = deps
        region = common_values['region'] or self.default_regions.get(account)
        if self._multiregion_account_(account):
            values['provider'] = 'aws.' + region
        values['region'] = region
        bucket_tf_resource = aws_s3_bucket(identifier, **values)
        tf_resources.append(bucket_tf_resource)
        output_name = output_prefix + '[bucket]'
        output_value = '${' + bucket_tf_resource.fullname + '.bucket}'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_prefix + '[aws_region]'
        tf_resources.append(output(output_name, value=region))
        endpoint = 's3.{}.amazonaws.com'.format(region)
        output_name = output_prefix + '[endpoint]'
        tf_resources.append(output(output_name, value=endpoint))

        sqs_identifier = common_values.get('sqs_identifier', None)
        if sqs_identifier is not None:
            sqs_values = {
                'name': sqs_identifier
            }
            if values['provider']:
                sqs_values['provider'] = values['provider']
            sqs_data = data_aws_sqs_queue(sqs_identifier, **sqs_values)
            tf_resources.append(sqs_data)

            events = common_values.get('events', ["s3:ObjectCreated:*"])
            notification_values = {
                'bucket': '${' + bucket_tf_resource.fullname + '.id}',
                'queue': [{
                    'id': sqs_identifier,
                    'queue_arn':
                        '${data.aws_sqs_queue.' + sqs_identifier + '.arn}',
                    'events': events
                }]
            }
            filter_prefix = common_values.get('filter_prefix', None)
            if filter_prefix is not None:
                notification_values['queue'][0]['filter_prefix'] = \
                    filter_prefix
            filter_suffix = common_values.get('filter_suffix', None)
            if filter_suffix is not None:
                notification_values['queue'][0]['filter_suffix'] = \
                    filter_suffix

            notification_tf_resource = aws_s3_bucket_notification(
                sqs_identifier, **notification_values)
            tf_resources.append(notification_tf_resource)

        bucket_policy = common_values['bucket_policy']
        if bucket_policy:
            values = {
                'bucket': identifier,
                'policy': bucket_policy,
                'depends_on': [bucket_tf_resource]
            }
            bucket_policy_tf_resource = \
                aws_s3_bucket_policy(identifier, **values)
            tf_resources.append(bucket_policy_tf_resource)

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

        action = ["s3:*Object"]
        allow_object_tagging = common_values.get('allow_object_tagging', False)
        if allow_object_tagging:
            action.append("s3:*ObjectTagging")

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
                    "Action": action,
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

        region = values.pop('region', self.default_regions.get(account))
        provider = ''
        if region is not None and self._multiregion_account_(account):
            provider = 'aws.' + region
            values['provider'] = provider

        parameter_group = values['parameter_group']
        if parameter_group:
            pg_values = self.get_values(parameter_group)
            pg_identifier = pg_values['name']
            pg_values['parameter'] = pg_values.pop('parameters')
            if self._multiregion_account_(account) and len(provider) > 0:
                pg_values['provider'] = provider
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

        if values.get('transit_encryption_enabled', False):
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
        if values.get('transit_encryption_enabled', False):
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
        kms_keys = set()
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
                if self._multiregion_account_(account):
                    values['provider'] = 'aws.' + region
                values.update(defaults)
                kms_master_key_id = values.pop('kms_master_key_id', None)
                if kms_master_key_id is not None:
                    if not kms_master_key_id.startswith("arn:"):
                        kms_key = self._find_resource_(
                            account, kms_master_key_id, 'kms')
                        if kms_key:
                            kms_res = "aws_kms_key." + \
                                kms_key['resource']['identifier']
                            values['kms_master_key_id'] = \
                                "${" + kms_res + ".arn}"
                            values['depends_on'] = [kms_res]
                        else:
                            raise ValueError(
                                f"failed to find kms key {kms_master_key_id}")
                    kms_keys.add(values['kms_master_key_id'])
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
            if len(kms_keys):
                kms_statement = {
                    "Effect": "Allow",
                    "Action": ["kms:Decrypt"],
                    "Resource": list(kms_keys)
                }
                policy['Statement'].append(kms_statement)
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
                if self._multiregion_account_(account):
                    values['provider'] = 'aws.' + region
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

        region = common_values['region'] or self.default_regions.get(account)
        if self._multiregion_account_(account):
            values['provider'] = 'aws.' + region
        ecr_tf_resource = aws_ecr_repository(identifier, **values)
        tf_resources.append(ecr_tf_resource)
        output_name = output_prefix + '[url]'
        output_value = '${' + ecr_tf_resource.fullname + '.repository_url}'
        tf_resources.append(output(output_name, value=output_value))
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
        region = common_values['region'] or self.default_regions.get(account)
        if self._multiregion_account_(account):
            values['provider'] = 'aws.' + region
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

    def populate_tf_resource_s3_sqs(self, resource, namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)
        uid = self.uids.get(account)

        bucket_tf_resource = \
            self.populate_tf_resource_s3(resource, namespace_info)

        tf_resources = []
        sqs_identifier = f'{identifier}-sqs'
        sqs_values = {
            'name': sqs_identifier
        }

        visibility_timeout_seconds = \
            int(common_values.get('visibility_timeout_seconds', 30))
        if visibility_timeout_seconds in range(0, 43200):
            sqs_values['visibility_timeout_seconds'] = \
                visibility_timeout_seconds

        message_retention_seconds = \
            int(common_values.get('message_retention_seconds', 345600))
        if visibility_timeout_seconds in range(60, 1209600):
            sqs_values['message_retention_seconds'] = \
                message_retention_seconds

        kms_master_key_id = common_values.get('kms_master_key_id', None)
        if kms_master_key_id is not None:
            sqs_values['kms_master_key_id'] = kms_master_key_id

        region = common_values['region'] or self.default_regions.get(account)
        if self._multiregion_account_(account):
            sqs_values['provider'] = 'aws.' + region

        sqs_tf_resource = aws_sqs_queue(sqs_identifier, **sqs_values)
        tf_resources.append(sqs_tf_resource)

        events = common_values.get('events', ["s3:ObjectCreated:*"])
        notification_values = {
            'bucket': '${' + bucket_tf_resource.fullname + '.id}',
            'queue': [{
                'id': sqs_identifier,
                'queue_arn':
                    '${' + sqs_tf_resource.fullname + '.arn}',
                'events': events
            }]
        }

        filter_prefix = common_values.get('filter_prefix', None)
        if filter_prefix is not None:
            notification_values['queue'][0]['filter_prefix'] = filter_prefix
        filter_suffix = common_values.get('filter_suffix', None)
        if filter_suffix is not None:
            notification_values['queue'][0]['filter_suffix'] = filter_suffix

        notification_tf_resource = aws_s3_bucket_notification(
            sqs_identifier, **notification_values)
        tf_resources.append(notification_tf_resource)

        # iam resources
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/iam_access_key.html

        # iam user for queue
        values = {}
        values['name'] = sqs_identifier
        user_tf_resource = aws_iam_user(sqs_identifier, **values)
        tf_resources.append(user_tf_resource)

        # iam access key for user
        values = {}
        values['user'] = sqs_identifier
        values['depends_on'] = [user_tf_resource]
        access_key_tf_resource = aws_iam_access_key(sqs_identifier, **values)
        tf_resources.append(access_key_tf_resource)
        output_name = output_prefix + '[sqs_aws_access_key_id]'
        output_value = '${' + access_key_tf_resource.fullname + '.id}'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_prefix + '[sqs_aws_secret_access_key]'
        output_value = '${' + access_key_tf_resource.fullname + '.secret}'
        tf_resources.append(output(output_name, value=output_value))

        # iam policy for queue
        values = {}
        values['name'] = sqs_identifier
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["sqs:*"],
                    "Resource": [
                        "arn:aws:sqs:*:{}:{}".format(uid, sqs_identifier)
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
        policy_tf_resource = aws_iam_policy(sqs_identifier, **values)
        tf_resources.append(policy_tf_resource)

        # iam user policy attachment
        values = {}
        values['user'] = sqs_identifier
        values['policy_arn'] = \
            '${' + policy_tf_resource.fullname + '.arn}'
        values['depends_on'] = [user_tf_resource, policy_tf_resource]
        user_policy_attachment_tf_resource = \
            aws_iam_user_policy_attachment(sqs_identifier, **values)
        tf_resources.append(user_policy_attachment_tf_resource)

        # outputs
        output_name = '{}[{}]'.format(output_prefix, sqs_identifier)
        output_value = \
            'https://sqs.{}.amazonaws.com/{}/{}'.format(
                region, uid, sqs_identifier)
        tf_resources.append(output(output_name, value=output_value))

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def populate_tf_resource_cloudwatch(self, resource, namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        # ecr repository
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/
        # cloudwatch_log_group.html
        values = {
            'name': identifier,
            'tags': common_values['tags'],
            'retention_in_days':
                self._get_retention_in_days(
                    common_values, account, identifier)
        }

        region = common_values['region'] or self.default_regions.get(account)
        provider = ''
        if self._multiregion_account_(account):
            provider = 'aws.' + region
            values['provider'] = provider
        log_group_tf_resource = aws_cloudwatch_log_group(identifier, **values)
        tf_resources.append(log_group_tf_resource)

        es_identifier = common_values.get('es_identifier', None)
        if es_identifier is not None:

            assume_role_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Action": "sts:AssumeRole",
                        "Principal": {
                            "Service": "lambda.amazonaws.com"
                        },
                        "Effect": "Allow"
                    }
                ]
            }

            role_identifier = f"{identifier}-lambda-execution-role"
            role_values = {
                'name': role_identifier,
                'assume_role_policy':
                    json.dumps(assume_role_policy, sort_keys=True)
            }

            role_tf_resource = aws_iam_role(role_identifier, **role_values)
            tf_resources.append(role_tf_resource)

            policy_identifier = f"{identifier}-lambda-execution-policy"
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents",
                            "ec2:CreateNetworkInterface",
                            "ec2:DescribeNetworkInterfaces",
                            "ec2:DeleteNetworkInterface"
                        ],
                        "Resource": "*"
                    },
                    {
                        "Effect": "Allow",
                        "Action": "es:*",
                        "Resource": "arn:aws:es:*"
                    }
                ]
            }

            policy_values = {
                'role': "${" + role_tf_resource.fullname + ".id}",
                'policy': json.dumps(policy, sort_keys=True)
            }
            policy_tf_resource = \
                aws_iam_role_policy(policy_identifier, **policy_values)
            tf_resources.append(policy_tf_resource)

            es_domain = {
                'domain_name': es_identifier
            }
            if provider:
                es_domain['provider'] = provider
            tf_resources.append(data('aws_elasticsearch_domain',
                                     es_identifier, **es_domain))

            release_url = common_values.get('release_url', LOGTOES_RELEASE)
            zip_file = self.get_logtoes_zip(release_url)

            lambda_identifier = f"{identifier}-lambda"
            lambda_values = {
                'filename': zip_file,
                'source_code_hash':
                    '${filebase64sha256("' + zip_file + '")}',
                'role': "${" + role_tf_resource.fullname + ".arn}"
            }

            lambda_values["function_name"] = lambda_identifier
            lambda_values["runtime"] = \
                common_values.get('runtime', 'nodejs10.x')
            lambda_values["timeout"] = \
                common_values.get('timeout', 30)
            lambda_values["handler"] = \
                common_values.get('handler', 'index.handler')
            lambda_values["memory_size"] = \
                common_values.get('memory_size', 128)

            lambda_values["vpc_config"] = {
                'subnet_ids': [
                    "${data.aws_elasticsearch_domain." + es_identifier +
                    ".vpc_options.0.subnet_ids}"
                ],
                'security_group_ids': [
                    "${data.aws_elasticsearch_domain." + es_identifier +
                    ".vpc_options.0.security_group_ids}"
                ]
            }

            lambda_values["environment"] = {
                'variables': {
                    'es_endpoint':
                        '${data.aws_elasticsearch_domain.' + es_identifier +
                        '.endpoint}'
                }
            }

            if provider:
                lambda_values['provider'] = provider
            lambds_tf_resource = \
                aws_lambda_function(lambda_identifier, **lambda_values)
            tf_resources.append(lambds_tf_resource)

            permission_vaules = {
                'statement_id': 'cloudwatch_allow',
                'action': 'lambda:InvokeFunction',
                'function_name': "${" + lambds_tf_resource.fullname + ".arn}",
                'principal': 'logs.amazonaws.com',
                'source_arn': "${" + log_group_tf_resource.fullname + ".arn}"
            }

            if provider:
                permission_vaules['provider'] = provider
            permission_tf_resource = \
                aws_lambda_permission(lambda_identifier, **permission_vaules)
            tf_resources.append(permission_tf_resource)

            subscription_vaules = {
                'name': lambda_identifier,
                'log_group_name':
                    "${" + log_group_tf_resource.fullname + ".name}",
                'destination_arn':
                    "${" + lambds_tf_resource.fullname + ".arn}",
                'filter_pattern': "",
                'depends_on': [log_group_tf_resource]
            }

            filter_pattern = common_values.get('filter_pattern', None)
            if filter_pattern is not None:
                subscription_vaules["filter_pattern"] = filter_pattern

            if provider:
                subscription_vaules['provider'] = provider
            subscription_tf_resource = \
                aws_cloudwatch_log_subscription_filter(lambda_identifier,
                                                       **subscription_vaules)
            tf_resources.append(subscription_tf_resource)

        output_name = output_prefix + '[log_group_name]'
        output_value = '${' + log_group_tf_resource.fullname + '.name}'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_prefix + '[aws_region]'
        tf_resources.append(output(output_name, value=region))

        # iam resources
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/iam_access_key.html

        # iam user for log group
        values = {
            'name': identifier,
            'tags': common_values['tags'],
            'depends_on': [log_group_tf_resource]
        }
        user_tf_resource = aws_iam_user(identifier, **values)
        tf_resources.append(user_tf_resource)

        # iam access key for user
        tf_resources.extend(
            self.get_tf_iam_access_key(
                user_tf_resource, identifier, output_prefix))

        # iam user policy for log group
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:DescribeLogStreams",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    "Effect": "Allow",
                    "Resource":
                        "${" + log_group_tf_resource.fullname + ".arn}:*"
                },
                {
                    "Action": ["logs:DescribeLogGroups"],
                    "Effect": "Allow",
                    "Resource": "*"
                }
            ]
        }
        values = {
            'user': identifier,
            'name': identifier,
            'policy': json.dumps(policy, sort_keys=True),
            'depends_on': [user_tf_resource]
        }
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def populate_tf_resource_kms(self, resource, namespace_info):
        account, identifier, values, output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)
        values.pop('identifier', None)

        # kms customer master key
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/kms_key.html

        # provide a default description if not provided
        if 'description' not in values:
            values['description'] = 'app-interface created KMS key'

        uppercase = ['key_usage']
        for key in uppercase:
            if key in values:
                values[key] = values[key].upper()
        region = values.pop(
            'region', None) or self.default_regions.get(account)
        if self._multiregion_account_(account):
            values['provider'] = 'aws.' + region

        tf_resource = aws_kms_key(identifier, **values)
        tf_resources.append(tf_resource)

        # key_id
        output_name = output_prefix + '[key_id]'
        output_value = '${' + tf_resource.fullname + '.key_id}'
        tf_resources.append(output(output_name, value=output_value))

        alias_values = {}
        alias_values['name'] = "alias/" + identifier
        alias_values['target_key_id'] = "${aws_kms_key." + identifier + \
                                        ".key_id}"
        if self._multiregion_account_(account):
            alias_values['provider'] = 'aws.' + region
        tf_resource = aws_kms_alias(identifier, **alias_values)
        tf_resources.append(tf_resource)

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def populate_tf_resource_kinesis(self, resource, namespace_info):
        account, identifier, values, output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        # pop identifier since we use values and not common_values
        values.pop('identifier', None)

        # get region and set provider if required
        region = values.pop('region', None) or \
            self.default_regions.get(account)
        if self._multiregion_account_(account):
            values['provider'] = 'aws.' + region

        # kinesis stream
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/kinesis_stream.html
        kinesis_tf_resource = aws_kinesis_stream(identifier, **values)
        tf_resources.append(kinesis_tf_resource)
        output_name = output_prefix + '[stream_name]'
        tf_resources.append(output(output_name, value=identifier))
        output_name = output_prefix + '[aws_region]'
        tf_resources.append(output(output_name, value=region))

        # iam resources
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "kinesis:Get*",
                        "kinesis:Describe*",
                        "kinesis:PutRecord"
                    ],
                    "Resource": [
                        "${" + kinesis_tf_resource.fullname + ".arn}"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "kinesis:ListStreams"
                    ],
                    "Resource": [
                        "*"
                    ]
                }
            ]
        }
        tf_resources.extend(
            self.get_tf_iam_service_user(
                kinesis_tf_resource,
                identifier,
                policy,
                values['tags'],
                output_prefix
            )
        )

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    @staticmethod
    def _get_retention_in_days(values, account, identifier):
        default_retention_in_days = 14
        allowed_retention_in_days = \
            [1, 3, 5, 7, 14, 30, 60, 90, 120, 150,
             180, 365, 400, 545, 731, 1827, 3653]

        retention_in_days = \
            values.get('retention_in_days') or default_retention_in_days
        if retention_in_days not in allowed_retention_in_days:
            logging.error(
                f"[{account}] log group {identifier} " +
                f"retention_in_days '{retention_in_days}' " +
                f"must be one of {allowed_retention_in_days}. " +
                f"defaulting to '{default_retention_in_days}'.")

        return retention_in_days

    def get_tf_iam_service_user(self, dep_tf_resource, identifier, policy,
                                tags, output_prefix):
        # iam resources
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/iam_access_key.html
        tf_resources = []

        # iam user
        values = {}
        values['name'] = identifier
        values['tags'] = tags
        values['depends_on'] = [dep_tf_resource]
        user_tf_resource = aws_iam_user(identifier, **values)
        tf_resources.append(user_tf_resource)

        # iam access key
        tf_resources.extend(
            self.get_tf_iam_access_key(
                user_tf_resource, identifier, output_prefix))

        # iam user policy
        values = {}
        values['user'] = identifier
        values['name'] = identifier
        values['policy'] = json.dumps(policy, sort_keys=True)
        values['depends_on'] = [user_tf_resource]
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        return tf_resources

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
        az = resource.get('availability_zone', None)
        queues = resource.get('queues', None)
        specs = resource.get('specs', None)
        parameter_group = resource.get('parameter_group', None)
        sqs_identifier = resource.get('sqs_identifier', None)
        s3_events = resource.get('s3_events', None)
        bucket_policy = resource.get('bucket_policy', None)
        sc = resource.get('storage_class', None)
        enhanced_monitoring = resource.get('enhanced_monitoring', None)
        replica_source = resource.get('replica_source', None)
        es_identifier = resource.get('es_identifier', None)
        filter_pattern = resource.get('filter_pattern', None)
        secret = resource.get('secret', None)
        output_resource_db_name = \
            resource.get('output_resource_db_name', None)
        reset_password = \
            resource.get('reset_password', None)

        values = self.get_values(defaults_path) if defaults_path else {}
        self.aggregate_values(values)
        self.override_values(values, overrides)
        values['identifier'] = identifier
        values['tags'] = self.get_resource_tags(namespace_info)
        values['variables'] = variables
        values['policies'] = policies
        values['user_policy'] = user_policy
        values['region'] = region
        values['availability_zone'] = az
        values['queues'] = queues
        values['specs'] = specs
        values['parameter_group'] = parameter_group
        values['sqs_identifier'] = sqs_identifier
        values['s3_events'] = s3_events
        values['bucket_policy'] = bucket_policy
        values['storage_class'] = sc
        values['enhanced_monitoring'] = enhanced_monitoring
        values['replica_source'] = replica_source
        values['es_identifier'] = es_identifier
        values['filter_pattern'] = filter_pattern
        values['secret'] = secret
        values['output_resource_db_name'] = output_resource_db_name
        values['reset_password'] = reset_password

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

    @staticmethod
    def validate_elasticsearch_version(version):
        """ Validate ElasticSearch version. """
        return version in [7.7, 7.4, 7.1,
                           6.8, 6.7, 6.5, 6.4, 6.3, 6.2, 6.0,
                           5.6, 5.5, 5.3, 5.1,
                           2.3,
                           1.5]

    @staticmethod
    def get_elasticsearch_service_role_tf_resource():
        """ Service role for ElasticSearch. """
        service_role = {
          'aws_service_name': "es.amazonaws.com"
        }
        return aws_iam_service_linked_role('elasticsearch', **service_role)

    @staticmethod
    def is_elasticsearch_domain_name_valid(name):
        """ Handle for Error creating Elasticsearch:
        InvalidParameterValue: Elasticsearch domain name must start with a
        lowercase letter and must be between 3 and 28 characters. Valid
        characters are a-z (lowercase only), 0-9, and - (hyphen). """
        if len(name) < 3 or len(name) > 28:
            return False
        pattern = r'^[a-z][a-z0-9-]+$'
        return re.search(pattern, name)

    def populate_tf_resource_elasticsearch(self, resource, namespace_info,
                                           existing_secrets):

        account, identifier, values, output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []

        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        if not self.is_elasticsearch_domain_name_valid(values['identifier']):
            raise ElasticSearchResourceNameInvalidError(
                f"[{account}] ElasticSearch domain name must must start with" +
                f" a lowercase letter and must be between 3 and 28 " +
                f"characters. Valid characters are a-z (lowercase only), 0-9" +
                f", and - (hyphen). " +
                f"{values['identifier']}")

        elasticsearch_version = values.get('elasticsearch_version', 7.7)
        if not self.validate_elasticsearch_version(elasticsearch_version):
            raise ElasticSearchResourceVersionInvalidError(
                f"[{account}] Invalid ElasticSearch version" +
                f" {values['elasticsearch_version']} provided" +
                f" for resource {values['identifier']}.")

        es_values = {}
        es_values["domain_name"] = identifier
        es_values["elasticsearch_version"] = elasticsearch_version
        ebs_options = values.get('ebs_options', {})

        es_values["ebs_options"] = {
            "ebs_enabled": ebs_options.get('ebs_enabled', True),
            "volume_size": ebs_options.get('volume_size', '100')
        }

        es_values["encrypt_at_rest"] = {
            "enabled": values.get('encrypt_at_rest', {}).get('enabled', True)
        }

        node_to_node_encryption = values.get('node_to_node_encryption', {})

        es_values["node_to_node_encryption"] = {
            "enabled": node_to_node_encryption.get("enabled", True)
        }

        domain_endpoint_options = values.get('domain_endpoint_options', {})
        tls_security_policy = \
            domain_endpoint_options.get("tls_security_policy",
                                        'Policy-Min-TLS-1-0-2019-07')
        enforce_https = domain_endpoint_options.get("enforce_https", True)
        es_values["domain_endpoint_options"] = {
            "enforce_https": enforce_https,
            "tls_security_policy": tls_security_policy
        }

        cluster_config = values.get('cluster_config', {})
        dedicated_master_enabled = cluster_config.\
            get("dedicated_master_enabled", True)
        dedicated_master_type = cluster_config.\
            get("dedicated_master_type", 't2.small.elasticsearch')
        dedicated_master_count = cluster_config.\
            get("dedicated_master_count", 3)
        zone_awareness_enabled = cluster_config.\
            get("zone_awareness_enabled", True)

        es_values["cluster_config"] = {
            "instance_type": cluster_config.get("instance_type",
                                                't2.small.elasticsearch'),
            "instance_count": cluster_config.get("instance_count", 3),
            "zone_awareness_enabled": zone_awareness_enabled
        }

        if dedicated_master_enabled:
            es_values["cluster_config"]["dedicated_master_enabled"] = \
                dedicated_master_enabled
            es_values["cluster_config"]["dedicated_master_type"] = \
                dedicated_master_type
            es_values["cluster_config"]["dedicated_master_count"] = \
                dedicated_master_count

        if zone_awareness_enabled:
            zone_awareness_config = cluster_config.\
                get("zone_awareness_config", {})
            availability_zone_count = \
                zone_awareness_config.get('availability_zone_count', 3)
            es_values["cluster_config"]['zone_awareness_config'] = {
                'availability_zone_count': availability_zone_count
            }

        snapshot_options = values.get('snapshot_options', {})
        automated_snapshot_start_hour = \
            snapshot_options.get("automated_snapshot_start_hour", 23)

        es_values["snapshot_options"] = {
            "automated_snapshot_start_hour": automated_snapshot_start_hour
        }

        vpc_options = values.get('vpc_options', {})
        security_group_ids = vpc_options.get('security_group_ids', None)
        subnet_ids = vpc_options.get('subnet_ids', None)

        if subnet_ids is None:
            raise ElasticSearchResourceMissingSubnetIdError(
                f"[{account}] No subnet ids provided for Elasticsearch" +
                f" resource {values['identifier']}")

        if not zone_awareness_enabled and len(subnet_ids) > 1:
            raise ElasticSearchResourceZoneAwareSubnetInvalidError(
                f"[{account}] Multiple subnet ids are provided but " +
                f" zone_awareness_enabled is set to false for"
                f" resource {values['identifier']}")

        if availability_zone_count != len(subnet_ids):
            raise ElasticSearchResourceZoneAwareSubnetInvalidError(
                f"[{account}] Subnet ids count does not match " +
                f" availability_zone_count for"
                f" resource {values['identifier']}")

        es_values["vpc_options"] = {
            'subnet_ids': subnet_ids
        }

        if security_group_ids is not None:
            es_values["vpc_options"]['security_group_ids'] = security_group_ids

        advanced_options = values.get('advanced_options', None)
        if advanced_options is not None:
            es_values["advanced_options"] = advanced_options

        svc_role_tf_resource = \
            self.get_elasticsearch_service_role_tf_resource()

        es_values['depends_on'] = [svc_role_tf_resource]
        tf_resources.append(svc_role_tf_resource)

        access_policies = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": "*"
                    },
                    "Action": "es:*",
                    "Resource": "*"
                }
            ]
        }
        es_values['access_policies'] = json.dumps(
            access_policies, sort_keys=True)

        region = values['region'] or self.default_regions.get(account)
        if self._multiregion_account_(account):
            es_values['provider'] = 'aws.' + region

        es_tf_resource = aws_elasticsearch_domain(identifier, **es_values)
        tf_resources.append(es_tf_resource)

        # Setup outputs
        output_name = output_prefix + '[arn]'
        output_value = '${' + es_tf_resource.fullname + '.arn}'
        tf_resources.append(output(output_name, value=output_value))

        output_name = output_prefix + '[domain_id]'
        output_value = '${' + es_tf_resource.fullname + '.domain_id}'
        tf_resources.append(output(output_name, value=output_value))

        output_name = output_prefix + '[domain_name]'
        output_value = '${' + es_tf_resource.fullname + '.domain_name}'
        tf_resources.append(output(output_name, value=output_value))

        output_name = output_prefix + '[endpoint]'
        output_value = 'https://' + \
            '${' + es_tf_resource.fullname + '.endpoint}'
        tf_resources.append(output(output_name, value=output_value))

        output_name = output_prefix + '[kibana_endpoint]'
        output_value = 'https://' + \
            '${' + es_tf_resource.fullname + '.kibana_endpoint}'
        tf_resources.append(output(output_name, value=output_value))

        output_name = output_prefix + '[vpc_id]'
        output_value = '${' + es_tf_resource.fullname + \
            '.vpc_options.0.vpc_id}'
        tf_resources.append(output(output_name, value=output_value))

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)

    def populate_tf_resource_acm(self, resource, namespace_info,
                                 existing_secrets):
        account, identifier, common_values, \
            output_prefix, output_resource_name = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info,
                                 output_prefix, output_resource_name)

        secret = common_values.get('secret', None)
        secret_data = self.secret_reader.read_all(secret)

        key = secret_data.get('key', None)
        if key is None:
            raise KeyError(
                    f"Vault secret '{secret['path']}' " +
                    f"does not have required key [key]")

        certificate = secret_data.get('certificate', None)
        if certificate is None:
            raise KeyError(
                    f"Vault secret '{secret['path']}' " +
                    f"does not have required key [certificate]")

        caCertificate = secret_data.get('caCertificate', None)

        values = {
            'private_key': key,
            'certificate_body': certificate
        }
        if caCertificate is not None:
            values['certificate_chain'] = caCertificate

        region = common_values['region'] or self.default_regions.get(account)
        if self._multiregion_account_(account):
            values['provider'] = 'aws.' + region

        acm_tf_resource = aws_acm_certificate(identifier, **values)
        tf_resources.append(acm_tf_resource)

        output_name = output_prefix + '[arn]'
        output_value = '${' + acm_tf_resource.fullname + '.arn}'
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_prefix + '[key]'
        output_value = key
        tf_resources.append(output(output_name, value=output_value))
        output_name = output_prefix + '[certificate]'
        output_value = certificate
        tf_resources.append(output(output_name, value=output_value))
        if caCertificate is not None:
            output_name = output_prefix + '[caCertificate]'
            output_value = caCertificate
            tf_resources.append(output(output_name, value=output_value))

        for tf_resource in tf_resources:
            self.add_resource(account, tf_resource)
