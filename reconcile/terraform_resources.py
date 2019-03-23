import logging

import utils.gql as gql

from utils.config import get_config

from terrascript import Terrascript, provider, terraform, backend
from terrascript.aws.r import aws_instance

QUERY = """

"""



_working_dir = None

def func(ts):
    ts.add(aws_instance('example', ami='ami-2757f631', instance_type='t2.micro'))


def setup_tf_working_dir():
    # fetch terraform secret from vault
    # fetch desired resources from gql
    # create temp directory
    # construct tf file(s)
    # _working_dir = temp_dir

    ts = Terrascript()

    b = backend("s3",
                bucket="dtsd-tf-backend-aws02",
                key="qontract-reconcile.tfstate",
                region="us-east-1")

    ts += terraform(backend=b)

    # Add a provider (+= syntax)
    ts += provider('aws', access_key='ACCESS_KEY_HERE',
                   secret_key='SECRET_KEY_HERE', region='us-east-1')

    # Add an AWS EC2 instance (add() syntax).
    func(ts)

    # Print the JSON-style configuration to stdout.
    print(ts.dump())

    # gqlapi = gql.get_api()
    # result = gqlapi.query(QUERY)
    pass


def remove_working_dir():
    pass


def tf_init():
    pass


def tf_plan():
    pass


def tf_apply():
    pass


def run(dry_run=False):

    setup_tf_working_dir()
    tf_init()
    tf_plan()

    if not dry_run:
        tf_apply()

    remove_working_dir()
