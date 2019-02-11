import logging

import reconcile.gql as gql
import utils.ldap_client as ldap_client

from reconcile.aggregated_list import (AggregatedList,
                                       AggregatedDiffRunner)

USERS_QUERY = """
{
  user {
    path
    redhat_username
  }
}
"""

def remove_user_mr(path):
    # send merge request to remove user from app-interface repo
    # 
    # we should add the the path to the repo as a conf option in config.toml.
    # the MR should follow a naming convention. The first would be to check 
    # if the MR already exists before opening a new one... this has to be 
    # idempotent

    pass


def run(dry_run=False):
    gqlapi = gql.get_api()
    result = gqlapi.query(USERS_QUERY)

    for user in result['user']:
        username = user['redhat_username']
        path = user['path']

        if (ldap_client.user_exists(username)):
            continue
        
        logging.info(['delete_user', username, path])
        
        if dry_run:
            continue

        remove_user_mr(path)
    
    return
