import utils.gql as gql


APP_INTERFACE_SETTINGS_QUERY = """
{
  settings: app_interface_settings_v1 {
    vault
    kubeBinary
    pullRequestGateway
    dependencies {
      type
      services {
        name
      }
    }
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


APP_INTERFACE_EMAILS_QUERY = """
{
  emails: app_interface_emails_v1 {
    name
    subject
    to {
      aliases
      services {
        serviceOwners {
          email
        }
      }
      clusters {
        name
      }
      namespaces {
        name
      }
      aws_accounts {
        accountOwners {
          email
        }
      }
      roles {
        users {
          org_username
        }
      }
      users {
        org_username
      }
    }
    body
  }
}
"""


def get_app_interface_emails():
    """ Returns Email resources defined in app-interface """
    gqlapi = gql.get_api()
    return gqlapi.query(APP_INTERFACE_EMAILS_QUERY)['emails']


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
    consoleUrl
    resourcesDefaultRegion
    supportedDeploymentRegions
    accountOwners {
      name
      email
    }
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
    consoleUrl
    kibanaUrl
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
      accessTokenClientId
      accessTokenUrl
      offlineToken {
        path
        field
        format
        version
      }
    }
    awsInfrastructureAccess {
      awsGroup {
        account {
          uid
          terraformUsername
        }
        roles {
          users {
            org_username
          }
        }
      }
      accessLevel
    }
    spec {
      provider
      region
      major_version
      multi_az
      nodes
      instance_type
      storage
      load_balancers
    }
    network {
      vpc
      service
      pod
    }
    peering {
      vpc_id
      connections {
        name
        vpc {
          account {
            name
            uid
            terraformUsername
          }
          vpc_id
          cidr_block
          region
        }
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
    app {
      name
    }
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
    managedResourceNames {
      resource
      resourceNames
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
    openshiftServiceAccountTokens {
      namespace {
        name
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
        }
      }
      serviceAccountName
    }
  }
}
"""


def get_namespaces():
    """ Returns all Namespaces """
    gqlapi = gql.get_api()
    return gqlapi.query(NAMESPACES_QUERY)['namespaces']


APPS_QUERY = """
{
  apps: apps_v1 {
    path
    name
    serviceOwners {
      name
      email
    }
    codeComponents {
      url
      resource
      gitlabRepoOwners
      gitlabHousekeeping {
        enabled
        rebase
      }
      jira {
        serverUrl
        token {
          path
        }
      }
    }
  }
}
"""


def get_apps():
    """ Returns all Apps. """
    gqlapi = gql.get_api()
    return gqlapi.query(APPS_QUERY)['apps']


def get_code_components():
    """ Returns code components from all apps. """
    apps = get_apps()
    code_components_lists = [a['codeComponents'] for a in apps
                             if a['codeComponents'] is not None]
    code_components = [item for sublist in code_components_lists
                       for item in sublist]
    return code_components


def get_repos(server=''):
    """ Returns all repos defined under codeComponents
    Optional arguments:
    server: url of the server to return. for example: https://github.com
    """
    code_components = get_code_components()
    repos = [c['url'] for c in code_components if c['url'].startswith(server)]

    return repos


def get_repos_gitlab_owner(server=''):
    """ Returns all repos defined under codeComponents that have gitlabOwner
    enabled.
    Optional arguments:
    server: url of the server to return. for example: https://github.com
    """
    code_components = get_code_components()
    return [c['url'] for c in code_components
            if c['url'].startswith(server) and
            c['gitlabRepoOwners']]


def get_repos_gitlab_housekeeping(server=''):
    """ Returns all repos defined under codeComponents that have
    gitlabHousekeeping enabled.
    Optional arguments:
    server: url of the server to return. for example: https://github.com
    """
    code_components = get_code_components()
    return [{'url': c['url'],
             'enable_rebase': c['gitlabHousekeeping']['rebase']}
            for c in code_components
            if c['url'].startswith(server) and
            c['gitlabHousekeeping'] and
            c['gitlabHousekeeping']['enabled']]


