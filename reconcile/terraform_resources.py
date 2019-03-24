import logging
import sys
import tempfile
import shutil

import utils.gql as gql
import utils.vault_client as vault_client

from utils.config import get_config

from python_terraform import *
from terrascript import Terrascript, provider, terraform, backend
from terrascript.aws.r import aws_s3_bucket

QUERY = """

"""


_working_dir = None


def bootstrap_config():
    ts = Terrascript()
    secret = vault_client.read_all('app-sre/creds/terraform/terraform-aws02')
    ts += provider('aws',
                   access_key=secret['aws_access_key_id'],
                   secret_key=secret['aws_secret_access_key'],
                   version=secret['aws_provider_version'],
                   region=secret['region'])
    b = backend("s3",
                access_key=secret['aws_access_key_id'],
                secret_key=secret['aws_secret_access_key'],
                bucket=secret['bucket'],
                key=secret['key'],
                region=secret['region'])
    ts += terraform(backend=b)

    return ts


def add_resources(ts):
    # fetch desired resources from gql
    # gqlapi = gql.get_api()
    # result = gqlapi.query(QUERY)
    ts.add(aws_s3_bucket('maor-test-bucket', bucket='maor-test-bucket-19wtj4'))


def write_to_tmp_file(ts):
    global _working_dir

    _working_dir = tempfile.mkdtemp()
    with open(_working_dir + '/config.tf', 'w') as f:
        f.write(ts.dump())


def tf_setup():   
    ts = bootstrap_config()
    add_resources(ts)
    write_to_tmp_file(ts)


def check_tf_output(return_code, stdout, stderr):
    for line in stdout.split('\n'):
        if len(line) == 0:
            continue
        logging.debug(line)
    if return_code != 0 and len(stderr) != 0:
        for line in stderr.split('\n'):
            if len(line) == 0:
                continue
            logging.error(stderr)
        tf_cleanup()
        sys.exit(return_code)


def log_diff(stdout):
    for line in stdout.split('\n'):
        if line.startswith('+ aws'):
            line_split = line.replace('+ ', '').split('.')
            logging.info(['create', line_split[0], line_split[1]])
        if line.startswith('- aws'):
            line_split = line.replace('- ', '').split('.')
            logging.info(['destroy', line_split[0], line_split[1]])
        if line.startswith('~ aws'):
            line_split = line.replace('~ ', '').split('.')
            logging.info(['update', line_split[0], line_split[1]])


def tf_init():
    global _working_dir

    tf = Terraform(working_dir=_working_dir)
    return_code, stdout, stderr = tf.init()
    check_tf_output(return_code, stdout, stderr)

    return tf


def tf_plan(tf):
    return_code, stdout, stderr = tf.plan(detailed_exitcode=False)
    check_tf_output(return_code, stdout, stderr)
    log_diff(stdout)


def tf_apply(tf):
    return_code, stdout, stderr = tf.apply(auto_approve=True)
    check_tf_output(return_code, stdout, stderr)


def tf_cleanup():
    global _working_dir

    shutil.rmtree(_working_dir)


def run(dry_run=False):
    global _working_dir

    tf_setup()
    tf = tf_init()
    tf_plan(tf)

    if not dry_run:
        tf_apply(tf)

    tf_cleanup()
