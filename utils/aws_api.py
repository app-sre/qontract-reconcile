import logging
import boto3
import botocore
import json
import os
import time

import utils.threaded as threaded
import utils.vault_client as vault_client

from threading import Lock


class InvalidResourceTypeError(Exception):
    pass


class AWSApi(object):
    """Wrapper around AWS SDK"""

    def __init__(self, thread_pool_size, accounts):
        self.thread_pool_size = thread_pool_size
        self.init_sessions_and_resources(accounts)
        self.init_users()
        self._lock = Lock()
        self.resource_types = \
            ['s3', 'sqs', 'dynamodb', 'rds', 'rds_snapshots']

    def init_sessions_and_resources(self, accounts):
        results = threaded.run(self.get_vault_tf_secrets, accounts,
                               self.thread_pool_size)
        self.sessions = {}
        self.resources = {}
        for account, secret in results:
            access_key = secret['aws_access_key_id']
            secret_key = secret['aws_secret_access_key']
            region_name = secret['region']
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region_name,
            )
            self.sessions[account] = session
            self.resources[account] = {}

    @staticmethod
    def get_vault_tf_secrets(account):
        account_name = account['name']
        automation_token = account['automationToken']
        secret = vault_client.read_all(automation_token)
        return (account_name, secret)

    def init_users(self):
        self.users = {}
        for account, s in self.sessions.items():
            iam = s.client('iam')
            users = [u['UserName'] for u in iam.list_users()['Users']]
            self.users[account] = users

    def simulate_deleted_users(self, io_dir):
        src_integrations = ['terraform_resources', 'terraform_users']
        if not os.path.exists(io_dir):
            return
        for i in src_integrations:
            file_path = os.path.join(io_dir, i + '.json')
            if not os.path.exists(file_path):
                continue
            with open(file_path, 'r') as f:
                deleted_users = json.load(f)
            for deleted_user in deleted_users:
                delete_from_account = deleted_user['account']
                delete_user = deleted_user['user']
                self.users[delete_from_account].remove(delete_user)

    def map_resources(self):
        threaded.run(self.map_resource, self.resource_types,
                     self.thread_pool_size)

    def map_resource(self, resource_type):
        if resource_type == 's3':
            self.map_s3_resources()
        elif resource_type == 'sqs':
            self.map_sqs_resources()
        elif resource_type == 'dynamodb':
            self.map_dynamodb_resources()
        elif resource_type == 'rds':
            self.map_rds_resources()
        elif resource_type == 'rds_snapshots':
            self.map_rds_snapshots()
        else:
            raise InvalidResourceTypeError(resource_type)

    def map_s3_resources(self):
        for account, s in self.sessions.items():
            s3 = s.client('s3')
            buckets_list = s3.list_buckets()
            if 'Buckets' not in buckets_list:
                continue
            buckets = [b['Name'] for b in buckets_list['Buckets']]
            self.set_resouces(account, 's3', buckets)
            buckets_without_owner = \
                self.get_resources_without_owner(account, buckets)
            unfiltered_buckets = \
                self.custom_s3_filter(account, s3, buckets_without_owner)
            self.set_resouces(account, 's3_no_owner', unfiltered_buckets)

    def map_sqs_resources(self):
        for account, s in self.sessions.items():
            sqs = s.client('sqs')
            queues_list = sqs.list_queues()
            if 'QueueUrls' not in queues_list:
                continue
            queues = queues_list['QueueUrls']
            self.set_resouces(account, 'sqs', queues)
            queues_without_owner = \
                self.get_resources_without_owner(account, queues)
            unfiltered_queues = \
                self.custom_sqs_filter(account, sqs, queues_without_owner)
            self.set_resouces(account, 'sqs_no_owner', unfiltered_queues)

    def map_dynamodb_resources(self):
        for account, s in self.sessions.items():
            dynamodb = s.client('dynamodb')
            tables = self.paginate(dynamodb, 'list_tables', 'TableNames')
            self.set_resouces(account, 'dynamodb', tables)
            tables_without_owner = \
                self.get_resources_without_owner(account, tables)
            unfiltered_tables = \
                self.custom_dynamodb_filter(
                    account,
                    s,
                    dynamodb,
                    tables_without_owner
                )
            self.set_resouces(account, 'dynamodb_no_owner', unfiltered_tables)

    def map_rds_resources(self):
        for account, s in self.sessions.items():
            rds = s.client('rds')
            results = \
                self.paginate(rds, 'describe_db_instances', 'DBInstances')
            instances = [t['DBInstanceIdentifier'] for t in results]
            self.set_resouces(account, 'rds', instances)
            instances_without_owner = \
                self.get_resources_without_owner(account, instances)
            unfiltered_instances = \
                self.custom_rds_filter(account, rds, instances_without_owner)
            self.set_resouces(account, 'rds_no_owner', unfiltered_instances)

    def map_rds_snapshots(self):
        self.wait_for_resource('rds')
        for account, s in self.sessions.items():
            rds = s.client('rds')
            results = \
                self.paginate(rds, 'describe_db_snapshots', 'DBSnapshots')
            snapshots = [t['DBSnapshotIdentifier'] for t in results]
            self.set_resouces(account, 'rds_snapshots', snapshots)
            snapshots_without_db = [t['DBSnapshotIdentifier'] for t in results
                                    if t['DBInstanceIdentifier'] not in
                                    self.resources[account]['rds']]
            unfiltered_snapshots = \
                self.custom_rds_snapshot_filter(account, rds,
                                                snapshots_without_db)
            self.set_resouces(account, 'rds_snapshots_no_owner',
                              unfiltered_snapshots)

    def paginate(self, client, method, key):
        """ paginate returns an aggregated list of the specified key
        from all pages returned by executing the client's specified method."""
        paginator = client.get_paginator(method)
        return [values
                for page in paginator.paginate()
                for values in page.get(key, [])]

    def wait_for_resource(self, resource):
        """ wait_for_resource waits until the specified resource type
        is ready for all accounts.
        When we have more resource types then threads,
        this function will need to change to a dependency graph."""
        wait = True
        while wait:
            wait = False
            for account in self.sessions:
                if self.resources[account].get(resource) is None:
                    continue
                wait = True
                time.sleep(2)
                break

    def set_resouces(self, account, key, value):
        with self._lock:
            self.resources[account][key] = value

    def get_resources_without_owner(self, account, resources):
        return [r for r in resources if not self.has_owner(account, r)]

    def has_owner(self, account, resource):
        has_owner = False
        for u in self.users[account]:
            if resource.lower().startswith(u.lower()):
                has_owner = True
                break
            if '://' in resource:
                if resource.split('/')[-1].startswith(u.lower()):
                    has_owner = True
                    break
        return has_owner

    def custom_s3_filter(self, account, s3, buckets):
        type = 's3 bucket'
        unfiltered_buckets = []
        for b in buckets:
            try:
                tags = s3.get_bucket_tagging(Bucket=b)
            except botocore.exceptions.ClientError:
                tags = {}
            if not self.should_filter(account, type, b, tags, 'TagSet'):
                unfiltered_buckets.append(b)

        return unfiltered_buckets

    def custom_sqs_filter(self, account, sqs, queues):
        type = 'sqs queue'
        unfiltered_queues = []
        for q in queues:
            tags = sqs.list_queue_tags(QueueUrl=q)
            if not self.should_filter(account, type, q, tags, 'Tags'):
                unfiltered_queues.append(q)

        return unfiltered_queues

    def custom_dynamodb_filter(self, account, session, dynamodb, tables):
        type = 'dynamodb table'
        dynamodb_resource = session.resource('dynamodb')
        unfiltered_tables = []
        for t in tables:
            table_arn = dynamodb_resource.Table(t).table_arn
            tags = dynamodb.list_tags_of_resource(ResourceArn=table_arn)
            if not self.should_filter(account, type, t, tags, 'Tags'):
                unfiltered_tables.append(t)

        return unfiltered_tables

    def custom_rds_filter(self, account, rds, instances):
        type = 'rds instance'
        unfiltered_instances = []
        for i in instances:
            instance = rds.describe_db_instances(DBInstanceIdentifier=i)
            instance_arn = instance['DBInstances'][0]['DBInstanceArn']
            tags = rds.list_tags_for_resource(ResourceName=instance_arn)
            if not self.should_filter(account, type, i, tags, 'TagList'):
                unfiltered_instances.append(i)

        return unfiltered_instances

    def custom_rds_snapshot_filter(self, account, rds, snapshots):
        type = 'rds snapshots'
        unfiltered_snapshots = []
        for s in snapshots:
            snapshot = rds.describe_db_snapshots(DBSnapshotIdentifier=s)
            snapshot_arn = snapshot['DBSnapshots'][0]['DBSnapshotArn']
            tags = rds.list_tags_for_resource(ResourceName=snapshot_arn)
            if not self.should_filter(account, type, s, tags, 'TagList'):
                unfiltered_snapshots.append(s)

        return unfiltered_snapshots

    def should_filter(self, account, resource_type,
                      resource_name, resource_tags, tags_key):
        if self.resource_has_special_name(account, resource_type,
                                          resource_name):
            return True
        if tags_key in resource_tags:
            tags = resource_tags[tags_key]
            if self.resource_has_special_tags(account, resource_type,
                                              resource_name, tags):
                return True

        return False

    def resource_has_special_name(self, account, type, resource):
        skip_msg = '[{}] skipping {} '.format(account, type) + \
            '({} related) {}'

        ignore_names = {
            'production': ['prod'],
            'stage': ['stage', 'staging'],
            'terraform': ['terraform', '-tf-'],
        }

        for msg, tags in ignore_names.items():
            for tag in tags:
                if tag.lower() in resource.lower():
                    logging.debug(skip_msg.format(msg, resource))
                    return True

        return False

    def resource_has_special_tags(self, account, type, resource, tags):
        skip_msg = '[{}] skipping {} '.format(account, type) + \
            '({}={}) {}'

        ignore_tags = {
            'ENV': ['prod', 'stage', 'staging'],
            'environment': ['prod', 'stage', 'staging'],
            'owner': ['app-sre'],
            'managed_by_integration': [
                'terraform_resources',
                'terraform_users'
            ],
            'aws_gc_hands_off': ['true'],
        }

        for tag, ignore_values in ignore_tags.items():
            for ignore_value in ignore_values:
                value = self.get_tag_value(tags, tag)
                if ignore_value.lower() in value.lower():
                    logging.debug(skip_msg.format(tag, value, resource))
                    return True

        return False

    def get_tag_value(self, tags, tag):
        if isinstance(tags, dict):
            return tags.get(tag, '')
        elif isinstance(tags, list):
            for t in tags:
                if t['Key'] == tag:
                    return t['Value']

        return ''

    def delete_resources_without_owner(self, dry_run, enable_deletion):
        warning_message = '\'delete\' action is not enabled. ' + \
                          'Please run the integration manually ' + \
                          'with the \'--enable-deletion\' flag.'

        for account, s in self.sessions.items():
            for rt in self.resource_types:
                for r in self.resources[account].get(rt + '_no_owner', []):
                    logging.info(['delete_resource', account, rt, r])
                    if not dry_run:
                        if enable_deletion:
                            self.delete_resource(s, rt, r)
                        else:
                            logging.warning(warning_message)

    def delete_resource(self, session, resource_type, resource_name):
        if resource_type == 's3':
            resource = session.resource(resource_type)
            self.delete_bucket(resource, resource_name)
        elif resource_type == 'sqs':
            client = session.client(resource_type)
            self.delete_queue(client, resource_name)
        elif resource_type == 'dynamodb':
            resource = session.resource(resource_type)
            self.delete_table(resource, resource_name)
        elif resource_type == 'rds':
            client = session.client(resource_type)
            self.delete_instance(client, resource_name)
        elif resource_type == 'rds_snapshots':
            client = session.client(resource_type)
            self.delete_snapshot(client, resource_name)
        else:
            raise InvalidResourceTypeError(resource_type)

    def delete_bucket(self, s3, bucket_name):
        bucket = s3.Bucket(bucket_name)
        for key in bucket.objects.all():
            key.delete()
        bucket.delete()

    def delete_queue(self, sqs, queue_url):
        sqs.delete_queue(QueueUrl=queue_url)

    def delete_table(self, dynamodb, table_name):
        table = dynamodb.Table(table_name)
        table.delete()

    def delete_instance(self, rds, instance_name):
        rds.delete_db_instance(
            DBInstanceIdentifier=instance_name,
            SkipFinalSnapshot=True,
            DeleteAutomatedBackups=True
        )

    def delete_snapshot(self, rds, snapshot_identifier):
        rds.delete_db_snapshot(
            DBSnapshotIdentifier=snapshot_identifier
        )

    def delete_keys(self, dry_run, keys_to_delete):
        users_keys = self.get_users_keys()
        for account, s in self.sessions.items():
            iam = s.client('iam')
            keys = keys_to_delete.get(account, [])
            for key in keys:
                user = [user for user, user_keys
                        in users_keys[account].items()
                        if key in user_keys]
                if not user:
                    continue
                # unpack single item from sequence
                # since only a single user can have a given key
                [user] = user

                logging.info(['delete_key', account, user, key])

                if not dry_run:
                    iam.delete_access_key(
                        UserName=user,
                        AccessKeyId=key
                    )

    def get_users_keys(self):
        users_keys = {}
        for account, s in self.sessions.items():
            iam = s.client('iam')
            users_keys[account] = {user: self.get_user_keys(iam, user)
                                   for user in self.users[account]}

        return users_keys

    def get_user_keys(self, iam, user):
        key_list = iam.list_access_keys(UserName=user)['AccessKeyMetadata']
        return [uk['AccessKeyId'] for uk in key_list]

    def get_support_cases(self):
        self.support_cases = {}
        for account, s in self.sessions.items():
            try:
                support = s.client('support')
                support_cases = support.describe_cases(
                    includeResolvedCases=True,
                    includeCommunications=True
                )['cases']
                self.support_cases[account] = support_cases
            except Exception:
                msg = '[{}] error getting support cases, check support level'
                logging.error(msg.format(account))

        return self.support_cases