def get_repos_gitlab_jira(server=''):
    code_components = get_code_components()
    return [{'url': c['url'], 'jira': c['jira']}
            for c in code_components
            if c['url'].startswith(server)
            and c.get('jira')]


USERS_QUERY = """
{
  users: users_v1 {
    path
    name
    org_username
    github_username
    slack_username
    pagerduty_name
  }
}
"""


ROLES_QUERY = """
{
  users: users_v1 {
    name
    org_username
    labels
    roles {
      name
      path
      permissions {
        name
        path
        service
        ... on PermissionGithubOrgTeam_v1 {
          org
          team
        }
        ... on PermissionQuayOrgTeam_v1 {
          org
          team
        }
      } access {
        cluster {
          name
          path
        }
        clusterRole
        namespace {
          name
        }
        role
      } aws_groups {
        name
        path
        account {
          name
        }
        policies
      } owned_saas_files {
        name
      }
    }
  }
}
"""


def get_roles():
    gqlapi = gql.get_api()
    return gqlapi.query(ROLES_QUERY)['users']


def get_users():
    """ Returnes all Users. """
    gqlapi = gql.get_api()
    return gqlapi.query(USERS_QUERY)['users']


BOTS_QUERY = """
{
  bots: bots_v1 {
    path
    name
    org_username
    github_username
    openshift_serviceaccount
  }
}
"""


def get_bots():
    """ Returnes all Bots. """
    gqlapi = gql.get_api()
    return gqlapi.query(BOTS_QUERY)['bots']


APP_INTERFACE_SQL_QUERIES_QUERY = """
{
  sql_queries: app_interface_sql_queries_v1 {
    name
    namespace
    {
      name
      managedTerraformResources
      terraformResources
      {
        provider
        ... on NamespaceTerraformResourceRDS_v1
        {
          identifier
          output_resource_name
          defaults
        }
      }
      cluster
      {
        name
        serverUrl
        automationToken
        {
          path
          field
          format
        }
        internal
      }
    }
    identifier
    overrides
    {
      db_host
      db_port
      db_name
      db_user
      db_password
    }
    output
    query
  }
}
"""


def get_app_interface_sql_queries():
    """ Returns SqlQuery resources defined in app-interface """
    gqlapi = gql.get_api()
    return gqlapi.query(APP_INTERFACE_SQL_QUERIES_QUERY)['sql_queries']


SAAS_FILES_QUERY = """
{
  saas_files: saas_files_v1 {
    path
    name
    app {
      name
    }
    slack {
      workspace {
        name
        integrations {
          name
          token {
            path
            field
          }
          channel
          icon_emoji
          username
        }
      }
      channel
    }
    managedResourceTypes
    authentication {
      code {
        path
        field
      }
      image {
        path
      }
    }
    resourceTemplates {
      name
      url
      path
      hash_length
      parameters
      targets {
        namespace {
          name
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
        }
        hash
        notify
        parameters
      }
    }
    roles {
      users {
        org_username
      }
    }
  }
}
"""


def get_saas_files():
    """ Returns SaasFile resources defined in app-interface """
    gqlapi = gql.get_api()
    return gqlapi.query(SAAS_FILES_QUERY)['saas_files']


PERFORMANCE_PARAMETERS_QUERY = """
{
  performance_parameters_v1 {
    labels
    name
    component
    prometheusLabels
    namespace {
      name
      cluster {
        observabilityNamespace {
          name
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
            disable {
              integrations
            }
          }
        }
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
    }
    SLIRecordingRules {
      name
      kind
      metric
      percentile
      selectors
      httpStatusLabel
    }
    volume {
      name
      threshold
      rules
      additionalLabels
    }
    availability {
      name
      additionalLabels
      rules {
        latency
        errors
      }
    }
    latency {
      name
      threshold
      rules
      additionalLabels
    }
    errors {
      name
      target
      rules
      additionalLabels
    }
    rawRecordingRules {
      record
      expr
      labels
    }
  }
}
"""

def get_performance_parameters():
    """ Returns performance parameters resources defined in app-interface """
    gqlapi = gql.get_api()
    return gqlapi.query(
        PERFORMANCE_PARAMETERS_QUERY)['performance_parameters_v1']
