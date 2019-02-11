import logging

import reconcile.gql as gql
import utils.ldap_client as ldap_client
import utils.gitlab_client as gitlab_client


USERS_QUERY = """
{
  user {
    path
    redhat_username
  }
}
"""


def run(dry_run=False):
    gqlapi = gql.get_api()
    result = gqlapi.query(USERS_QUERY)

    for user in result['user']:
        username = user['redhat_username']
        path = 'data' + user['path']

        if (ldap_client.user_exists(username)):
            continue
        
        logging.info(['delete_user', username, path])
        
        if dry_run:
            continue

        gitlab_client.create_delete_user_mr(username, path)
    
    return
