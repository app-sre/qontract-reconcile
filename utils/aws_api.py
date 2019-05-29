import logging
import boto3
import botocore

import utils.vault_client as vault_client

from utils.config import get_config

from multiprocessing.dummy import Pool as ThreadPool


class AWSApi(object):
    """Wrapper around AWS SDK"""

    def __init__(self, thread_pool_size):
        self.thread_pool_size = thread_pool_size
        self.init_sessions()
        self.init_users()
        self.map_resources()

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

    def map_s3_resources(self):
        for account, s in self.sessions.items():
            s3 = s.client('s3')
            buckets = [b['Name'] for b in s3.list_buckets()['Buckets']]
            self.resources[account]['s3'] = buckets
            buckets_without_owner = \
                self.get_resources_without_owner(account, buckets)
            unfiltered_buckets = \
                self.custom_s3_filter(s3, buckets_without_owner)
            self.resources[account]['s3_no_owner'] = unfiltered_buckets

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
        return has_owner

    def custom_s3_filter(self, s3, buckets):
        skip_msg = 'skipping bucket {}, {}'
        unfiltered_buckets = []
        for b in buckets:
            # ignore terraform buckets
            if '-tf-' in b:
                logging.debug(skip_msg.format(b, 'terraform related'))
                continue
            # ignore buckets with special tags
            try:
                special_tags = ['managed_by_integration', 'owner',
                                'aws_gc_hands_off']
                for tag in special_tags:
                    tags = s3.get_bucket_tagging(Bucket=b)['TagSet']
                    value = self.get_tag_value(tags, tag)
                    if value is not None:
                        logging.debug(skip_msg.format(b, tag + '=' + value))
                        continue
                unfiltered_buckets.append(b)
            except Exception as e:
                if 'NoSuchTagSet' in e.message:
                    unfiltered_buckets.append(b)
        return unfiltered_buckets

    def get_tag_value(self, tags, tag):
        value = None
        for t in tags:
            if t['Key'] == tag:
                value = t['Value']
                break
        return value

    def delete_resources_without_owner(self, dry_run):
        for account, s in self.sessions.items():
            s3 = s.resource('s3')
            for b in self.resources[account]['s3_no_owner']:
                logging.info(['delete_resource', 's3', account, b])
                if not dry_run:
                    self.delete_bucket(s3, b)

    def delete_bucket(self, s3, bucket_name):
        bucket = s3.Bucket(bucket_name)
        for key in bucket.objects.all():
            key.delete()
        bucket.delete()
