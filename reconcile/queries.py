import utils.gql as gql


APP_INTERFACE_SETTINGS_QUERY = """
{
  settings: app_interface_settings_v1 {
    vault
    kubeBinary
    pullRequestGateway
    saasDeployJobTemplate
    hashLength
    dependencies {
      type
      services {
        name
      }
    }
    credentials {
      name
      secret {
        path
        field
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


CREDENTIALS_REQUESTS_QUERY = """
{
  credentials_requests: credentials_requests_v1 {
    name
    description
    user {
      org_username
      public_gpg_key
    }
    credentials
  }
}
"""


def get_credentials_requests():
    """ Returns Credentials Requests resources defined in app-interface """
    gqlapi = gql.get_api()
    return gqlapi.query(CREDENTIALS_REQUESTS_QUERY)['credentials_requests']


JENKINS_INSTANCES_QUERY = """
{
  instances: jenkins_instances_v1 {
    name
    serverUrl
    token {
      path
      field
    }
    previousUrls
    plugins
  }
}
"""


def get_jenkins_instances():
    """ Returns a list of Jenkins instances """
    gqlapi = gql.get_api()
    return gqlapi.query(JENKINS_INSTANCES_QUERY)['instances']


def get_jenkins_instances_previous_urls():
    instances = get_jenkins_instances()
    all_previous_urls = []
    for instance in instances:
        previous_urls = instance.get('previousUrls')
        if previous_urls:
            all_previous_urls.extend(previous_urls)
    return all_previous_urls


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


GITHUB_INSTANCE_QUERY = """
{
  instances: githuborg_v1 {
    url
    token {
      path
      field
    }
  }
}
"""


def get_github_instance():
    """ Returns a single Github instance """
    gqlapi = gql.get_api()
    instances = gqlapi.query(GITHUB_INSTANCE_QUERY)['instances']
    for instance in instances:
        if instance['url'] == "https://github.com/app-sre":
            return instance


GITHUB_ORGS_QUERY = """
{
  orgs: githuborg_v1 {
    name
    two_factor_authentication
    token {
      path
      field
    }
  }
}
"""


def get_github_orgs():
    """ Returns all GitHub orgs """
    gqlapi = gql.get_api()
    return gqlapi.query(GITHUB_ORGS_QUERY)['orgs']


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
    garbageCollection
    disable {
      integrations
    }
    deleteKeys
    premiumSupport
    ecrs {
      region
    }
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
    auth {
      service
      org
      team
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
          name
          uid
          terraformUsername
          automationToken {
            path
            field
          }
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
      connections {
        name
        provider
        ... on ClusterPeeringConnectionAccount_v1 {
          vpc {
            account {
              name
              uid
              terraformUsername
              automationToken {
                path
                field
              }
            }
            vpc_id
            cidr_block
            region
          }
        }
        ... on ClusterPeeringConnectionClusterRequester_v1 {
          cluster {
            name
            network {
              vpc
            }
            spec {
              region
            }
            awsInfrastructureAccess {
              awsGroup {
                account {
                  name
                  uid
                  terraformUsername
                  automationToken {
                    path
                    field
                  }
                }
              }
              accessLevel
            }
            peering {
              connections {
                name
                provider
                ... on ClusterPeeringConnectionClusterAccepter_v1 {
                  name
                  cluster {
                    name
                  }
                }
              }
            }
          }
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
    quota {
      quotas {
        name
        resources {
          limits {
            cpu
            memory
          }
          requests {
            cpu
            memory
          }
        }
        scopes
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


PRODUCTS_QUERY = """
{
  products: products_v1 {
    path
    name
    description
    environments {
      name
      description
    }
  }
}
"""


def get_products():
    """ Returns all Products """
    gqlapi = gql.get_api()
    return gqlapi.query(PRODUCTS_QUERY)['products']


ENVIRONMENTS_QUERY = """
{
  environments: environments_v1 {
    path
    name
    description
    product {
      name
    }
    namespaces {
      name
      app {
        name
      }
      cluster {
        name
      }
    }
  }
}
"""


def get_environments():
    """ Returns all Products """
    gqlapi = gql.get_api()
    return gqlapi.query(ENVIRONMENTS_QUERY)['environments']


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
        days_interval
        limit
        enable_closing
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
             'housekeeping': c['gitlabHousekeeping']}
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
    public_gpg_key
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
    instance {
      name
      serverUrl
      token {
        path
        field
      }
      deleteMethod
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
    imagePatterns
    authentication {
      code {
        path
        field
      }
      image {
        path
      }
    }
    parameters
    resourceTemplates {
      name
      url
      path
      hash_length
      parameters
      targets {
        namespace {
          name
          environment {
            name
            parameters
          }
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
        }
        ref
        parameters
        upstream
        disable
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


def get_saas_files(saas_file_name=None, env_name=None, app_name=None):
    """ Returns SaasFile resources defined in app-interface """
    gqlapi = gql.get_api()
    saas_files = gqlapi.query(SAAS_FILES_QUERY)['saas_files']

    if saas_file_name is None and env_name is None and app_name is None:
        return saas_files
    if saas_file_name == '' or env_name == '' or app_name == '':
        return []

    for saas_file in saas_files[:]:
        if saas_file_name:
            if saas_file['name'] != saas_file_name:
                saas_files.remove(saas_file)
                continue
        if env_name:
            resource_templates = saas_file['resourceTemplates']
            for rt in resource_templates[:]:
                targets = rt['targets']
                for target in targets[:]:
                    namespace = target['namespace']
                    environment = namespace['environment']
                    if environment['name'] != env_name:
                        targets.remove(target)
                if not targets:
                    resource_templates.remove(rt)
            if not resource_templates:
                saas_files.remove(saas_file)
                continue
        if app_name:
            if saas_file['app']['name'] != app_name:
                saas_files.remove(saas_file)
                continue

    return saas_files


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
      target
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
    rawAlerting {
      alert
      expr
      for
      labels
      annotations {
        message
        runbook
        dashboard
        link_url
      }
    }
  }
}
"""


def get_performance_parameters():
    """ Returns performance parameters resources defined in app-interface """
    gqlapi = gql.get_api()
    return gqlapi.query(
        PERFORMANCE_PARAMETERS_QUERY)['performance_parameters_v1']
