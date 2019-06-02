import logging
import boto3

import utils.vault_client as vault_client

from utils.config import get_config

from multiprocessing.dummy import Pool as ThreadPool


class AWSApi(object):
    """Wrapper around AWS SDK"""

    def __init__(self, thread_pool_size):
        self.thread_pool_size = thread_pool_size
        self.init_sessions()
        self.init_users()

    def init_sessions(self):
        config = get_config()
        self.accounts = config['terraform'].items()

        vault_specs = self.init_vault_tf_secret_specs()
        pool = ThreadPool(self.thread_pool_size)
        results = pool.map(self.get_vault_tf_secrets, vault_specs)

        self.sessions = {}
        for account, secret in results:
            access_key = secret['aws_access_key_id']
            secret_key = secret['aws_secret_access_key']
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            self.sessions[account] = session

    def init_vault_tf_secret_specs(self):
        vault_specs = []
        for account, data in self.accounts:
            init_spec = {'account': account,
                         'data': data}
            vault_specs.append(init_spec)
        return vault_specs

    def get_vault_tf_secrets(self, init_spec):
        account = init_spec['account']
        data = init_spec['data']
        secrets_path = data['secrets_path']
        secret = vault_client.read_all(secrets_path + '/config')
        return (account, secret)

    def init_users(self):
        self.users = {}
        for account, s in self.sessions.items():
            iam = s.client('iam')
            users = [u['UserName'] for u in iam.list_users()['Users']]
            self.users[account] = users

    def map_resources(self):
        self.resources = {}
        for account, _ in self.accounts:
            self.resources[account] = {}

        self.map_s3_resources()
        self.map_sqs_resources()
        self.map_dynamodb_resources()
        self.map_rds_resources()

    def map_s3_resources(self):
        for account, s in self.sessions.items():
            s3 = s.client('s3')
            buckets_list = s3.list_buckets()
            if 'Buckets' not in buckets_list:
                continue
            buckets = [b['Name'] for b in buckets_list['Buckets']]
            self.resources[account]['s3'] = buckets
            buckets_without_owner = \
                self.get_resources_without_owner(account, buckets)
            unfiltered_buckets = \
                self.custom_s3_filter(account, s3, buckets_without_owner)
            self.resources[account]['s3_no_owner'] = unfiltered_buckets

    def map_sqs_resources(self):
        for account, s in self.sessions.items():
            sqs = s.client('sqs')
            queues_list = sqs.list_queues()
            if 'QueueUrls' not in queues_list:
                continue
            queues = queues_list['QueueUrls']
            self.resources[account]['sqs'] = queues
            queues_without_owner = \
                self.get_resources_without_owner(account, queues)
            unfiltered_queues = \
                self.custom_sqs_filter(account, sqs, queues_without_owner)
            self.resources[account]['sqs_no_owner'] = unfiltered_queues

    def map_dynamodb_resources(self):
        for account, s in self.sessions.items():
            dynamodb = s.client('dynamodb')
            tables_list = dynamodb.list_tables()
            if 'TableNames' not in tables_list:
                continue
            tables = tables_list['TableNames']
            self.resources[account]['dynamodb'] = tables
            tables_without_owner = \
                self.get_resources_without_owner(account, tables)
            unfiltered_tables = \
                self.custom_dynamodb_filter(
                    account,
                    s,
                    dynamodb,
                    tables_without_owner
                )
            self.resources[account]['dynamodb_no_owner'] = unfiltered_tables

    def map_rds_resources(self):
        for account, s in self.sessions.items():
            rds = s.client('rds')
            instances_list = rds.describe_db_instances()
            if 'DBInstances' not in instances_list:
                continue
            instances = [t['DBInstanceIdentifier']
                         for t in instances_list['DBInstances']]
            self.resources[account]['rds'] = instances
            instances_without_owner = \
                self.get_resources_without_owner(account, instances)
            unfiltered_instances = \
                self.custom_rds_filter(account, rds, instances_without_owner)
            self.resources[account]['rds_no_owner'] = unfiltered_instances

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
            tags = s3.get_bucket_tagging(Bucket=b)
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
                if tag in resource.lower():
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
            'managed_by_integration': [''],
            'aws_gc_hands_off': [''],
        }

        for tag, ignore_values in ignore_tags.items():
            for ignore_value in ignore_values:
                value = self.get_tag_value(tags, tag)
                if ignore_value in value:
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
        else:
            return ''

    def delete_resources_without_owner(self, dry_run, enable_deletion):
        warning_message = '\'delete\' action is not enabled. ' + \
                          'Please run the integration manually ' + \
                          'with the \'--enable-deletion\' flag.'

        resource_types = ['s3', 'sqs', 'dynamodb', 'rds']
        for account, s in self.sessions.items():
            for rt in resource_types:
                for r in self.resources[account].get(rt + '_no_owner', []):
                    logging.info(['delete_resource', rt, account, r])
                    if not dry_run:
                        if enable_deletion:
                            self.delete_resource(s, r)
                        else:
                            logging.warning(warning_message)

    def delete_resource(self, session, resource_type, resource_name):
        if resource_type == 's3':
            resource = session.resource(resource_type)
            self.delete_bucket(resource, resource_name)
        elif type == 'sqs':
            client = session.client(resource_type)
            self.delete_queue(client, resource_name)
        elif type == 'dynamodb':
            resource = session.resource(resource_type)
            self.delete_table(resource, resource_name)
        elif type == 'rds':
            client = session.client(resource_type)
            self.delete_instance(client, resource_name)
        else:
            raise Exception('invalid resource type: ' + resource_type)

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
