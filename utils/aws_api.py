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
        resources_without_owner = []
        for r in resources:
            if self.has_owner(account, r):
                continue
            resources_without_owner.append(r)
        return resources_without_owner

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
            if self.resource_has_special_name(account, type, b):
                continue
            # ignore buckets with special tags
            try:
                tags = s3.get_bucket_tagging(Bucket=b)['TagSet']
                if self.resource_has_special_tags(account, type, b, tags):
                    continue
                unfiltered_buckets.append(b)
            except Exception as e:
                if 'NoSuchTagSet' in e.message:
                    unfiltered_buckets.append(b)
        return unfiltered_buckets

    def custom_sqs_filter(self, account, sqs, queues):
        type = 'sqs queue'
        unfiltered_queues = []
        for q in queues:
            if self.resource_has_special_name(account, type, q):
                continue
            # ignore queues with special tags
            try:
                tags = sqs.list_queue_tags(QueueUrl=q)['Tags']
                if self.resource_has_special_tags(account, type, q, tags):
                    continue
                unfiltered_queues.append(q)
            except KeyError as e:
                if 'Tags' in e.message:
                    unfiltered_queues.append(q)
        return unfiltered_queues

    def custom_dynamodb_filter(self, account, session, dynamodb, tables):
        type = 'dynamodb table'
        dynamodb_resource = session.resource('dynamodb')
        unfiltered_tables = []
        for t in tables:
            if self.resource_has_special_name(account, type, t):
                continue
            # ignore queues with special tags
            try:
                table_arn = dynamodb_resource.Table(t).table_arn
                tags = dynamodb.list_tags_of_resource(
                    ResourceArn=table_arn)['Tags']
                if self.resource_has_special_tags(account, type, t, tags):
                    continue
                unfiltered_tables.append(t)
            except KeyError as e:
                if 'Tags' in e.message:
                    unfiltered_tables.append(t)
        return unfiltered_tables

    def custom_rds_filter(self, account, rds, instances):
        type = 'rds instance'
        unfiltered_instances = []
        for i in instances:
            if self.resource_has_special_name(account, type, i):
                continue
            # ignore queues with special tags
            try:
                instance = rds.describe_db_instances(DBInstanceIdentifier=i)
                instance_arn = instance['DBInstances'][0]['DBInstanceArn']
                tags = rds.list_tags_for_resource(
                    ResourceName=instance_arn)['TagList']
                if self.resource_has_special_tags(account, type, i, tags):
                    continue
                unfiltered_instances.append(i)
            except KeyError as e:
                print(i)
                print(instance)
                print(e.message)
                if 'TagList' in e.message:
                    unfiltered_instances.append(i)
        return unfiltered_instances

    def resource_has_special_name(self, account, type, resource):
        skip_msg = '[{}] skipping {} '.format(account, type) + \
            '({}) {}'
        # ignore stage/prod buckets - just for safety
        if 'prod' in resource.lower():
            logging.debug(skip_msg.format('production related', resource))
            return True
        if 'stag' in resource.lower():
            logging.debug(skip_msg.format('stage related', resource))
            return True
        # ignore terraform buckets
        if 'terraform' in resource.lower():
            logging.debug(skip_msg.format('terraform related', resource))
            return True
        if '-tf-' in resource.lower():
            logging.debug(skip_msg.format('terraform related', resource))
            return True

        return False

    def resource_has_special_tags(self, account, type, resource, tags):
        skip_msg = '[{}] skipping {} '.format(account, type) + \
            '({}={}) {}'
        tag = 'ENV'
        value = self.get_tag_value(tags, tag)
        if 'prod' in value.lower():
            logging.debug(skip_msg.format(tag, value, resource))
            return True
        if 'stag' in value.lower():
            logging.debug(skip_msg.format(tag, value, resource))
            return True
        tag = 'environment'
        value = self.get_tag_value(tags, tag)
        if 'prod' in value.lower():
            logging.debug(skip_msg.format(tag, value, resource))
            return True
        if 'stag' in value.lower():
            logging.debug(skip_msg.format(tag, value, resource))
            return True
        tag = 'managed_by_integration'
        value = self.get_tag_value(tags, tag)
        if value:
            logging.debug(skip_msg.format(tag, value, resource))
            return True
        tag = 'owner'
        value = self.get_tag_value(tags, tag)
        if 'app-sre' in value:
            logging.debug(skip_msg.format(tag, value, resource))
            return True
        tag = 'aws_gc_hands_off'
        value = self.get_tag_value(tags, tag)
        if value:
            logging.debug(skip_msg.format(tag, value, resource))
            return True

        return False

    def get_tag_value(self, tags, tag):
        # tags may be represented as either a dict or a struct.
        # we try to treat tags as a dict, and if we get an attribute error,
        # we treat it as a struct.
        value = ''
        try:
            for k, v in tags.items():
                if k == tag:
                    value = v
                    break
            return value
        except AttributeError:
            pass

        for t in tags:
            if t['Key'] == tag:
                value = t['Value']
                break
        return value

    def delete_resources_without_owner(self, dry_run, enable_deletion):
        warning_message = '\'delete\' action is not enabled. ' + \
                          'Please run the integration manually ' + \
                          'with the \'--enable-deletion\' flag.'
        for account, s in self.sessions.items():
            if 's3_no_owner' in self.resources[account]:
                s3 = s.resource('s3')
                for b in self.resources[account]['s3_no_owner']:
                    logging.info(['delete_resource', 's3', account, b])
                    if not dry_run:
                        if enable_deletion:
                            self.delete_bucket(s3, b)
                        else:
                            logging.warning(warning_message)

            if 'sqs_no_owner' in self.resources[account]:
                sqs = s.client('sqs')
                for q in self.resources[account]['sqs_no_owner']:
                    q_name = q.split('/')[-1]
                    logging.info(['delete_resource', 'sqs', account, q_name])
                    if not dry_run:
                        if enable_deletion:
                            self.delete_queue(sqs, q)
                        else:
                            logging.warning(warning_message)

            if 'dynamodb_no_owner' in self.resources[account]:
                dynamodb = s.resource('dynamodb')
                for t in self.resources[account]['dynamodb_no_owner']:
                    logging.info(['delete_resource', 'dynamodb', account, t])
                    if not dry_run:
                        if enable_deletion:
                            self.delete_table(dynamodb, t)
                        else:
                            logging.warning(warning_message)

            if 'rds_no_owner' in self.resources[account]:
                rds = s.client('rds')
                for i in self.resources[account]['rds_no_owner']:
                    logging.info(['delete_resource', 'rds', account, i])
                    if not dry_run:
                        if enable_deletion:
                            self.delete_instance(rds, i)
                        else:
                            logging.warning(warning_message)

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
