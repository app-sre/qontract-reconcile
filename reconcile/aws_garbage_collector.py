import logging

from utils.aws_api import AWSApi


def run(dry_run=False, thread_pool_size=10):
    aws = AWSApi(thread_pool_size)
    aws.delete_resources_without_owner(dry_run)
