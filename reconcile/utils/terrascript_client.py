import base64
from dataclasses import dataclass
import enum
import json
import logging
import os
import random
import re
import string
import tempfile

from threading import Lock

from typing import (
    Any, Dict, List, Iterable, Mapping, MutableMapping, Optional, Tuple, cast
)
from ipaddress import ip_network, ip_address

import anymarkup
import requests
from github import Github


from terrascript import (Terrascript, provider, Provider, Terraform,
                         Backend, Output, data)
from terrascript.resource import (
    aws_db_instance, aws_db_parameter_group,
    aws_s3_bucket, aws_iam_user,
    aws_s3_bucket_notification,
    aws_iam_access_key, aws_iam_user_policy,
    aws_iam_group,
    aws_iam_group_policy_attachment,
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
    aws_ram_resource_share,
    aws_ram_principal_association,
    aws_ram_resource_association,
    aws_ram_resource_share_accepter,
    aws_ec2_transit_gateway_vpc_attachment,
    aws_ec2_transit_gateway_vpc_attachment_accepter,
    aws_ec2_transit_gateway_route,
    aws_security_group,
    aws_security_group_rule,
    aws_route,
    aws_cloudwatch_log_group,
    aws_cloudwatch_log_resource_policy,
    aws_kms_key,
    aws_kms_alias,
    aws_elasticsearch_domain,
    aws_iam_service_linked_role,
    aws_lambda_function, aws_lambda_permission,
    aws_cloudwatch_log_subscription_filter,
    aws_acm_certificate,
    aws_kinesis_stream,
    aws_route53_zone,
    aws_route53_record,
    aws_route53_health_check,
    aws_cloudfront_public_key,
    aws_lb,
    aws_lb_target_group,
    aws_lb_target_group_attachment,
    aws_lb_listener,
    aws_lb_listener_rule,
    aws_secretsmanager_secret,
    aws_secretsmanager_secret_version,
    aws_iam_instance_profile,
    aws_launch_template,
    aws_autoscaling_group,
    random_id,
)
# temporary to create aws_ecrpublic_repository
from terrascript import Resource
from sretoolbox.utils import threaded

from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.jenkins_api import JenkinsApi
from reconcile.utils.ocm import OCMMap
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.git import is_file_in_git_repo
from reconcile.github_org import get_default_config
from reconcile.utils.gpg import gpg_key_valid
from reconcile.utils.exceptions import (FetchResourceError,
                                        PrintToFileInGitRepositoryError)
from reconcile.utils.elasticsearch_exceptions \
    import (ElasticSearchResourceNameInvalidError,
            ElasticSearchResourceMissingSubnetIdError,
            ElasticSearchResourceZoneAwareSubnetInvalidError)
import reconcile.openshift_resources_base as orb
import reconcile.utils.aws_helper as awsh


GH_BASE_URL = os.environ.get('GITHUB_API', 'https://api.github.com')
LOGTOES_RELEASE = 'repos/app-sre/logs-to-elasticsearch-lambda/releases/latest'
VARIABLE_KEYS = ['region', 'availability_zone', 'parameter_group', 'name',
                 'enhanced_monitoring', 'replica_source',
                 'output_resource_db_name', 'reset_password', 'ca_cert',
                 'sqs_identifier', 's3_events', 'bucket_policy',
                 'event_notifications', 'storage_class', 'kms_encryption',
                 'variables', 'policies', 'user_policy', 'secrets_prefix',
                 'es_identifier', 'filter_pattern',
                 'specs', 'secret', 'public', 'domain',
                 'aws_infrastructure_access', 'cloudinit_configs', 'image',
                 'assume_role', 'inline_policy', 'assume_condition']


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super().__init__("unknown provider error: " + str(msg))


def safe_resource_id(s):
    """Sanitize a string into a valid terraform resource id"""
    res = s.translate({ord(c): "_" for c in "."})
    res = res.replace("*", "_star")
    return res


class aws_ecrpublic_repository(Resource):
    pass


# temporary until we upgrade to a terrascript release
# that supports this provider
# https://github.com/mjuenema/python-terrascript/pull/166
class time(Provider):
    pass


# temporary until we upgrade to a terrascript release
# that supports this resource
# https://github.com/mjuenema/python-terrascript/pull/166
class time_sleep(Resource):
    pass


class ElasticSearchLogGroupType(enum.Enum):
    INDEX_SLOW_LOGS = 'INDEX_SLOW_LOGS'
    SEARCH_SLOW_LOGS = 'SEARCH_SLOW_LOGS'
    ES_APPLICATION_LOGS = 'ES_APPLICATION_LOGS'


@dataclass
class ElasticSearchLogGroupInfo:
    account: str
    account_id: str
    region: str
    log_group_identifier: str


