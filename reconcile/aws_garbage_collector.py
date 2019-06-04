from utils.aws_api import AWSApi


def run(dry_run=False, thread_pool_size=10,
        enable_deletion=False, io_dir='throughput/'):
    aws = AWSApi(thread_pool_size)
    if dry_run:
        aws.simulate_deleted_users(io_dir)
    aws.map_resources()
    aws.delete_resources_without_owner(dry_run, enable_deletion)
