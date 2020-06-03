import base64
import json
import logging

import reconcile.queries as queries
import utils.vault_client as vault_client

from utils.aws_api import AWSApi

QONTRACT_INTEGRATION = 'aws-ecr-image-pull-secrets'


def enc_dec(data):
    return base64.b64encode(data.encode('utf-8')).decode('utf-8')


def construct_secret_data(data):
    auth_data = data['authorizationData'][0]
    server = auth_data['proxyEndpoint']
    token = auth_data['authorizationToken']
    data = {
        'auths': {
            server: {
                'username': 'AWS',
                'password': token,
                'email': '',
                'auth': enc_dec(f'AWS:{token}')
            }
        }
    }

    return {'.dockerconfigjson': enc_dec(json.dumps(data))}


def write_output_to_vault(dry_run, vault_path, account, secret_data):
    integration_name = QONTRACT_INTEGRATION
    secret_path = f"{vault_path}/{integration_name}/{account}"
    secret = {'path': secret_path, 'data': secret_data}
    logging.info(['write_secret', secret_path])
    if not dry_run:
        vault_client.write(secret)


def run(dry_run=False, vault_output_path=''):
    accounts = [a for a in queries.get_aws_accounts() if a.get('ecrs')]
    settings = queries.get_app_interface_settings()
    aws = AWSApi(1, accounts, settings=settings)
    tokens = aws.get_ecr_auth_tokens()
    for account, data in tokens.items():
        secret_data = construct_secret_data(data)
        write_output_to_vault(dry_run, vault_output_path,
                              account, secret_data)