class TerrascriptClient:  # pylint: disable=too-many-public-methods
    """
    At a high-level, this class is responsible for generating Terraform configuration in
    JSON format from app-interface schemas/openshift/terraform-resource-1.yml objects.

    Usage example (mostly to demonstrate API):

    ts = TerrascriptClient("terraform_resources", "qrtf", 20, accounts, settings)
    ts.populate_resources(tf_namespaces, existing_secrets, account_name, ocm_map=ocm_map)
    ts.dump(print_to_file, existing_dirs=working_dirs)

    More information on Terrascript: https://python-terrascript.readthedocs.io/en/develop/
    """
    def __init__(self, integration: str, integration_prefix: str,
                 thread_pool_size: int, accounts: list[dict[str, Any]],
                 settings: Optional[Mapping[str, Any]] = None) -> None:
        self.integration = integration
        self.integration_prefix = integration_prefix
        self.settings = settings
        self.thread_pool_size = thread_pool_size
        filtered_accounts = self.filter_disabled_accounts(accounts)
        self.secret_reader = SecretReader(settings=settings)
        self.populate_configs(filtered_accounts)
        self.versions = {a['name']: a['providerVersion']
                         for a in filtered_accounts}
        tss = {}
        locks = {}
        self.supported_regions = {}
        for name, config in self.configs.items():
            # Ref: https://github.com/mjuenema/python-terrascript#example
            ts = Terrascript()
            supported_regions = config['supportedDeploymentRegions']
            self.supported_regions[name] = supported_regions
            if supported_regions is not None:
                for region in supported_regions:
                    ts += provider.aws(
                        access_key=config['aws_access_key_id'],
                        secret_key=config['aws_secret_access_key'],
                        version=self.versions.get(name),
                        region=region,
                        alias=region)

            # Add default region, which will be in resourcesDefaultRegion
            ts += provider.aws(
                access_key=config['aws_access_key_id'],
                secret_key=config['aws_secret_access_key'],
                version=self.versions.get(name),
                region=config['resourcesDefaultRegion'])

            # the time provider can be removed if all AWS accounts
            # upgrade to a provider version with this bug fix
            # https://github.com/hashicorp/terraform-provider-aws/pull/20926
            ts += time(
                version="0.7.2"
            )

            ts += provider.random(
                version="3.1.0"
            )

            ts += provider.template(
                version="2.2.0"
            )

            b = Backend("s3",
                        access_key=config['aws_access_key_id'],
                        secret_key=config['aws_secret_access_key'],
                        bucket=config['bucket'],
                        key=config['{}_key'.format(integration)],
                        region=config['region'])
            ts += Terraform(backend=b)
            tss[name] = ts
            locks[name] = Lock()

        self.tss: dict[str, Terrascript] = tss
        """AWS account name to Terrascript mapping."""

        self.locks: dict[str, Lock] = locks
        """AWS account name to Lock mapping."""

        self.accounts = {a['name']: a for a in filtered_accounts}
        self.uids = {a['name']: a['uid'] for a in filtered_accounts}
        self.default_regions = {a['name']: a['resourcesDefaultRegion']
                                for a in filtered_accounts}
        self.partitions = {a['name']: a.get('partition') or 'aws'
                           for a in filtered_accounts}
        self.logtoes_zip = ''
        self.logtoes_zip_lock = Lock()
        self.github: Optional[Github] = None
        self.github_lock = Lock()

    def get_logtoes_zip(self, release_url):
        if not self.logtoes_zip:
            with self.logtoes_zip_lock:
                # this may have already happened, so we check again
                if not self.logtoes_zip:
                    self.token = get_default_config()['token']
                    self.logtoes_zip = \
                        self.download_logtoes_zip(LOGTOES_RELEASE)
        if release_url == LOGTOES_RELEASE:
            return self.logtoes_zip
        else:
            return self.download_logtoes_zip(release_url)

    def download_logtoes_zip(self, release_url):
        headers = {'Authorization': 'token ' + self.token}
        r = requests.get(GH_BASE_URL + '/' + release_url, headers=headers)
        r.raise_for_status()
        data = r.json()
        zip_url = data['assets'][0]['browser_download_url']
        zip_file = '/tmp/LogsToElasticsearch-' + data['tag_name'] + '.zip'
        if not os.path.exists(zip_file):
            r = requests.get(zip_url)
            r.raise_for_status()
            # pylint: disable=consider-using-with
            open(zip_file, 'wb').write(r.content)
        return zip_file

    def init_github(self) -> Github:
        if not self.github:
            with self.github_lock:
                if not self.github:
                    token = get_default_config()['token']
                    self.github = Github(token, base_url=GH_BASE_URL)
        return self.github

    def init_jenkins(self, instance: dict) -> JenkinsApi:
        return JenkinsApi(instance['token'], settings=self.settings)

    def filter_disabled_accounts(self, accounts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
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

    def populate_configs(self, accounts: Iterable[awsh.Account]):
        results = threaded.run(awsh.get_tf_secrets, accounts,
                               self.thread_pool_size,
                               secret_reader=self.secret_reader)
        self.configs: Dict[str, Dict] = {}
        for account_name, config in results:
            account = awsh.get_account(accounts, account_name)
            config['supportedDeploymentRegions'] = account['supportedDeploymentRegions']
            config['resourcesDefaultRegion'] = account['resourcesDefaultRegion']
            self.configs[account_name] = config

    def _get_partition(self, account):
        return self.partitions.get(account) or 'aws'

    @staticmethod
    def get_tf_iam_group(group_name):
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
                        policy_arn = \
                            f'arn:{self._get_partition(account_name)}:' + \
                            f'iam::aws:policy/{policy}'
                        tf_iam_group_policy_attachment = \
                            aws_iam_group_policy_attachment(
                                group_name + '-' + policy.replace('/', '_'),
                                group=group_name,
                                policy_arn=policy_arn,
                                depends_on=self.get_dependencies(
                                    [tf_iam_group])
                            )
                        self.add_resource(account_name,
                                          tf_iam_group_policy_attachment)
                    groups[account_name][group_name] = 'Done'
        return groups

    @staticmethod
    def _get_aws_username(user):
        return user.get('aws_username') or user['org_username']

    @staticmethod
    def _validate_mandatory_policies(
        account: Mapping[str, Any],
        user_policies: Iterable[Mapping[str, Any]],
        role_name: str
    ) -> bool:
        ok = True
        mandatory_policies = \
            [p for p in account.get('policies') or [] if p.get('mandatory')]
        for mp in mandatory_policies:
            if mp not in user_policies:
                msg = \
                    f"[{account['name']}] mandatory policy " + \
                    f"{mp['name']} not associated to role {role_name}"
                logging.error(msg)
                ok = False
        return ok

    def populate_iam_users(self, roles):
        error = False
        for role in roles:
            users = role['users']
            if len(users) == 0:
                continue

            aws_groups = role['aws_groups'] or []
            user_policies = role['user_policies'] or []

            for aws_group in aws_groups:
                group_name = aws_group['name']
                account = aws_group['account']
                account_name = account['name']
                account_console_url = account['consoleUrl']

                ok = self._validate_mandatory_policies(
                    account, user_policies, role['name'])
                if not ok:
                    error = True

                # we want to include the console url in the outputs
                # to be used later to generate the email invitations
                output_name_0_13 = '{}_console-urls__{}'.format(
                    self.integration_prefix, account_name
                )
                output_value = account_console_url
                tf_output = Output(output_name_0_13, value=output_value)
                self.add_resource(account_name, tf_output)

                for user in users:
                    user_name = self._get_aws_username(user)

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
                            depends_on=self.get_dependencies(
                                [tf_iam_user, tf_iam_group])
                        )
                    self.add_resource(account_name,
                                      tf_iam_user_group_membership)

                    # if user does not have a gpg key,
                    # a password will not be created.
                    # a gpg key may be added at a later time,
                    # and a password will be generated
                    user_public_gpg_key = user['public_gpg_key']
                    if user_public_gpg_key is None:
                        msg = \
                            f'{user_name} does not have a public gpg key.'
                        logging.error(msg)
                        error = True
                        continue
                    try:
                        gpg_key_valid(user_public_gpg_key)
                    except ValueError as e:
                        msg = \
                            f'invalid public gpg key for {user_name}. ' + \
                            f'details: {str(e)}'
                        logging.error(msg)
                        error = True
                        continue
                    # Ref: terraform aws iam_user_login_profile
                    tf_iam_user_login_profile = aws_iam_user_login_profile(
                        user_name,
                        user=user_name,
                        pgp_key=user_public_gpg_key,
                        depends_on=self.get_dependencies([tf_iam_user]),
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
                    output_name_0_13 = '{}_enc-passwords__{}'.format(
                        self.integration_prefix, user_name)
                    output_value = '${' + \
                        tf_iam_user_login_profile.encrypted_password + '}'
                    tf_output = Output(output_name_0_13, value=output_value)
                    self.add_resource(account_name, tf_output)

            for user_policy in user_policies:
                policy_name = user_policy['name']
                account_name = user_policy['account']['name']
                account_uid = user_policy['account']['uid']
                for user in users:
                    # replace known keys with values
                    user_name = self._get_aws_username(user)
                    policy = user_policy['policy']
                    policy = policy.replace('${aws:username}', user_name)
                    policy = \
                        policy.replace('${aws:accountid}', account_uid)

                    # Ref: terraform aws_iam_policy
                    tf_iam_user = self.get_tf_iam_user(user_name)
                    identifier = f'{user_name}-{policy_name}'
                    tf_aws_iam_policy = aws_iam_policy(
                        identifier,
                        name=identifier,
                        policy=policy,
                    )
                    self.add_resource(account_name,
                                      tf_aws_iam_policy)
                    # Ref: terraform aws_iam_user_policy_attachment
                    tf_iam_user_policy_attachment = \
                        aws_iam_user_policy_attachment(
                            identifier,
                            user=user_name,
                            policy_arn=f"${{{tf_aws_iam_policy.arn}}}",
                            depends_on=self.get_dependencies(
                                [tf_iam_user, tf_aws_iam_policy])
                        )
                    self.add_resource(account_name,
                                      tf_iam_user_policy_attachment)

        return error

    def populate_users(self, roles):
        self.populate_iam_groups(roles)
        err = self.populate_iam_users(roles)
        return err

    @staticmethod
    def get_alias_name_from_assume_role(assume_role):
        uid = awsh.get_account_uid_from_arn(assume_role)
        return f"account-{uid}"

    def populate_additional_providers(self, accounts):
        for account in accounts:
            account_name = account['name']
            assume_role = account['assume_role']
            alias = self.get_alias_name_from_assume_role(assume_role)
            ts = self.tss[account_name]
            config = self.configs[account_name]
            existing_provider_aliases = \
                [p.get('alias') for p in ts['provider']['aws']]
            if alias not in existing_provider_aliases:
                ts += provider.aws(
                    access_key=config['aws_access_key_id'],
                    secret_key=config['aws_secret_access_key'],
                    version=self.versions.get(account_name),
                    region=account['assume_region'],
                    alias=alias,
                    assume_role={'role_arn': assume_role})

    def populate_route53(self, desired_state, default_ttl=300):
        for zone in desired_state:
            acct_name = zone['account_name']

            # Ensure zone is in the state for the given account
            zone_id = safe_resource_id(f"{zone['name']}")
            zone_values = {
                'name': zone['name'],
                'vpc': zone.get('vpc'),
                'comment': 'Managed by Terraform'
            }
            zone_resource = aws_route53_zone(zone_id, **zone_values)
            self.add_resource(acct_name, zone_resource)

            counts = {}
            for record in zone['records']:
                record_fqdn = f"{record['name']}.{zone['name']}"
                record_id = safe_resource_id(
                    f"{record_fqdn}_{record['type'].upper()}")

                # Count record names so we can generate unique IDs
                if record_id not in counts:
                    counts[record_id] = 0
                counts[record_id] += 1

                # If more than one record with a given name, append _{count}
                if counts[record_id] > 1:
                    record_id = f"{record_id}_{counts[record_id]}"

                # Use default TTL if none is specified
                # or if this record is an alias
                # None/zero is accepted but not a good default
                if not record.get('alias') and record.get('ttl') is None:
                    record['ttl'] = default_ttl

                # Define healthcheck if needed
                healthcheck = record.pop('healthcheck', None)
                if healthcheck:
                    healthcheck_id = record_id
                    healthcheck_values = {**healthcheck}
                    healthcheck_resource = aws_route53_health_check(
                        healthcheck_id, **healthcheck_values)
                    self.add_resource(acct_name, healthcheck_resource)
                    # Assign the healthcheck resource ID to the record
                    record['health_check_id'] = \
                        f"${{{healthcheck_resource.id}}}"

                record_values = {
                    'zone_id': f"${{{zone_resource.id}}}",
                    **record
                }
                record_resource = aws_route53_record(record_id,
                                                     **record_values)
                self.add_resource(acct_name, record_resource)

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
            req_alias = self.get_alias_name_from_assume_role(
                req_account['assume_role'])

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
            acc_alias = self.get_alias_name_from_assume_role(
                acc_account['assume_role'])

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
            if connection_provider in ['account-vpc', 'account-vpc-mesh']:
                if self._multiregion_account(acc_account_name):
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
                    if connection_provider in \
                            ['account-vpc', 'account-vpc-mesh']:
                        if self._multiregion_account(acc_account_name):
                            values['provider'] = 'aws.' + accepter['region']
                    else:
                        values['provider'] = 'aws.' + acc_alias
                    route_identifier = f'{identifier}-{route_table_id}'
                    tf_resource = aws_route(route_identifier, **values)
                    self.add_resource(acc_account_name, tf_resource)

    def populate_tgw_attachments(self, desired_state):
        for item in desired_state:
            if item['deleted']:
                continue

            connection_name = item['connection_name']
            requester = item['requester']
            accepter = item['accepter']

            # Requester's side of the connection - the AWS account
            req_account = requester['account']
            req_account_name = req_account['name']
            # Accepter's side of the connection - the cluster's account
            acc_account = accepter['account']
            acc_account_name = acc_account['name']
            acc_alias = self.get_alias_name_from_assume_role(
                acc_account['assume_role'])
            acc_uid = awsh.get_account_uid_from_arn(
                acc_account['assume_role'])

            tags = {
                'managed_by_integration': self.integration,
                'Name': connection_name
            }
            # add resource share
            values = {
                'name': connection_name,
                'allow_external_principals': True,
                'tags': tags
            }
            if self._multiregion_account(req_account_name):
                values['provider'] = 'aws.' + requester['region']
            tf_resource_share = \
                aws_ram_resource_share(connection_name, **values)
            self.add_resource(req_account_name, tf_resource_share)

            # share with accepter aws account
            values = {
                'principal': acc_uid,
                'resource_share_arn': '${' + tf_resource_share.arn + '}'
            }
            if self._multiregion_account(req_account_name):
                values['provider'] = 'aws.' + requester['region']
            tf_resource_association = \
                aws_ram_principal_association(connection_name, **values)
            self.add_resource(req_account_name, tf_resource_association)

            # accept resource share from accepter aws account
            values = {
                'provider': 'aws.' + acc_alias,
                'share_arn': '${' + tf_resource_share.arn + '}',
                'depends_on': [
                    'aws_ram_resource_share.' + connection_name,
                    'aws_ram_principal_association.' + connection_name
                ]
            }
            tf_resource_share_accepter = \
                aws_ram_resource_share_accepter(connection_name, **values)
            self.add_resource(acc_account_name, tf_resource_share_accepter)

            # until now it was standard sharing
            # from this line onwards we will be adding content
            # specific for the TGW attachments integration

            # tgw share association
            identifier = f"{requester['tgw_id']}-{accepter['vpc_id']}"
            values = {
                'resource_arn': requester['tgw_arn'],
                'resource_share_arn': '${' + tf_resource_share.arn + '}'
            }
            if self._multiregion_account(req_account_name):
                values['provider'] = 'aws.' + requester['region']
            tf_resource_association = \
                aws_ram_resource_association(identifier, **values)
            self.add_resource(req_account_name, tf_resource_association)

            # now that the tgw is shared to the cluster's aws account
            # we can create a vpc attachment to the tgw
            subnets_id_az = accepter['subnets_id_az']
            subnets = self.get_az_unique_subnet_ids(subnets_id_az)
            values = {
                'provider': 'aws.' + acc_alias,
                'subnet_ids': subnets,
                'transit_gateway_id': requester['tgw_id'],
                'vpc_id': accepter['vpc_id'],
                'depends_on': [
                    'aws_ram_principal_association.' + connection_name,
                    'aws_ram_resource_association.' + identifier
                ],
                'tags': tags
            }
            tf_resource_attachment = \
                aws_ec2_transit_gateway_vpc_attachment(identifier, **values)
            # we send the attachment from the cluster's aws account
            self.add_resource(acc_account_name, tf_resource_attachment)

            # and accept the attachment in the non cluster's aws account
            values = {
                'transit_gateway_attachment_id':
                    '${' + tf_resource_attachment.id + '}',
                'tags': tags
            }
            if self._multiregion_account(req_account_name):
                values['provider'] = 'aws.' + requester['region']
            tf_resource_attachment_accepter = \
                aws_ec2_transit_gateway_vpc_attachment_accepter(
                    identifier, **values)
            self.add_resource(
                req_account_name, tf_resource_attachment_accepter)

            # add routes to existing route tables
            route_table_ids = accepter.get('route_table_ids')
            req_cidr_block = requester.get('cidr_block')
            if route_table_ids and req_cidr_block:
                for route_table_id in route_table_ids:
                    values = {
                        'provider': 'aws.' + acc_alias,
                        'route_table_id': route_table_id,
                        'destination_cidr_block': req_cidr_block,
                        'transit_gateway_id': requester['tgw_id']
                    }
                    route_identifier = f'{identifier}-{route_table_id}'
                    tf_resource = aws_route(route_identifier, **values)
                    self.add_resource(acc_account_name, tf_resource)

            # add routes to peered transit gateways in the requester's
            # account to achieve global routing from all regions
            requester_routes = requester.get('routes')
            if requester_routes:
                for route in requester_routes:
                    route_region = route['region']
                    if route_region not in \
                            self.supported_regions[req_account_name]:
                        logging.warning(
                            f'[{req_account_name}] TGW in ' +
                            f'unsupported region: {route_region}')
                        continue
                    values = {
                        'destination_cidr_block': route['cidr_block'],
                        'transit_gateway_attachment_id':
                            route['tgw_attachment_id'],
                        'transit_gateway_route_table_id':
                            route['tgw_route_table_id'],
                    }
                    if self._multiregion_account(req_account_name):
                        values['provider'] = 'aws.' + route_region
                    route_identifier = f"{identifier}-{route['tgw_id']}"
                    tf_resource = aws_ec2_transit_gateway_route(
                        route_identifier, **values)
                    self.add_resource(req_account_name, tf_resource)

            # add rules to security groups of VPCs which are attached
            # to the transit gateway to allow traffic through the routes
            requester_rules = requester.get('rules')
            if requester_rules:
                for rule in requester_rules:
                    rule_region = rule['region']
                    if rule_region not in \
                            self.supported_regions[req_account_name]:
                        logging.warning(
                            f'[{req_account_name}] TGW in ' +
                            f'unsupported region: {rule_region}')
                        continue
                    values = {
                        'type': 'ingress',
                        'from_port': 0,
                        'to_port': 0,
                        'protocol': 'all',
                        'cidr_blocks': [rule['cidr_block']],
                        'security_group_id': rule['security_group_id']
                    }
                    if self._multiregion_account(req_account_name):
                        values['provider'] = 'aws.' + rule_region
                    rule_identifier = f"{identifier}-{rule['vpc_id']}"
                    tf_resource = aws_security_group_rule(
                        rule_identifier, **values)
                    self.add_resource(req_account_name, tf_resource)

    @staticmethod
    def get_az_unique_subnet_ids(subnets_id_az):
        """ returns a list of subnet ids which are unique per az """
        results = []
        azs = []
        for subnet_id_az in subnets_id_az:
            az = subnet_id_az['az']
            if az in azs:
                continue
            results.append(subnet_id_az['id'])
            azs.append(az)

        return results

    def populate_resources(self, namespaces: Iterable[Mapping[str, Any]],
                           existing_secrets: Mapping[str, Any],
                           account_name: Optional[str],
                           ocm_map: Optional[OCMMap] = None) -> None:
        """
        Populates the terraform configuration from the definitions in app-interface
        (schemas/openshift/terraform-resource-1.yml).
        :param namespaces: schemas/openshift/namespace-1.yml object
        :param existing_secrets:
        :param account_name: AWS account name
        :param ocm_map:
        """
        self.init_populate_specs(namespaces, account_name)
        for specs in self.account_resources.values():
            for spec in specs:
                self.populate_tf_resources(spec, existing_secrets,
                                           ocm_map=ocm_map)

    def init_populate_specs(self, namespaces: Iterable[Mapping[str, Any]],
                            account_name: Optional[str]) -> None:
        self.account_resources: dict[str, list[dict[str, Any]]] = {}
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

    def populate_tf_resources(self, populate_spec, existing_secrets,
                              ocm_map=None):
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
                                                      namespace_info,
                                                      ocm_map=ocm_map)
        elif provider == 'secrets-manager-service-account':
            self.populate_tf_resource_secrets_manager_sa(resource,
                                                         namespace_info)
        elif provider == 'aws-iam-role':
            self.populate_tf_resource_role(resource, namespace_info)
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
            self.populate_tf_resource_elasticsearch(resource, namespace_info)
        elif provider == 'acm':
            self.populate_tf_resource_acm(resource, namespace_info)
        elif provider == 'kinesis':
            self.populate_tf_resource_kinesis(resource, namespace_info)
        elif provider == 's3-cloudfront-public-key':
            self.populate_tf_resource_s3_cloudfront_public_key(resource,
                                                               namespace_info)
        elif provider == 'alb':
            self.populate_tf_resource_alb(resource, namespace_info,
                                          ocm_map=ocm_map)
        elif provider == 'secrets-manager':
            self.populate_tf_resource_secrets_manager(resource, namespace_info)
        elif provider == 'asg':
            self.populate_tf_resource_asg(resource, namespace_info,
                                          existing_secrets)
        elif provider == 'route53-zone':
            self.populate_tf_resource_route53_zone(resource, namespace_info)
        else:
            raise UnknownProviderError(provider)

    def populate_tf_resource_rds(self, resource, namespace_info,
                                 existing_secrets):
        account, identifier, values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        # we want to allow an empty name, so we
        # only validate names which are not empty
        if values.get('name') and not self.validate_db_name(values['name']):
            raise FetchResourceError(
                f"[{account}] RDS name must contain 1 to 63 letters, " +
                "numbers, or underscores. RDS name must begin with a " +
                "letter. Subsequent characters can be letters, " +
                f"underscores, or digits (0-9): {values['name']}")

        # we can't specify the availability_zone for an multi_az
        # rds instance
        if values.get('multi_az'):
            az = values.pop('availability_zone', None)
        else:
            az = values.get('availability_zone', None)
        provider = ''
        region = values.pop('region', None)
        if self._multiregion_account(account):
            # To get the provider we should use, we get the region
            # and use that as an alias in the provider definition
            if az:
                provider = 'aws.' + self._region_from_availability_zone(az)
                values['provider'] = provider
            if region:
                provider_region = f'aws.{region}'
                if not provider:
                    provider = provider_region
                    values['provider'] = provider
                elif provider != provider_region:
                    raise ValueError('region does not match availability zone')

        # 'deps' should contain a list of terraform resource names
        # (not full objects) that must be created
        # before the actual RDS instance should be created
        deps = []
        parameter_group = values.pop('parameter_group', None)
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
            if self._multiregion_account(account) and len(provider) > 0:
                pg_values['provider'] = provider
            pg_tf_resource = \
                aws_db_parameter_group(pg_identifier, **pg_values)
            tf_resources.append(pg_tf_resource)
            deps = self.get_dependencies([pg_tf_resource])
            values['parameter_group_name'] = pg_name

        enhanced_monitoring = values.pop('enhanced_monitoring', None)

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

            role_res_name = self.get_dependencies([role_tf_resource])[0]
            deps.append(role_res_name)

            em_values = {
                'role': role_tf_resource.name,
                'policy_arn':
                    "arn:aws:iam::aws:policy/service-role/" +
                    "AmazonRDSEnhancedMonitoringRole",
                'depends_on': self.get_dependencies([role_tf_resource])
            }
            attachment_tf_resource = \
                aws_iam_role_policy_attachment(em_identifier, **em_values)
            tf_resources.append(attachment_tf_resource)

            attachment_res_name = \
                self.get_dependencies([attachment_tf_resource])[0]
            deps.append(attachment_res_name)

            values['monitoring_role_arn'] = \
                f'${{{role_tf_resource.arn}}}'

        reset_password_current_value = values.pop('reset_password', None)
        if self._db_needs_auth(values):
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
                    password = existing_secret['db.password']
                except KeyError:
                    password = self.generate_random_password()
        else:
            password = ""
        values['password'] = password

        ca_cert = values.pop('ca_cert', None)
        if ca_cert:
            # db.ca_cert
            output_name_0_13 = output_prefix + '__db_ca_cert'
            output_value = self.secret_reader.read(ca_cert)
            tf_resources.append(Output(output_name_0_13, value=output_value))

        region = self._region_from_availability_zone(
            az) or self.default_regions.get(account)
        replica_source = values.pop('replica_source', None)
        if replica_source:
            if 'replicate_source_db' in values:
                raise ValueError(
                    "only one of replicate_source_db or replica_source " +
                    "can be defined")
            source_info = self._find_resource(account, replica_source, 'rds')
            if source_info:
                values['backup_retention_period'] = 0
                deps.append("aws_db_instance." +
                            source_info['resource']['identifier'])
                replica_az = source_info.get('availability_zone', None)
                if replica_az and len(replica_az) > 1:
                    replica_region = self._region_from_availability_zone(
                        replica_az)
                else:
                    replica_region = self.default_regions.get(account)
                _, _, source_values, _, _, _ = self.init_values(
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
                            "db_subnet_group_name must be defined if " +
                            "read replica source in different region")

                    # storage_encrypted is ignored for cross-region replicas
                    encrypt = values.get('storage_encrypted', None)
                    if encrypt and 'kms_key_id' not in values:
                        raise ValueError(
                            "storage_encrypted ignored for cross-region " +
                            "read replica.  Set kms_key_id")

                # Read Replicas shouldn't set these values as they come from
                # the source db
                remove_params = ['engine', 'password', 'username']
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

        # There seems to be a bug in tf-provider-aws when making replicas
        # w/ ehanced-monitoring, causing tf to not wait long enough
        # between the actions of creating an enhanced-monitoring IAM role
        # and checking the permissions of that role on a RDS replica
        # if the source-db already exists.
        # Therefore we wait 30s between these actions.
        # This sleep can be removed if all AWS accounts upgrade
        # to a provider version with this bug fix.
        # https://github.com/hashicorp/terraform-provider-aws/pull/20926
        if enhanced_monitoring and replica_source:
            sleep_vals = {}
            sleep_vals['depends_on'] = [attachment_res_name]
            sleep_vals['create_duration'] = "30s"

            # time_sleep
            # Terraform resource reference:
            # https://registry.terraform.io
            # /providers/hashicorp/time/latest/docs/resources/sleep
            time_sleep_resource = time_sleep(identifier, **sleep_vals)

            tf_resources.append(time_sleep_resource)
            time_sleep_res_name = \
                self.get_dependencies([time_sleep_resource])[0]
            deps.append(time_sleep_res_name)

        kms_key_id = values.pop('kms_key_id', None)
        if kms_key_id is not None:
            if kms_key_id.startswith("arn:"):
                values['kms_key_id'] = kms_key_id
            else:
                kms_key = self._find_resource(account, kms_key_id, 'kms')
                if kms_key:
                    kms_res = "aws_kms_key." + \
                        kms_key['resource']['identifier']
                    values['kms_key_id'] = "${" + kms_res + ".arn}"
                    deps.append(kms_res)
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
        output_name_0_13 = output_prefix + '__db_host'
        output_value = '${' + tf_resource.address + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # db.port
        output_name_0_13 = output_prefix + '__db_port'
        output_value = '${' + str(tf_resource.port) + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # db.name
        output_name_0_13 = output_prefix + '__db_name'
        output_value = output_resource_db_name or values.get('name', '')
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # only set db user/password if not a replica or creation from snapshot
        if self._db_needs_auth(values):
            # db.user
            output_name_0_13 = output_prefix + '__db_user'
            output_value = values['username']
            tf_resources.append(Output(output_name_0_13, value=output_value))
            # db.password
            output_name_0_13 = output_prefix + '__db_password'
            output_value = values['password']
            tf_resources.append(Output(output_name_0_13, value=output_value))
            # only add reset_password key to the terraform state
            # if reset_password_current_value is defined.
            # this means that if the reset_password field is removed
            # from the rds definition in app-interface, the key will be
            # removed from the state and from the output resource,
            # leading to a recycle of the pods using this resource.
            if reset_password_current_value:
                output_name_0_13 = output_prefix + '__reset_password'
                output_value = reset_password_current_value
                tf_resources.append(
                    Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

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

    def _multiregion_account(self, name):
        if name not in self.configs:
            return False

        if self.configs[name]['supportedDeploymentRegions'] is not None:
            return True

        return False

    def _find_resource(self,
                       account: str,
                       source: str,
                       provider: str
                       ) -> Optional[Dict[str, Dict[str, Optional[str]]]]:
        if account not in self.account_resources:
            return None

        for res in self.account_resources[account]:
            r = res['resource']
            if r['identifier'] == source and r['provider'] == provider:
                return res
        return None

    @staticmethod
    def _region_from_availability_zone(az):
        # Find the region by removing the last character from the
        # availability zone. Availability zone is defined like
        # us-east-1a, us-east-1b, etc.  If there is no availability
        # zone, return emmpty string
        if az and len(az) > 1:
            return az[:-1]
        return None

    @staticmethod
    def _db_needs_auth(config):
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

    @staticmethod
    def generate_random_password(string_length=20):
        """Generate a random string of letters and digits """
        letters_and_digits = string.ascii_letters + string.digits
        return ''.join(random.choice(letters_and_digits)
                       for i in range(string_length))

    def populate_tf_resource_s3(self, resource, namespace_info):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        # s3 bucket
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/s3_bucket.html
        values = {}
        values['bucket'] = identifier
        versioning = common_values.get('versioning') or True
        values['versioning'] = {"enabled": versioning}
        values['tags'] = common_values['tags']
        values['acl'] = common_values.get('acl') or 'private'
        server_side_encryption_configuration = \
            common_values.get('server_side_encryption_configuration')
        if server_side_encryption_configuration:
            values['server_side_encryption_configuration'] = \
                server_side_encryption_configuration
        lifecycle_rules = common_values.get('lifecycle_rules')
        if lifecycle_rules:
            # common_values['lifecycle_rules'] is a list of lifecycle_rules
            values['lifecycle_rule'] = lifecycle_rules
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
        cors_rules = common_values.get('cors_rules')
        if cors_rules:
            # common_values['cors_rules'] is a list of cors_rules
            values['cors_rule'] = cors_rules
        deps = []
        replication_configs = common_values.get('replication_configurations')
        if replication_configs:
            rc_configs = []
            for config in replication_configs:
                rc_values = {}
                dest_bucket_id = config['destination_bucket_identifier']

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
                                "${aws_s3_bucket." + identifier + ".arn}",
                                "${aws_s3_bucket." + dest_bucket_id + ".arn}"
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
                rc_values['depends_on'] = self.get_dependencies(
                    [role_resource, policy_resource])
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
            values['depends_on'] = self.get_dependencies(deps)
        region = common_values.get('region') or \
            self.default_regions.get(account)
        if self._multiregion_account(account):
            values['provider'] = 'aws.' + region
        bucket_tf_resource = aws_s3_bucket(identifier, **values)
        tf_resources.append(bucket_tf_resource)
        output_name_0_13 = output_prefix + '__bucket'
        output_value = bucket_tf_resource.bucket
        tf_resources.append(Output(output_name_0_13, value=output_value))
        output_name_0_13 = output_prefix + '__aws_region'
        tf_resources.append(Output(output_name_0_13, value=region))
        endpoint = 's3.{}.amazonaws.com'.format(region)
        output_name_0_13 = output_prefix + '__endpoint'
        tf_resources.append(Output(output_name_0_13, value=endpoint))

        sqs_identifier = common_values.get('sqs_identifier', None)
        if sqs_identifier is not None:
            sqs_values = {
                'name': sqs_identifier
            }
            sqs_provider = values.get('provider')
            if sqs_provider:
                sqs_values['provider'] = sqs_provider
            sqs_data = data.aws_sqs_queue(sqs_identifier, **sqs_values)
            tf_resources.append(sqs_data)

            s3_events = common_values.get('s3_events', ["s3:ObjectCreated:*"])
            notification_values = {
                'bucket': '${' + bucket_tf_resource.id + '}',
                'queue': [{
                    'id': sqs_identifier,
                    'queue_arn':
                        '${data.aws_sqs_queue.' + sqs_identifier + '.arn}',
                    'events': s3_events
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

        event_notifications = common_values.get('event_notifications')
        sns_notifications = []
        sqs_notifications = []

        if event_notifications:
            for event_notification in event_notifications:
                destination_type = event_notification['destination_type']
                destination_identifier = event_notification['destination']
                event_type = event_notification['event_type']

                if destination_type == 'sns':
                    notification_type = 'topic'
                    resource_arn_data = 'data.aws_sns_topic'
                elif destination_type == 'sqs':
                    notification_type = 'queue'
                    resource_arn_data = 'data.aws_sqs_queue'

                if destination_identifier.startswith('arn:'):
                    resource_name = destination_identifier.split(':')[-1]
                    resource_arn = destination_identifier
                else:
                    resource_name = destination_identifier
                    resource_values = {
                        'name': resource_name
                    }
                    resource_provider = values.get('provider')
                    if resource_provider:
                        resource_values['provider'] = resource_provider
                    if destination_type == 'sns':
                        resource_data = data.aws_sns_topic(resource_name,
                                                           **resource_values)
                    elif destination_type == 'sqs':
                        resource_data = data.aws_sqs_queue(resource_name,
                                                           **resource_values)
                    tf_resources.append(resource_data)
                    resource_arn = '${'+resource_arn_data+'.' \
                        + destination_identifier + '.arn}'

                notification_config = {
                    'id': resource_name,
                    notification_type+'_arn': resource_arn,
                    'events': event_type
                }

                filter_prefix = event_notification.get('filter_prefix', None)
                if filter_prefix is not None:
                    notification_config['filter_prefix'] = filter_prefix
                filter_suffix = event_notification.get('filter_suffix', None)
                if filter_suffix is not None:
                    notification_config['filter_suffix'] = filter_suffix

                if destination_type == 'sns':
                    sns_notifications.append(notification_config)
                elif destination_type == 'sqs':
                    sqs_notifications.append(notification_config)

            notifications = {
                'bucket': '${' + bucket_tf_resource.id + '}'
            }
            if sns_notifications:
                notifications['topic'] = sns_notifications
            if sqs_notifications:
                notifications['queue'] = sqs_notifications

            notification_tf_resource = aws_s3_bucket_notification(
                    identifier+'-event-notifications', **notifications)
            tf_resources.append(notification_tf_resource)

        bucket_policy = common_values.get('bucket_policy')
        if bucket_policy:
            values = {
                'bucket': identifier,
                'policy': bucket_policy,
                'depends_on': self.get_dependencies([bucket_tf_resource])
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
        values['depends_on'] = self.get_dependencies([bucket_tf_resource])
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
        if common_values.get('acl', 'private') == 'public-read':
            action.append("s3:PutObjectAcl")
        allow_object_tagging = common_values.get('allow_object_tagging', False)
        if allow_object_tagging:
            action.append("s3:*ObjectTagging")

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "ListObjectsInBucket",
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket", "s3:PutBucketCORS"],
                    "Resource": ["${" + bucket_tf_resource.arn + "}"]
                },
                {
                    "Sid": "AllObjectActions",
                    "Effect": "Allow",
                    "Action": action,
                    "Resource": ["${" + bucket_tf_resource.arn + "}/*"]
                }
            ]
        }
        values['policy'] = json.dumps(policy, sort_keys=True)
        values['depends_on'] = self.get_dependencies([user_tf_resource])
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        self.add_resources(account, tf_resources)

        return bucket_tf_resource

    def populate_tf_resource_elasticache(self, resource, namespace_info,
                                         existing_secrets):
        account, identifier, values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)
        values.setdefault('replication_group_id', values['identifier'])
        values.pop('identifier', None)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        default_region = self.default_regions.get(account)
        desired_region = values.pop('region', default_region)

        provider = ''
        if desired_region is not None and self._multiregion_account(account):
            provider = 'aws.' + desired_region
            values['provider'] = provider

        parameter_group = values.get('parameter_group')
        # Assume that cluster enabled is false if parameter group unset
        pg_cluster_enabled = False

        if parameter_group:
            pg_values = self.get_values(parameter_group)
            pg_name = pg_values['name']
            pg_identifier = pg_name

            # If the desired region is not the same as the default region
            # we append the region to the identifier to make it unique
            # in the terraform config
            if desired_region is not None and desired_region != default_region:
                pg_identifier = f"{pg_name}-{desired_region}"

            pg_values['parameter'] = pg_values.pop('parameters')
            for param in pg_values['parameter']:
                if param['name'] == 'cluster-enabled' \
                        and param['value'] == 'yes':
                    pg_cluster_enabled = True

            if self._multiregion_account(account) and len(provider) > 0:
                pg_values['provider'] = provider
            pg_tf_resource = \
                aws_elasticache_parameter_group(pg_identifier, **pg_values)
            tf_resources.append(pg_tf_resource)
            values['depends_on'] = [
                f'aws_elasticache_parameter_group.{pg_identifier}',
            ]
            values['parameter_group_name'] = pg_name
            values.pop('parameter_group', None)

        try:
            auth_token = \
                existing_secrets[account][output_prefix]['db.auth_token']
        except KeyError:
            auth_token = self.generate_random_password()

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
        output_name_0_13 = output_prefix + '__db_endpoint'
        # https://docs.aws.amazon.com/AmazonElastiCache/
        # latest/red-ug/Endpoints.html
        if pg_cluster_enabled:
            output_value = \
                '${' + tf_resource.configuration_endpoint_address + '}'
        else:
            output_value = \
                '${' + tf_resource.primary_endpoint_address + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # db.port
        output_name_0_13 = output_prefix + '__db_port'
        output_value = '${' + str(tf_resource.port) + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # db.auth_token
        if values.get('transit_encryption_enabled', False):
            output_name_0_13 = output_prefix + '__db_auth_token'
            output_value = values['auth_token']
            tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def populate_tf_resource_service_account(self, resource, namespace_info,
                                             ocm_map=None):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

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
        for policy in common_values.get('policies') or []:
            tf_iam_user_policy_attachment = \
                aws_iam_user_policy_attachment(
                    identifier + '-' + policy,
                    user=identifier,
                    policy_arn='arn:aws:iam::aws:policy/' + policy,
                    depends_on=self.get_dependencies([user_tf_resource])
                )
            tf_resources.append(tf_iam_user_policy_attachment)

        user_policy = common_values.get('user_policy')
        if user_policy:
            variables = common_values.get('variables')
            # variables are replaced in the user_policy
            # and also added to the output resource
            if variables:
                data = json.loads(variables)
                for k, v in data.items():
                    to_replace = '${' + k + '}'
                    user_policy = user_policy.replace(to_replace, v)
                    output_name_0_13 = output_prefix + '__{}'.format(k)
                    tf_resources.append(Output(output_name_0_13, value=v))
            tf_aws_iam_user_policy = aws_iam_user_policy(
                identifier,
                name=identifier,
                user=identifier,
                policy=user_policy,
                depends_on=self.get_dependencies([user_tf_resource])
            )
            tf_resources.append(tf_aws_iam_user_policy)

        aws_infrastructure_access = \
            common_values.get('aws_infrastructure_access') or None
        if aws_infrastructure_access:
            # to provision a resource in a cluster's account, we need to
            # be able to assume role into it.
            # if assume_role is supplied - use it.
            # if it is not supplied - try to get the role to assume through
            # OCM AWS infrastructure access.
            assume_role = aws_infrastructure_access.get('assume_role')
            if assume_role:
                output_name_0_13 = output_prefix + '__role_arn'
                tf_resources.append(
                    Output(output_name_0_13, value=assume_role))
            elif ocm_map:
                cluster = aws_infrastructure_access['cluster']['name']
                ocm = ocm_map.get(cluster)
                role_grants = \
                    ocm.get_aws_infrastructure_access_role_grants(cluster)
                for user_arn, _, state, switch_role_link in role_grants:
                    # find correct user by identifier
                    user_id = awsh.get_user_id_from_arn(user_arn)
                    # output will only be added once
                    # terraform-resources created the user
                    # and ocm-aws-infrastructure-access granted it the role
                    if identifier == user_id and state != 'failed':
                        switch_role_arn = \
                            awsh.get_role_arn_from_role_link(switch_role_link)
                        output_name_0_13 = output_prefix + '__role_arn'
                        tf_resources.append(
                            Output(output_name_0_13, value=switch_role_arn))
            else:
                raise KeyError(
                    f'[{account}/{identifier}] '
                    'expected one of ocm_map or assume_role'
                )

        self.add_resources(account, tf_resources)

    def populate_tf_resource_secrets_manager_sa(self, resource,
                                                namespace_info):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        secrets_prefix = common_values['secrets_prefix']
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "secretsmanager:ListSecrets"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": "secretsmanager:*",
                    "Resource": [
                        f"arn:aws:secretsmanager:*:*:secret:{secrets_prefix}/*"
                    ]
                }
            ]
        }

        tf_resources.extend(
            self.get_tf_iam_service_user(
                [],
                identifier,
                policy,
                common_values['tags'],
                output_prefix
            )
        )

        output_name_0_13 = output_prefix + '__secrets_prefix'
        output_value = secrets_prefix
        tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def populate_tf_resource_role(self, resource, namespace_info):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        assume_role = common_values['assume_role']
        assume_role = {k: v for k, v in assume_role.items() if v is not None}
        # assume role policy
        assume_role_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "sts:AssumeRole",
                    "Effect": "Allow",
                    "Principal": assume_role
                }
            ]
        }
        assume_condition = \
            json.loads(common_values.get('assume_condition') or '{}')
        if assume_condition:
            assume_role_policy['Statement'][0]['Condition'] = assume_condition

        # iam role
        values = {
            'name': identifier,
            'tags': common_values['tags'],
            'assume_role_policy': json.dumps(assume_role_policy)
        }

        inline_policy = common_values.get('inline_policy')
        if inline_policy:
            values['inline_policy'] = {
                'name': identifier,
                'policy': inline_policy
            }

        role_tf_resource = aws_iam_role(identifier, **values)
        tf_resources.append(role_tf_resource)

        # output role arn
        output_name_0_13 = output_prefix + '__role_arn'
        output_value = '${' + role_tf_resource.arn + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def populate_tf_resource_sqs(self, resource, namespace_info):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)
        uid = self.uids.get(account)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)
        region = common_values.get('region') or \
            self.default_regions.get(account)
        specs = common_values.get('specs')
        all_queues_per_spec = []
        kms_keys = set()
        for spec in specs:
            defaults = self.get_values(spec['defaults'])
            queues = spec.pop('queues', [])
            all_queues = []
            for queue_kv in queues:
                queue_key = queue_kv['key']
                queue = queue_kv['value']
                # sqs queue
                # Terraform resource reference:
                # https://www.terraform.io/docs/providers/aws/r/sqs_queue.html
                values = {}
                queue_name = queue
                values['tags'] = common_values['tags']
                if self._multiregion_account(account):
                    values['provider'] = 'aws.' + region
                values.update(defaults)
                fifo_queue = values.get('fifo_queue', False)
                if fifo_queue:
                    queue_name += '.fifo'
                values['name'] = queue_name
                all_queues.append(queue_name)
                sqs_policy = values.pop('sqs_policy', None)
                if sqs_policy is not None:
                    values['policy'] = json.dumps(sqs_policy, sort_keys=True)
                dl_queue = values.pop('dl_queue', None)
                if dl_queue is not None:
                    max_receive_count = \
                        int(values.pop('max_receive_count', 10))
                    dl_values = {}
                    dl_values['name'] = dl_queue
                    if fifo_queue:
                        dl_values['name'] += '.fifo'
                    dl_data = data.aws_sqs_queue(dl_queue, **dl_values)
                    tf_resources.append(dl_data)
                    redrive_policy = {
                        'deadLetterTargetArn': '${' + dl_data.arn + '}',
                        'maxReceiveCount': max_receive_count
                    }
                    values['redrive_policy'] = \
                        json.dumps(redrive_policy, sort_keys=True)
                kms_master_key_id = values.pop('kms_master_key_id', None)
                if kms_master_key_id is not None:
                    if kms_master_key_id.startswith("arn:"):
                        values['kms_master_key_id'] = kms_master_key_id
                    else:
                        kms_key = self._find_resource(
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
                output_name_0_13 = output_prefix + '__aws_region'
                tf_resources.append(Output(output_name_0_13, value=region))
                output_name_0_13 = '{}__{}'.format(output_prefix, queue_key)
                output_value = \
                    'https://sqs.{}.amazonaws.com/{}/{}'.format(
                        region, uid, queue_name)
                tf_resources.append(
                    Output(output_name_0_13, value=output_value))
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
                            f"arn:{self._get_partition(account)}:" +
                            f"sqs:*:{uid}:{q}"
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
            if kms_keys:
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
                '${' + policy_tf_resource.arn + '}'
            values['depends_on'] = self.get_dependencies(
                [user_tf_resource, policy_tf_resource])
            tf_resource = \
                aws_iam_user_policy_attachment(policy_identifier, **values)
            tf_resources.append(tf_resource)

        self.add_resources(account, tf_resources)

    def populate_tf_resource_dynamodb(self, resource, namespace_info):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)
        uid = self.uids.get(account)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)
        region = common_values.get('region') or \
            self.default_regions.get(account)
        specs = common_values.get('specs')
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
                if self._multiregion_account(account):
                    values['provider'] = 'aws.' + region
                table_tf_resource = aws_dynamodb_table(table, **values)
                tf_resources.append(table_tf_resource)
                output_name_0_13 = '{}__{}'.format(output_prefix, table_key)
                tf_resources.append(Output(output_name_0_13, value=table))

        output_name_0_13 = output_prefix + '__aws_region'
        tf_resources.append(Output(output_name_0_13, value=region))
        output_name_0_13 = output_prefix + '__endpoint'
        output_value = f"https://dynamodb.{region}.amazonaws.com"
        tf_resources.append(Output(output_name_0_13, value=output_value))

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
        values['depends_on'] = self.get_dependencies([user_tf_resource])
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        self.add_resources(account, tf_resources)

    def populate_tf_resource_ecr(self, resource, namespace_info):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        # ecr repository
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/ecr_repository.html
        values = {}
        values['name'] = identifier
        values['tags'] = common_values['tags']

        region = common_values.get('region') or \
            self.default_regions.get(account)
        if self._multiregion_account(account):
            values['provider'] = 'aws.' + region
        ecr_tf_resource = aws_ecr_repository(identifier, **values)
        public = common_values.get('public')
        if public:
            # ecr public repository
            # does not support tags
            values.pop('tags')
            # uses repository_name and not name
            values['repository_name'] = values.pop('name')
            ecr_tf_resource = aws_ecrpublic_repository(identifier, **values)
        tf_resources.append(ecr_tf_resource)
        output_name_0_13 = output_prefix + '__url'
        output_value = '${' + ecr_tf_resource.repository_url + '}'
        if public:
            output_value = '${' + ecr_tf_resource.repository_uri + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        output_name_0_13 = output_prefix + '__aws_region'
        tf_resources.append(Output(output_name_0_13, value=region))

        # iam resources
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/iam_access_key.html

        # iam user for repository
        values = {}
        values['name'] = identifier
        values['tags'] = common_values['tags']
        values['depends_on'] = self.get_dependencies([ecr_tf_resource])
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
                    "Resource": "${" + ecr_tf_resource.arn + "}"
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
                    "Resource": "${" + ecr_tf_resource.arn + "}"
                }
            ]
        }
        values['policy'] = json.dumps(policy, sort_keys=True)
        values['depends_on'] = self.get_dependencies([user_tf_resource])
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        self.add_resources(account, tf_resources)

    def populate_tf_resource_s3_cloudfront(self, resource, namespace_info):
        # pylint: disable=unused-variable
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
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
                               cf_oai_tf_resource.iam_arn + "}"
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
        values['depends_on'] = self.get_dependencies([bucket_tf_resource])
        region = common_values.get('region') or \
            self.default_regions.get(account)
        if self._multiregion_account(account):
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
                '${' + bucket_tf_resource.bucket_domain_name + '}',
            'origin_id':
                values['default_cache_behavior']['target_origin_id'],
            's3_origin_config': {
                'origin_access_identity':
                    'origin-access-identity/cloudfront/' +
                    '${' + cf_oai_tf_resource.id + '}'
                }
        }
        values['origin'] = [origin]
        cf_distribution_tf_resource = \
            aws_cloudfront_distribution(identifier, **values)
        tf_resources.append(cf_distribution_tf_resource)

        # outputs
        # cloud_front_origin_access_identity_id
        output_name_0_13 = output_prefix + \
            '__cloud_front_origin_access_identity_id'
        output_value = '${' + cf_oai_tf_resource.id + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # s3_canonical_user_id
        output_name_0_13 = output_prefix + \
            '__s3_canonical_user_id'
        output_value = '${' + cf_oai_tf_resource.s3_canonical_user_id + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # distribution_domain
        output_name_0_13 = output_prefix + \
            '__distribution_domain'
        output_value = '${' + cf_distribution_tf_resource.domain_name + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # origin_access_identity
        output_name_0_13 = output_prefix + \
            '__origin_access_identity'
        output_value = 'origin-access-identity/cloudfront/' + \
            '${' + cf_oai_tf_resource.id + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def populate_tf_resource_s3_sqs(self, resource, namespace_info):
        # pylint: disable=unused-variable
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)
        uid = self.uids.get(account)

        bucket_tf_resource = \
            self.populate_tf_resource_s3(resource, namespace_info)

        region = common_values.get('region') or \
            self.default_regions.get(account)
        provider = ''
        if self._multiregion_account(account):
            provider = 'aws.' + region
        tf_resources = []
        sqs_identifier = f'{identifier}-sqs'
        sqs_values = {
            'name': sqs_identifier
        }

        sqs_values['visibility_timeout_seconds'] = \
            int(common_values.get('visibility_timeout_seconds', 30))
        sqs_values['message_retention_seconds'] = \
            int(common_values.get('message_retention_seconds', 345600))

        # https://docs.aws.amazon.com/AmazonS3/latest/dev/NotificationHowTo.html#grant-destinations-permissions-to-s3
        sqs_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": "*",
                "Action": "sqs:SendMessage",
                "Resource": f"arn:{self._get_partition(account)}:" +
                            f"sqs:*:*:{sqs_identifier}",
                "Condition": {
                    "ArnEquals": {
                        "aws:SourceArn":
                            '${' + bucket_tf_resource.arn + '}'
                    }
                }
            }]
        }
        sqs_values['policy'] = json.dumps(sqs_policy, sort_keys=True)

        kms_encryption = common_values.get('kms_encryption', False)
        if kms_encryption:
            kms_identifier = f'{identifier}-kms'
            kms_values = {
                'description':
                    'app-interface created KMS key for' + sqs_identifier
            }
            kms_values['key_usage'] = \
                str(common_values.get('key_usage', 'ENCRYPT_DECRYPT')).upper()
            kms_values['customer_master_key_spec'] = \
                str(common_values.get('customer_master_key_spec',
                                      'SYMMETRIC_DEFAULT')).upper()
            kms_values['is_enabled'] = common_values.get('is_enabled', True)

            kms_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "AWS": f"arn:{self._get_partition(account)}:" +
                                   f"iam::{uid}:root"
                        },
                        "Action": "kms:*",
                        "Resource": "*"
                    },
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "s3.amazonaws.com"
                        },
                        "Action": [
                            "kms:GenerateDataKey",
                            "kms:Decrypt"
                        ],
                        "Resource": "*"
                    }
                ]
            }
            kms_values['policy'] = json.dumps(kms_policy, sort_keys=True)
            if provider:
                kms_values['provider'] = provider

            kms_tf_resource = aws_kms_key(kms_identifier, **kms_values)
            tf_resources.append(kms_tf_resource)

            alias_values = {
                'name': 'alias/' + kms_identifier,
                'target_key_id':
                    '${' + kms_tf_resource.key_id + '}'
            }
            if provider:
                alias_values['provider'] = provider
            alias_tf_resource = aws_kms_alias(kms_identifier, **alias_values)
            tf_resources.append(alias_tf_resource)

            sqs_values['kms_master_key_id'] = '${' + kms_tf_resource.arn + '}'
            sqs_values['depends_on'] = self.get_dependencies([kms_tf_resource])

        if provider:
            sqs_values['provider'] = provider

        sqs_tf_resource = aws_sqs_queue(sqs_identifier, **sqs_values)
        tf_resources.append(sqs_tf_resource)

        s3_events = common_values.get('s3_events', ["s3:ObjectCreated:*"])
        notification_values = {
            'bucket': '${' + bucket_tf_resource.id + '}',
            'queue': [{
                'id': sqs_identifier,
                'queue_arn':
                    '${' + sqs_tf_resource.arn + '}',
                'events': s3_events
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
        values['depends_on'] = self.get_dependencies([user_tf_resource])
        access_key_tf_resource = aws_iam_access_key(sqs_identifier, **values)
        tf_resources.append(access_key_tf_resource)
        # outputs
        # sqs_aws_access_key_id
        output_name_0_13 = output_prefix + '__sqs_aws_access_key_id'
        output_value = '${' + access_key_tf_resource.id + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # sqs_aws_secret_access_key
        output_name_0_13 = output_prefix + '__sqs_aws_secret_access_key'
        output_value = '${' + access_key_tf_resource.secret + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))

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
                        f"arn:{self._get_partition(account)}:" +
                        f"sqs:*:{uid}:{sqs_identifier}"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": ["sqs:ListQueues"],
                    "Resource": "*"
                }
            ]
        }
        if kms_encryption:
            kms_statement = {
                "Effect": "Allow",
                "Action": ["kms:Decrypt"],
                "Resource": [
                    sqs_values['kms_master_key_id']
                ]
            }
            policy['Statement'].append(kms_statement)
        values['policy'] = json.dumps(policy, sort_keys=True)
        policy_tf_resource = aws_iam_policy(sqs_identifier, **values)
        tf_resources.append(policy_tf_resource)

        # iam user policy attachment
        values = {}
        values['user'] = sqs_identifier
        values['policy_arn'] = \
            '${' + policy_tf_resource.arn + '}'
        values['depends_on'] = self.get_dependencies(
            [user_tf_resource, policy_tf_resource])
        user_policy_attachment_tf_resource = \
            aws_iam_user_policy_attachment(sqs_identifier, **values)
        tf_resources.append(user_policy_attachment_tf_resource)

        # outputs
        output_name_0_13 = '{}__{}'.format(output_prefix, sqs_identifier)
        output_value = \
            'https://sqs.{}.amazonaws.com/{}/{}'.format(
                region, uid, sqs_identifier)
        tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def populate_tf_resource_cloudwatch(self, resource, namespace_info):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

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

        region = common_values.get('region') or \
            self.default_regions.get(account)
        provider = ''
        if self._multiregion_account(account):
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
                'role': "${" + role_tf_resource.id + "}",
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
            tf_resources.append(
                data.aws_elasticsearch_domain(es_identifier, **es_domain))

            release_url = common_values.get('release_url', LOGTOES_RELEASE)
            zip_file = self.get_logtoes_zip(release_url)

            lambda_identifier = f"{identifier}-lambda"
            lambda_values = {
                'filename': zip_file,
                'source_code_hash':
                    '${filebase64sha256("' + zip_file + '")}',
                'role': "${" + role_tf_resource.arn + "}"
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
                'subnet_ids':
                    "${data.aws_elasticsearch_domain." + es_identifier +
                    ".vpc_options.0.subnet_ids}",
                'security_group_ids':
                    "${data.aws_elasticsearch_domain." + es_identifier +
                    ".vpc_options.0.security_group_ids}"
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
                'function_name': "${" + lambds_tf_resource.arn + "}",
                'principal': 'logs.amazonaws.com',
                'source_arn': "${" + log_group_tf_resource.arn + "}:*"
            }

            if provider:
                permission_vaules['provider'] = provider
            permission_tf_resource = \
                aws_lambda_permission(lambda_identifier, **permission_vaules)
            tf_resources.append(permission_tf_resource)

            subscription_vaules = {
                'name': lambda_identifier,
                'log_group_name': log_group_tf_resource.name,
                'destination_arn':
                    "${" + lambds_tf_resource.arn + "}",
                'filter_pattern': "",
                'depends_on': self.get_dependencies([log_group_tf_resource])
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

        output_name_0_13 = output_prefix + '__log_group_name'
        output_value = log_group_tf_resource.name
        tf_resources.append(Output(output_name_0_13, value=output_value))
        output_name_0_13 = output_prefix + '__aws_region'
        tf_resources.append(Output(output_name_0_13, value=region))

        # iam resources
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/iam_access_key.html

        # iam user for log group
        values = {
            'name': identifier,
            'tags': common_values['tags'],
            'depends_on': self.get_dependencies([log_group_tf_resource])
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
                        "${" + log_group_tf_resource.arn + "}:*"
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
            'depends_on': self.get_dependencies([user_tf_resource])
        }
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        self.add_resources(account, tf_resources)

    def populate_tf_resource_kms(self, resource, namespace_info):
        account, identifier, values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)
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
        if self._multiregion_account(account):
            values['provider'] = 'aws.' + region

        tf_resource = aws_kms_key(identifier, **values)
        tf_resources.append(tf_resource)

        # key_id
        output_name_0_13 = output_prefix + '__key_id'
        output_value = '${' + tf_resource.key_id + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))

        alias_values = {}
        alias_values['name'] = "alias/" + identifier
        alias_values['target_key_id'] = "${aws_kms_key." + identifier + \
                                        ".key_id}"
        if self._multiregion_account(account):
            alias_values['provider'] = 'aws.' + region
        tf_resource = aws_kms_alias(identifier, **alias_values)
        tf_resources.append(tf_resource)

        self.add_resources(account, tf_resources)

    def populate_tf_resource_kinesis(self, resource, namespace_info):
        account, identifier, values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        # pop identifier since we use values and not common_values
        values.pop('identifier', None)

        # get region and set provider if required
        region = values.pop('region', None) or \
            self.default_regions.get(account)
        if self._multiregion_account(account):
            values['provider'] = 'aws.' + region

        # kinesis stream
        # Terraform resource reference:
        # https://www.terraform.io/docs/providers/aws/r/kinesis_stream.html
        kinesis_tf_resource = aws_kinesis_stream(identifier, **values)
        tf_resources.append(kinesis_tf_resource)
        # outputs
        # stream_name
        output_name_0_13 = output_prefix + '__stream_name'
        tf_resources.append(Output(output_name_0_13, value=identifier))
        # aws_region
        output_name_0_13 = output_prefix + '__aws_region'
        tf_resources.append(Output(output_name_0_13, value=region))

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
                        "${" + kinesis_tf_resource.arn + "}"
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

        self.add_resources(account, tf_resources)

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
        if dep_tf_resource:
            values['depends_on'] = self.get_dependencies([dep_tf_resource])
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
        values['depends_on'] = self.get_dependencies([user_tf_resource])
        tf_resource = aws_iam_user_policy(identifier, **values)
        tf_resources.append(tf_resource)

        return tf_resources

    def get_tf_iam_access_key(self, user_tf_resource,
                              identifier, output_prefix):
        tf_resources = []
        values = {}
        values['user'] = identifier
        values['depends_on'] = self.get_dependencies([user_tf_resource])
        tf_resource = aws_iam_access_key(identifier, **values)
        tf_resources.append(tf_resource)
        # outputs
        # aws_access_key_id
        output_name_0_13 = output_prefix + '__aws_access_key_id'
        output_value = '${' + tf_resource.id + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # aws_secret_access_key
        output_name_0_13 = output_prefix + '__aws_secret_access_key'
        output_value = '${' + tf_resource.secret + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))

        return tf_resources

    def add_resources(self, account, tf_resources):
        for r in tf_resources:
            self.add_resource(account, r)

    def add_resource(self, account, tf_resource):
        if account not in self.locks:
            logging.debug(
                'integration {} is disabled for account {}. '
                'can not add resource'.format(self.integration, account))
            return
        with self.locks[account]:
            self.tss[account].add(tf_resource)

    def dump(self,
             print_to_file: Optional[str] = None,
             existing_dirs: Optional[dict[str, str]] = None) -> dict[str, str]:
        """
        Dump the Terraform configurations (in JSON format) to the working directories.

        :param print_to_file: an alternative path to write the file to in addition to
                              the standard location
        :param existing_dirs: existing working directory, key is account name, value is
                              the directory location
        :return: key is AWS account name and value is directory location
        """
        if existing_dirs is None:
            working_dirs: dict[str, str] = {}
        else:
            working_dirs = existing_dirs

        if print_to_file:
            if is_file_in_git_repo(print_to_file):
                raise PrintToFileInGitRepositoryError(print_to_file)
            if os.path.isfile(print_to_file):
                os.remove(print_to_file)

        for name, ts in self.tss.items():
            if print_to_file:
                with open(print_to_file, 'a') as f:
                    f.write(f'##### {name} #####\n')
                    f.write(str(ts))
                    f.write('\n')
            if existing_dirs is None:
                wd = tempfile.mkdtemp()
            else:
                wd = working_dirs[name]
            with open(wd + '/config.tf.json', 'w') as f:
                f.write(str(ts))
            working_dirs[name] = wd

        return working_dirs

    def init_values(self,
                    resource: Mapping[str, Any],
                    namespace_info: Mapping[str, Any]
                    ) -> tuple[str, str, dict, str, str, dict]:
        """
        Initialize the values of the terraform resource and merge the defaults and
        overrides.

        :param resource: schemas/openshift/terraform-resource-1.yml object
        :param namespace_info: schemas/openshift/namespace-1.yml object
        """
        account = resource['account']
        provider = resource['provider']
        identifier = resource['identifier']
        defaults_path = resource.get('defaults', None)
        overrides = resource.get('overrides', None)

        values = self.get_values(defaults_path) if defaults_path else {}
        self.aggregate_values(values)
        self.override_values(values, overrides)
        values['identifier'] = identifier
        values['tags'] = self.get_resource_tags(namespace_info)

        for key in VARIABLE_KEYS:
            val = resource.get(key, None)
            # checking explicitly for not None
            # to allow passing empty strings, False, etc
            if val is not None:
                values[key] = val

        output_prefix = '{}-{}'.format(identifier, provider)
        output_resource_name = resource['output_resource_name']
        if output_resource_name is None:
            output_resource_name = output_prefix

        annotations = json.loads(resource.get('annotations') or '{}')

        return account, identifier, values, output_prefix, \
            output_resource_name, annotations

    @staticmethod
    def aggregate_values(values):
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

    @staticmethod
    def override_values(values, overrides):
        if overrides is None:
            return
        data = json.loads(overrides)
        for k, v in data.items():
            values[k] = v

    def init_common_outputs(self, tf_resources, namespace_info,
                            output_prefix, output_resource_name, annotations):
        output_format_0_13 = '{}__{}_{}'
        cluster, namespace, _, _ = self.unpack_namespace_info(namespace_info)
        # cluster
        output_name_0_13 = output_format_0_13.format(
            output_prefix, self.integration_prefix, 'cluster')
        output_value = cluster
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # namespace
        output_name_0_13 = output_format_0_13.format(
            output_prefix, self.integration_prefix, 'namespace')
        output_value = namespace
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # resource
        output_name_0_13 = output_format_0_13.format(
            output_prefix, self.integration_prefix, 'resource')
        output_value = 'Secret'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # output_resource_name
        output_name_0_13 = output_format_0_13.format(
            output_prefix, self.integration_prefix, 'output_resource_name')
        output_value = output_resource_name
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # annotations
        if annotations:
            output_name_0_13 = output_format_0_13.format(
                output_prefix, self.integration_prefix, 'annotations')
            anno_json = json.dumps(annotations).encode("utf-8")
            output_value = base64.b64encode(anno_json).decode()
            tf_resources.append(Output(output_name_0_13, value=output_value))

    @staticmethod
    def get_raw_values(path):
        gqlapi = gql.get_api()
        try:
            raw_values = gqlapi.get_resource(path)
        except gql.GqlGetResourceError as e:
            raise FetchResourceError(str(e))
        return raw_values

    @staticmethod
    def get_values(path):
        raw_values = TerrascriptClient.get_raw_values(path)
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
        cluster, namespace, environment, app = self.unpack_namespace_info(namespace_info)
        return {
            'managed_by_integration': self.integration,
            'cluster': cluster,
            'namespace': namespace,
            'environment': environment,
            'app': app,
        }

    @staticmethod
    def unpack_namespace_info(namespace_info):
        cluster = namespace_info['cluster']['name']
        namespace = namespace_info['name']
        environment = namespace_info['environment']['name']
        app = namespace_info['app']['name']
        return cluster, namespace, environment, app

    @staticmethod
    def get_dependencies(tf_resources: Iterable[Resource]
                         ) -> List[str]:
        return [f"{tf_resource.__class__.__name__}.{tf_resource._name}"
                for tf_resource in tf_resources]

    @staticmethod
    def get_elasticsearch_service_role_tf_resource():
        """ Service role for ElasticSearch. """
        service_role = {
            'aws_service_name': 'es.amazonaws.com',
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

    @staticmethod
    def elasticsearch_log_group_identifier(
        domain_identifier: str,
        log_type: ElasticSearchLogGroupType
    ) -> str:
        log_type_name = log_type.value.lower()
        return f'OpenSearchService__{domain_identifier}__{log_type_name}'

    def _elasticsearch_get_all_log_group_infos(
        self
    ) -> list[ElasticSearchLogGroupInfo]:
        """
        Gather all cloud_watch_log_groups for the
        current account. This is required to set
        an account-wide resource policy.
        """
        log_group_infos = []
        for resources in self.account_resources.values():
            for i in resources:
                res = i['resource']
                ns = i['namespace_info']
                if res.get('provider') != 'elasticsearch':
                    continue
                # res.get('', []) won't work, as publish_log_types is
                # explicitly set to None if not set
                log_types = res['publish_log_types'] or []
                for log_type in log_types:
                    region = ns['cluster']['spec']['region']
                    account = res['account']
                    account_id = self.accounts[account]['uid']
                    lg_identifier = \
                        TerrascriptClient.elasticsearch_log_group_identifier(
                            domain_identifier=res['identifier'],
                            log_type=ElasticSearchLogGroupType(log_type),
                        )
                    log_group_infos.append(
                        ElasticSearchLogGroupInfo(
                            account=account,
                            account_id=account_id,
                            region=region,
                            log_group_identifier=lg_identifier,
                        )
                    )
        return log_group_infos

    def _get_elasticsearch_account_wide_resource_policy(
        self, account: str
    ) -> Optional[aws_cloudwatch_log_resource_policy]:
        """
        https://docs.aws.amazon.com/opensearch-service/latest/developerguide/createdomain-configure-slow-logs.html
        CloudWatch Logs supports 10 resource policies per Region.
        If you plan to enable logs for several OpenSearch Service domains,
        you should create and reuse a broader policy that includes multiple
        log groups to avoid reaching this limit.
        I.e., ideally we aggregate ALL log group identifiers for each
        account first.

        This function returns None, if no log groups are found for that
        account.
        """
        log_group_infos = \
            self._elasticsearch_get_all_log_group_infos()

        if not log_group_infos:
            return None

        log_groups_policy = {
            'Version': '2012-10-17',
            'Statement': [{
                'Effect': 'Allow',
                'Principal': {
                    'Service': 'es.amazonaws.com',
                },
                'Action': [
                    'logs:PutLogEvents',
                    'logs:CreateLogStream',
                ],
                'Resource': [
                    (
                        f'arn:aws:logs:{info.region}:{info.account_id}'
                        f':log-group:{info.log_group_identifier}:*'
                    )
                    for info in log_group_infos if info.account == account
                ],
            }]
        }
        log_groups_policy_values = {
            'policy_name': 'es-log-publishing-permissions',
            'policy_document': json.dumps(log_groups_policy, sort_keys=True),
        }
        resource_policy = aws_cloudwatch_log_resource_policy(
            'es_log_publishing_resource_policy',
            **log_groups_policy_values,
        )
        return resource_policy

    def _get_tf_resource_elasticsearch_log_groups(
        self, identifier: str, account: str,
        resource: Mapping[str, Any], values: Mapping[str, Any],
        output_prefix: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """
        Generate cloud_watch_log_group terraform_resources
        for the given resource. Further, generate
        publishing_options blocks which will be further used
        by the consumer.
        """
        ES_LOG_GROUP_RETENTION_DAYS = 90
        tf_resources = []
        publishing_options = []

        # res.get('', []) won't work, as publish_log_types is
        # explicitly set to None if not set
        log_types = resource['publish_log_types'] or []
        for log_type in log_types:
            log_type_identifier = \
                TerrascriptClient.elasticsearch_log_group_identifier(
                    domain_identifier=identifier,
                    log_type=ElasticSearchLogGroupType(log_type),
                )
            log_group_values = {
                'name': log_type_identifier,
                'tags': {},
                'retention_in_days': ES_LOG_GROUP_RETENTION_DAYS,
            }
            region = values.get('region') or \
                self.default_regions.get(account)
            if self._multiregion_account(account):
                log_group_values['provider'] = f'aws.{region}'
            log_group_tf_resource = \
                aws_cloudwatch_log_group(log_type_identifier,
                                         **log_group_values)
            tf_resources.append(log_group_tf_resource)
            arn = f'${{{log_group_tf_resource.arn}}}'

            # add arn to output
            output_name_0_13 = (
                f'{output_prefix}__cloudwatch_log_group_'
                f'{log_type.lower()}_arn'
            )
            output_value = arn
            tf_resources.append(Output(output_name_0_13, value=output_value))

            # add name to output
            output_name_0_13 = (
                f'{output_prefix}__cloudwatch_log_group_'
                f'{log_type.lower()}_name'
            )
            output_value = log_type_identifier
            tf_resources.append(Output(output_name_0_13, value=output_value))
            publishing_options.append(
                {
                    'log_type': log_type,
                    'cloudwatch_log_group_arn': arn,
                }
            )

        return tf_resources, publishing_options

    def populate_tf_resource_elasticsearch(self, resource, namespace_info):

        account, identifier, values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []

        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        if not self.is_elasticsearch_domain_name_valid(values['identifier']):
            raise ElasticSearchResourceNameInvalidError(
                f"[{account}] ElasticSearch domain name must must start with" +
                " a lowercase letter and must be between 3 and 28 " +
                "characters. Valid characters are a-z (lowercase only), 0-9" +
                ", and - (hyphen). " +
                f"{values['identifier']}")

        es_values = {}
        es_values["domain_name"] = identifier
        es_values["elasticsearch_version"] = \
            values.get('elasticsearch_version')

        log_group_resources, publishing_options = \
            self._get_tf_resource_elasticsearch_log_groups(
                identifier=identifier,
                account=account,
                resource=resource,
                values=values,
                output_prefix=output_prefix
            )
        tf_resources += log_group_resources

        resource_policy = self._get_elasticsearch_account_wide_resource_policy(
            account=account,
        )
        if resource_policy:
            tf_resources.append(resource_policy)

        es_values['log_publishing_options'] = publishing_options
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
        tf_resources.append(svc_role_tf_resource)
        es_deps = [svc_role_tf_resource]
        if resource_policy:
            es_deps.append(resource_policy)
        es_values['depends_on'] = self.get_dependencies(
            es_deps,
        )

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

        region = values.get('region') or \
            self.default_regions.get(account)
        if self._multiregion_account(account):
            es_values['provider'] = 'aws.' + region

        advanced_security_options = values.get('advanced_security_options', {})
        if advanced_security_options:
            es_values['advanced_security_options'] = \
                self._build_es_advanced_security_options(
                    advanced_security_options)

        es_tf_resource = aws_elasticsearch_domain(identifier, **es_values)
        tf_resources.append(es_tf_resource)

        # Setup outputs
        # arn
        output_name_0_13 = output_prefix + '__arn'
        output_value = '${' + es_tf_resource.arn + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # domain_id
        output_name_0_13 = output_prefix + '__domain_id'
        output_value = '${' + es_tf_resource.domain_id + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # domain_name
        output_name_0_13 = output_prefix + '__domain_name'
        output_value = es_tf_resource.domain_name
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # endpoint
        output_name_0_13 = output_prefix + '__endpoint'
        output_value = 'https://' + \
            '${' + es_tf_resource.endpoint + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # kibana_endpoint
        output_name_0_13 = output_prefix + '__kibana_endpoint'
        output_value = 'https://' + \
            '${' + es_tf_resource.kibana_endpoint + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # vpc_id
        output_name_0_13 = output_prefix + '__vpc_id'
        output_value = '${aws_elasticsearch_domain.' + identifier + \
            '.vpc_options.0.vpc_id}'
        tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def _build_es_advanced_security_options(
            self, advanced_security_options: MutableMapping[str, Any]) \
            -> MutableMapping[str, Any]:
        master_user_options = advanced_security_options.pop(
            'master_user_options', {})

        if master_user_options:
            master_user_secret = master_user_options['master_user_secret']
            secret_data = self.secret_reader.read_all(master_user_secret)

            required_keys = {'master_user_name', 'master_user_password'}
            if secret_data.keys() != required_keys:
                raise KeyError(
                    f"vault secret '{master_user_secret['path']}' must "
                    f"exactly contain these keys: {', '.join(required_keys)}")

            advanced_security_options['master_user_options'] = secret_data

        return advanced_security_options

    def populate_tf_resource_acm(self, resource, namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        values = {}
        secret = common_values.get('secret', None)
        if secret is not None:
            secret_data = self.secret_reader.read_all(secret)

            key = secret_data.get('key', None)
            if key is None:
                raise KeyError(
                    f"Vault secret '{secret['path']}' " +
                    "does not have required key [key]")

            certificate = secret_data.get('certificate', None)
            if certificate is None:
                raise KeyError(
                    f"Vault secret '{secret['path']}' " +
                    "does not have required key [certificate]")

            caCertificate = secret_data.get('caCertificate', None)

            values['private_key'] = key
            values['certificate_body'] = certificate
            if caCertificate is not None:
                values['certificate_chain'] = caCertificate

        domain = common_values.get('domain', None)
        if domain is not None:
            values['domain_name'] = domain['domain_name']
            values['validation_method'] = 'DNS'

            alt_names = domain.get('alternate_names', None)
            if alt_names is not None:
                values['subject_alternative_names'] = alt_names

        region = common_values.get('region') or \
            self.default_regions.get(account)
        if self._multiregion_account(account):
            values['provider'] = 'aws.' + region

        acm_tf_resource = aws_acm_certificate(identifier, **values)
        tf_resources.append(acm_tf_resource)

        # outputs
        # arn
        output_name_0_13 = output_prefix + '__arn'
        output_value = '${' + acm_tf_resource.arn + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # domain name
        # output_name_0_13 = output_prefix + '__domain_name'
        # output_value = '${' + acm_tf_resource.domain_name + '}'
        # tf_resources.append(Output(output_name_0_13, value=output_value))
        # status
        output_name_0_13 = output_prefix + '__status'
        output_value = '${' + acm_tf_resource.status + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # domain_validation_options
        output_name_0_13 = output_prefix + '__domain_validation_options'
        output_value = '${' + acm_tf_resource.domain_validation_options + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        if secret is not None:
            # key
            output_name_0_13 = output_prefix + '__key'
            output_value = key
            tf_resources.append(Output(output_name_0_13, value=output_value))
            # certificate
            output_name_0_13 = output_prefix + '__certificate'
            output_value = certificate
            tf_resources.append(Output(output_name_0_13, value=output_value))
            if caCertificate is not None:
                output_name_0_13 = output_prefix + '__caCertificate'
                output_value = caCertificate
                tf_resources.append(
                    Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def populate_tf_resource_s3_cloudfront_public_key(self, resource,
                                                      namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        values = {'name': identifier, 'comment': 'managed by app-interface'}
        secret = common_values.get('secret', None)
        if secret is None:
            raise KeyError('no secret defined for s3_cloudfront_public_key '
                           f'{identifier}')

        secret_data = self.secret_reader.read_all(secret)

        secret_key = 'cloudfront_public_key'
        key = secret_data.get(secret_key, None)
        if key is None:
            raise KeyError(
                f"vault secret '{secret['path']}' " +
                f"does not have required key [{secret_key}]")

        values['encoded_key'] = key

        pk_tf_resource = aws_cloudfront_public_key(identifier, **values)
        tf_resources.append(pk_tf_resource)

        # outputs
        # etag
        output_name_0_13 = output_prefix + '_etag'
        output_value = '${' + pk_tf_resource.etag + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # id
        output_name_0_13 = output_prefix + '__id'
        output_value = '${' + pk_tf_resource.id + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # key
        output_name_0_13 = output_prefix + '__key'
        output_value = key
        tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def _get_alb_target_ips_by_openshift_service(self,
                                                 identifier,
                                                 openshift_service,
                                                 account_name,
                                                 namespace_info,
                                                 ocm_map):
        account = self.accounts[account_name]
        awsapi = AWSApi(1, [account],
                        settings=self.settings,
                        init_users=False)
        cluster = namespace_info['cluster']
        ocm = ocm_map.get(cluster['name'])
        account['assume_role'] = \
            ocm.get_aws_infrastructure_access_terraform_assume_role(
                cluster['name'],
                account['uid'],
                account['terraformUsername'],
        )
        account['assume_region'] = cluster['spec']['region']
        service_name = \
            f"{namespace_info['name']}/{openshift_service}"
        ips = awsapi.get_alb_network_interface_ips(
            account,
            service_name
        )
        if not ips:
            raise ValueError(
                f'[{account_name}/{identifier}] expected at least one '
                f'network interface IP for openshift service {service_name}'
            )

        return ips

    def populate_tf_resource_alb(self, resource, namespace_info,
                                 ocm_map=None):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)
        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        default_region = self.default_regions.get(account)
        cluster_region = namespace_info['cluster']['spec']['region']

        if self._multiregion_account(account):
            provider = 'aws.' + cluster_region
        else:
            provider = 'aws.' + default_region

        vpc = resource['vpc']
        vpc_id = vpc['vpc_id']
        vpc_cidr_block = vpc['cidr_block']

        # https://www.terraform.io/docs/providers/aws/r/security_group.html
        # we will only support https (+ http redirection) at first
        # this can be enhanced when a use case comes along
        # https://github.com/hashicorp/terraform-provider-aws/issues/878
        empty_required_sg_values = {
            'prefix_list_ids': None,
            'security_groups': None,
            'self': None,
        }
        values = {
            'provider': provider,
            'vpc_id': vpc_id,
            'tags': common_values['tags'],

            'ingress': [
                {
                    'description': 'allow http',
                    'from_port': 80,
                    'to_port': 80,
                    'protocol': 'tcp',
                    'cidr_blocks': ['0.0.0.0/0'],
                    'ipv6_cidr_blocks': ['::/0'],
                    **empty_required_sg_values,
                },
                {
                    'description': 'allow https',
                    'from_port': 443,
                    'to_port': 443,
                    'protocol': 'tcp',
                    'cidr_blocks': ['0.0.0.0/0'],
                    'ipv6_cidr_blocks': ['::/0'],
                    **empty_required_sg_values,
                }
            ],

            'egress': [
                {
                    'description': 'allow http',
                    'from_port': 80,
                    'to_port': 80,
                    'protocol': 'tcp',
                    'cidr_blocks': ['0.0.0.0/0'],
                    'ipv6_cidr_blocks': ['::/0'],
                    **empty_required_sg_values,
                },
                {
                    'description': 'allow https',
                    'from_port': 443,
                    'to_port': 443,
                    'protocol': 'tcp',
                    'cidr_blocks': ['0.0.0.0/0'],
                    'ipv6_cidr_blocks': ['::/0'],
                    **empty_required_sg_values,
                }
            ]
        }
        sg_tf_resource = aws_security_group(identifier, **values)
        tf_resources.append(sg_tf_resource)

        # https://www.terraform.io/docs/providers/aws/r/lb.html
        values = {
            'provider': provider,
            'name': identifier,
            'internal': False,
            'ip_address_type': 'dualstack',
            'load_balancer_type': 'application',
            'security_groups': [f'${{{sg_tf_resource.id}}}'],
            'subnets': [s['id'] for s in vpc['subnets']],
            'tags': common_values['tags'],
            'depends_on': self.get_dependencies([sg_tf_resource]),
        }

        idle_timeout = resource.get('idle_timeout')
        if idle_timeout:
            values['idle_timeout'] = idle_timeout

        lb_tf_resource = aws_lb(identifier, **values)
        tf_resources.append(lb_tf_resource)

        default_target = None
        valid_targets = {}
        for t in resource['targets']:
            target_name = t['name']
            t_openshift_service = t.get('openshift_service')
            t_ips = t.get('ips')
            if t_openshift_service:
                target_ips = self._get_alb_target_ips_by_openshift_service(
                    identifier,
                    t_openshift_service,
                    account,
                    namespace_info,
                    ocm_map
                )
            elif t_ips:
                target_ips = t_ips
            else:
                raise KeyError('expected one of openshift_service or ips.')

            # https://www.terraform.io/docs/providers/random/r/id
            # The random ID will regenerate based on the 'keepers' values
            # So as long as the 'keepers' values don't change the ID will
            # remain the same
            lbt_random_id_values = {
                'keepers': {
                    'name': target_name,
                },
                'byte_length': 4,
            }
            lbt_random_id = random_id(
                f'{identifier}-{target_name}', **lbt_random_id_values)
            tf_resources.append(lbt_random_id)

            # https://www.terraform.io/docs/providers/aws/r/
            # lb_target_group.html
            values = {
                'provider': provider,
                'name': f'{target_name}-${{{lbt_random_id.hex}}}',
                'port': 443,
                'protocol': 'HTTPS',
                'protocol_version': 'HTTP1',
                'target_type': 'ip',
                'vpc_id': vpc_id,
                'health_check': {
                    'interval': 10,
                    'path': '/',
                    'protocol': 'HTTPS',
                    'port': 443,
                },
                'lifecycle': {
                    'create_before_destroy': True,
                }
            }
            lbt_identifier = f'{identifier}-{target_name}'
            lbt_tf_resource = aws_lb_target_group(lbt_identifier, **values)
            tf_resources.append(lbt_tf_resource)
            valid_targets[target_name] = lbt_tf_resource

            if t['default']:
                if default_target:
                    raise KeyError('expected only a single default target')
                default_target = lbt_tf_resource

            for ip in target_ips:
                # https://www.terraform.io/docs/providers/aws/r/
                # lb_target_group_attachment.html
                values = {
                    'provider': provider,
                    'target_group_arn': f'${{{lbt_tf_resource.arn}}}',
                    'target_id': ip,
                    'port': 443,
                    'depends_on': self.get_dependencies([lbt_tf_resource])
                }
                if not ip_address(ip) in ip_network(vpc_cidr_block):
                    values['availability_zone'] = 'all'
                ip_slug = ip.replace('.', '_')
                lbta_identifier = f'{lbt_identifier}-{ip_slug}'
                lbta_tf_resource = \
                    aws_lb_target_group_attachment(lbta_identifier, **values)
                tf_resources.append(lbta_tf_resource)

        # https://www.terraform.io/docs/providers/aws/r/lb_listener.html
        # redirect
        values = {
            'provider': provider,
            'load_balancer_arn': f'${{{lb_tf_resource.arn}}}',
            'port': 80,
            'protocol': 'HTTP',
            'default_action': {
                'type': 'redirect',
                'redirect': {
                    'port': 443,
                    'protocol': 'HTTPS',
                    'status_code': 'HTTP_301',
                }
            },
            'depends_on': self.get_dependencies([lb_tf_resource]),
        }
        redirect_identifier = f'{identifier}-redirect'
        redirect_lbl_tf_resource = \
            aws_lb_listener(redirect_identifier, **values)
        tf_resources.append(redirect_lbl_tf_resource)
        # forward
        if not default_target:
            raise KeyError('expected a single default target')
        values = {
            'provider': provider,
            'load_balancer_arn': f'${{{lb_tf_resource.arn}}}',
            'port': 443,
            'protocol': 'HTTPS',
            'ssl_policy': 'ELBSecurityPolicy-TLS-1-2-2017-01',
            'certificate_arn': resource['certificate_arn'],
            'default_action': {
                'type': 'forward',
                'target_group_arn': f'${{{default_target.arn}}}',
            },
            'depends_on': self.get_dependencies(
                [lb_tf_resource, default_target]),
        }
        forward_identifier = f'{identifier}-forward'
        forward_lbl_tf_resource = aws_lb_listener(forward_identifier, **values)
        tf_resources.append(forward_lbl_tf_resource)

        # https://www.terraform.io/docs/providers/aws/r/lb_listener_rule.html
        for rule_num, rule in enumerate(resource['rules']):
            condition = rule['condition']
            action = rule['action']
            config_methods = condition.get('methods', None)

            values = {
                'provider': provider,
                'listener_arn': f'${{{forward_lbl_tf_resource.arn}}}',
                'priority': rule_num + 1,
                'action': {
                    'type': 'forward',
                    'forward': {
                        'target_group': [],
                        'stickiness': {
                            'enabled': False,
                            'duration': 1,
                        }
                    },
                },
                'condition': [
                    {'path_pattern': {'values': [condition['path']]}}
                ],
                'depends_on': self.get_dependencies([forward_lbl_tf_resource]),
            }

            if config_methods:
                values['condition'].append(
                    {'http_request_method': {'values': config_methods}}
                )

            weight_sum = 0
            for a in action:
                target_name = a['target']
                if target_name not in valid_targets:
                    raise KeyError(
                        f'{target_name} not a valid target name'
                    )

                target_resource = valid_targets[target_name]

                values['action']['forward']['target_group'].append({
                    'arn': f'${{{target_resource.arn}}}',
                    'weight': a['weight']
                })
                weight_sum += a['weight']

            if weight_sum != 100:
                raise ValueError(
                    'sum of weights for a rule should be 100'
                    f' given: {weight_sum}'
                )

            lblr_identifier = f'{identifier}-rule-{rule_num+1:02d}'
            lblr_tf_resource = \
                aws_lb_listener_rule(lblr_identifier, **values)

            tf_resources.append(lblr_tf_resource)

        # outputs
        # dns name
        output_name_0_13 = output_prefix + '__dns_name'
        output_value = f'${{{lb_tf_resource.dns_name}}}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        # vpc cidr block
        output_name_0_13 = output_prefix + '__vpc_cidr_block'
        output_value = vpc_cidr_block
        tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def populate_tf_resource_secrets_manager(self, resource, namespace_info):
        account, identifier, common_values, \
            output_prefix, output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        values = {
            "name": identifier
        }

        region = common_values.get('region') or \
            self.default_regions.get(account)
        if self._multiregion_account(account):
            values['provider'] = 'aws.' + region

        aws_secret_resource = aws_secretsmanager_secret(identifier, **values)
        tf_resources.append(aws_secret_resource)

        secret = common_values.get('secret')
        secret_data = self.secret_reader.read_all(secret)

        version_values = {
            "secret_id": '${' + aws_secret_resource.id + '}',
            "secret_string": json.dumps(secret_data, sort_keys=True)
        }

        if self._multiregion_account(account):
            version_values['provider'] = 'aws.' + region

        aws_version_resource = \
            aws_secretsmanager_secret_version(identifier, **version_values)
        tf_resources.append(aws_version_resource)

        # outputs
        output_name_0_13 = output_prefix + '__arn'
        output_value = '${' + aws_version_resource.arn + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        output_name_0_13 = output_prefix + '__version_id'
        output_value = '${' + aws_version_resource.version_id + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def _get_commit_sha(self, repo_info: Mapping) -> str:
        url = repo_info['url']
        ref = repo_info['ref']
        pattern = r'^[0-9a-f]{40}$'
        # get commit_sha from ref
        if re.match(pattern, ref):
            return ref
        # get commit_sha from branch
        elif 'github' in url:
            github = self.init_github()
            repo_name = url.rstrip("/").replace('https://github.com/', '')
            repo = github.get_repo(repo_name)
            commit = repo.get_commit(sha=ref)
            return commit.sha
        elif 'gitlab' in url:
            raise NotImplementedError("dose not support gitlab repo for now")

        return ''

    def _get_asg_image_id(self, image: Mapping,
                          account: str, region: str) -> Tuple[Optional[str], str]:
        """
        AMI ID comes form AWS Api filter result.
        AMI needs to be shared by integration aws-ami-share.
        AMI needs to be taged with a tag_name and
        its value need to be the commit sha comes from upstream repo.
        """
        commit_sha = self._get_commit_sha(image)
        tag_name = image['tag_name']

        # Get the most recent AMI id
        aws_account = self.accounts[account]
        aws = AWSApi(1, [aws_account],
                     settings=self.settings,
                     init_users=False)
        tag = {
            'Key': tag_name,
            'Value': commit_sha
        }
        image_id = aws.get_image_id(account, region, tag)

        return image_id, commit_sha

    def _use_previous_image_id(self, image: dict) -> bool:
        upstream = image.get('upstream')
        if upstream:
            jenkins = self.init_jenkins(upstream['instance'])
            if jenkins.is_job_running(upstream['name']):
                # AMI is being built, use previous known image id
                return True
        return False

    def populate_tf_resource_asg(self, resource: dict,
                                 namespace_info: dict,
                                 existing_secrets: dict) -> None:
        account, identifier, common_values, \
            output_prefix, output_resource_name, annotations = \
            self.init_values(resource, namespace_info)

        tf_resources: List[Any] = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        tags = common_values['tags']
        tags['Name'] = identifier
        # common_values is untyped, so casting is necessary
        region = cast(str, common_values.get('region')) or \
            cast(str, self.default_regions.get(account))

        template_values = {
            "name": identifier,
            "vpc_security_group_ids":
                common_values.get('vpc_security_group_ids'),
            "update_default_version":
                common_values.get('update_default_version'),
            "block_device_mappings":
                common_values.get('block_device_mappings'),
            "tags": tags,
            "tag_specifications": [
                {
                    "resource_type": "instance",
                    "tags": tags
                },
                {
                    "resource_type": "volume",
                    "tags": tags
                }]
        }

        # common_values is untyped, so casting is necessary
        image = cast(dict, common_values.get('image'))
        image_id, commit_sha = \
            self._get_asg_image_id(image, account, region)
        if not image_id:
            if self._use_previous_image_id(image):
                new_commit_sha = commit_sha
                existing_ami = existing_secrets[account][output_prefix]
                image_id = existing_ami['image_id']
                commit_sha = existing_ami['commit_sha']
                logging.warning(
                    f"[{account}] ami for commit {new_commit_sha} "
                    f"not yet available. using ami {image_id} "
                    f"for previous commit {commit_sha}."
                )
            else:
                raise ValueError(f"could not find ami for commit {commit_sha} "
                                 f"in account {account}")
        template_values['image_id'] = image_id

        if self._multiregion_account(account):
            template_values['provider'] = 'aws.' + region

        role_name = common_values.get('iam_role_name')
        if role_name:
            profile_value = {
                "name": identifier,
                "role": role_name
            }
            if self._multiregion_account(account):
                profile_value['provider'] = 'aws.' + region
            profile_resource = \
                aws_iam_instance_profile(identifier, **profile_value)
            tf_resources.append(profile_resource)
            template_values['iam_instance_profile'] = {
                "name": profile_resource.name
            }

        cloudinit_configs = common_values.get('cloudinit_configs')
        if cloudinit_configs:
            vars = {}
            variables = common_values.get('variables')
            if variables:
                vars = json.loads(variables)
            vars.update({'aws_region': region})
            vars.update({'aws_account_id': self.uids.get(account)})
            part = []
            for c in cloudinit_configs:
                raw = self.get_raw_values(c['content'])
                content = orb.process_extracurlyjinja2_template(
                    body=raw['content'], vars=vars)
                # https://www.terraform.io/docs/language/expressions/strings.html#escape-sequences
                content = content.replace("${", "$${")
                content = content.replace("%{", "%%{")
                part.append({
                    "filename": c.get('filename'),
                    "content_type": c.get('content_type'),
                    "content": content
                })
            cloudinit_value = {
                "gzip": True,
                "base64_encode": True,
                "part": part
            }
            cloudinit_data = data.template_cloudinit_config(
                identifier, **cloudinit_value)
            tf_resources.append(cloudinit_data)
            template_values['user_data'] = '${' + cloudinit_data.rendered + '}'
        template_resource = aws_launch_template(identifier, **template_values)
        tf_resources.append(template_resource)

        asg_value = {
            "name": identifier,
            "max_size": common_values.get('max_size'),
            "min_size": common_values.get('min_size'),
            "availability_zones": common_values.get('availability_zones'),
            "capacity_rebalance": common_values.get('capacity_rebalance'),
            "mixed_instances_policy": {
                "instances_distribution": common_values.get(
                    'instances_distribution'),
                "launch_template": {
                    "launch_template_specification": {
                        "launch_template_id":
                            '${' + template_resource.id + '}',
                        "version":
                            '${' + template_resource.latest_version + '}'
                    }
                }
            },
            "instance_refresh": {
                "strategy": "Rolling",
                "preferences":
                    common_values.get('instance_refresh_preferences')
            }
        }
        instance_types = common_values.get('instance_types')
        if instance_types:
            override = [{"instance_type": i} for i in instance_types]
            (asg_value['mixed_instances_policy']
                      ['launch_template']['override']) = override  # type: ignore[assignment,index]
        asg_value['tags'] = [{
            "key": k,
            "value": v,
            "propagate_at_launch": True
        } for k, v in tags.items()]
        asg_resource = aws_autoscaling_group(identifier, **asg_value)
        tf_resources.append(asg_resource)

        # outputs
        output_name_0_13 = output_prefix + '__template_latest_version'
        output_value = '${' + template_resource.latest_version + '}'
        tf_resources.append(Output(output_name_0_13, value=output_value))
        output_name_0_13 = output_prefix + '__image_id'
        output_value = image_id
        tf_resources.append(Output(output_name_0_13, value=output_value))
        output_name_0_13 = output_prefix + '__commit_sha'
        output_value = commit_sha
        tf_resources.append(Output(output_name_0_13, value=output_value))

        self.add_resources(account, tf_resources)

    def populate_tf_resource_route53_zone(self, resource, namespace_info):
        account, identifier, common_values, output_prefix, \
            output_resource_name, annotations = \
            self.init_values(resource, namespace_info)
        tf_resources = []
        self.init_common_outputs(tf_resources, namespace_info, output_prefix,
                                 output_resource_name, annotations)

        # https://www.terraform.io/docs/providers/aws/r/route53_zone.html
        values = {
            'name': common_values['name'],
            'tags': common_values['tags'],
        }
        zone_id = safe_resource_id(identifier)
        zone_tf_resource = aws_route53_zone(zone_id, **values)
        tf_resources.append(zone_tf_resource)

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "route53:Change*",
                        "route53:Create*",
                        "route53:Get*",
                        "route53:List*",
                    ],
                    "Resource":
                        "arn:aws:route53:::hostedzone/" +
                        f"${{{zone_tf_resource.zone_id}}}"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "route53:List*"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": ["tag:GetResources"],
                    "Resource": "*"
                }
            ]
        }

        tf_resources.extend(
            self.get_tf_iam_service_user(
                zone_tf_resource,
                identifier,
                policy,
                common_values['tags'],
                output_prefix,
            )
        )

        self.add_resources(account, tf_resources)
