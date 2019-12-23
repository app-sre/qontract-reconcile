import utils.gql as gql


APP_INTERFACE_SETTINGS_QUERY = """
{
  settings: app_interface_settings_v1 {
    vault
    kubeBinary
    pullRequestGateway
  }
}
"""


def get_app_interface_settings():
    """ Returns App Interface settings """
    gqlapi = gql.get_api()
    settings = gqlapi.query(APP_INTERFACE_SETTINGS_QUERY)['settings']
    if settings:
        # assuming a single settings file for now
        return settings[0]
    return None


GITLAB_INSTANCES_QUERY = """
{
  instances: gitlabinstance_v1 {
    url
    token {
      path
      field
    }
    managedGroups
    projectRequests {
      group
      projects
    }
    sslVerify
  }
}
"""


def get_gitlab_instance():
    """ Returns a single GitLab instance """
    gqlapi = gql.get_api()
    # assuming a single GitLab instance for now
    return gqlapi.query(GITLAB_INSTANCES_QUERY)['instances'][0]


AWS_ACCOUNTS_QUERY = """
{
  accounts: awsaccounts_v1 {
    path
    name
    uid
    resourcesDefaultRegion
    automationToken {
      path
      field
    }
    disable {
      integrations
    }
    deleteKeys
  }
}
"""


def get_aws_accounts():
    """ Returns all AWS accounts """
    gqlapi = gql.get_api()
    return gqlapi.query(AWS_ACCOUNTS_QUERY)['accounts']


CLUSTERS_QUERY = """
{
  clusters: clusters_v1 {
    name
    serverUrl
    managedGroups
    managedClusterRoles
    jumpHost {
      hostname
      knownHosts
      user
      port
      identity {
        path
        field
        format
      }
    }
    ocm {
      name
      url
      accessTokenUrl
      offlineToken {
        path
        field
        format
        version
      }
    }
    automationToken {
      path
      field
      format
    }
    internal
    disable {
      integrations
    }
  }
}
"""


def get_clusters():
    """ Returns all Clusters """
    gqlapi = gql.get_api()
    return gqlapi.query(CLUSTERS_QUERY)['clusters']


NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    managedRoles
    cluster {
      name
      serverUrl
      jumpHost {
          hostname
          knownHosts
          user
          port
          identity {
              path
              field
              format
          }
      }
      automationToken {
        path
        field
        format
      }
      internal
      disable {
        integrations
      }
    }
    openshiftAcme {
      config {
        name
        image
        overrides {
          deploymentName
          roleName
          rolebindingName
          serviceaccountName
          rbacApiVersion
        }
      }
      accountSecret {
        path
        version
      }
    }
    limitRanges {
      name
      limits {
        default {
          cpu
          memory
        }
        defaultRequest {
          cpu
          memory
        }
        max {
          cpu
          memory
        }
        maxLimitRequestRatio {
          cpu
          memory
        }
        min {
          cpu
          memory
        }
        type
      }
    }
  }
}
"""


APPS_QUERY = """
{
  apps: apps_v1 {
    path
    name
    codeComponents {
      url
      resource
    }
  }
}
"""


def get_apps():
    """ Returns all apps along with their codeComponents """
    gqlapi = gql.get_api()
    return gqlapi.query(APPS_QUERY)['apps']


def get_repos(server=''):
    """ Returns all repos defined under codeComponents
    Optional arguments:
    server: url of the server to return. for example: https://github.com
    """
    gqlapi = gql.get_api()
    apps = gqlapi.query(APPS_QUERY)['apps']
    code_components_lists = [a['codeComponents'] for a in apps
                             if a['codeComponents'] is not None]
    code_components = [item for sublist in code_components_lists
                       for item in sublist]
    repos = [c['url'] for c in code_components if c['url'].startswith(server)]

    return repos
