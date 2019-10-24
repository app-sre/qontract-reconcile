import utils.gql as gql


GITLAB_INSTANCES_QUERY = """
{
  instances: gitlabinstance_v1 {
    url
    token {
      path
      field
    }
    managedGroups
    sslVerify
  }
}
"""


def get_gitlab_instance():
    gqlapi = gql.get_api()
    # assuming a single GitLab instance for now
    return gqlapi.query(GITLAB_INSTANCES_QUERY)['instances'][0]


AWS_ACCOUNTS_QUERY = """
{
  accounts: awsaccounts_v1 {
    path
    name
    automationToken {
      path
      field
    }
    deleteKeys
  }
}
"""


def get_aws_accounts():
    gqlapi = gql.get_api()
    return gqlapi.query(AWS_ACCOUNTS_QUERY)['accounts']


APPS_QUERY = """
{
  apps: apps_v1 {
    codeComponents {
        url
    }
  }
}
"""


def get_repos(server=''):
    gqlapi = gql.get_api()
    apps = gqlapi.query(APPS_QUERY)['apps']
    code_components_lists = [a['codeComponents'] for a in apps
                             if a['codeComponents'] is not None]
    code_components = [item for sublist in code_components_lists
                       for item in sublist]
    repos = [c['url'] for c in code_components if c['url'].startswith(server)]

    return repos
