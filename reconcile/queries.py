import logging
import itertools

from textwrap import indent

from jinja2 import Template

import reconcile.utils.gql as gql


APP_INTERFACE_SETTINGS_QUERY = """
{
  settings: app_interface_settings_v1 {
    vault
    kubeBinary
    mergeRequestGateway
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
    sqlQuery {
      imageRepository
      pullSecret {
        path
        version
        labels
        annotations
        type
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


def get_integrations():
    gqlapi = gql.get_api()
    return gqlapi.query(gql.INTEGRATIONS_QUERY)['integrations']


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
    deleteMethod
    managedProjects
    buildsCleanupRules {
      name
      keep_hours
    }
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
    providerVersion
    accountOwners {
      name
      email
    }
    automationToken {
      path
      field
    }
    garbageCollection
    enableDeletion
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
    path
    name
    serverUrl
    consoleUrl
    kibanaUrl
    prometheusUrl
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
      id
      external_id
      provider
      region
      channel
      version
      initial_version
      multi_az
      nodes
      instance_type
      storage
      load_balancers
      private
      provision_shard_id
      autoscale {
        min_replicas
        max_replicas
      }
    }
    externalConfiguration {
      labels
    }
    upgradePolicy {
      schedule_type
      schedule
    }
    additionalRouters {
      private
      route_selectors
    }
    network {
      vpc
      service
      pod
    }
    machinePools {
      id
      instance_type
      replicas
      labels
      taints {
        key
        value
        effect
      }
    }
    peering {
      connections {
        name
        provider
        manageRoutes
        delete
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
        ... on ClusterPeeringConnectionAccountVPCMesh_v1 {
          account {
            name
            uid
            terraformUsername
            automationToken {
              path
              field
            }
          }
          tags
        }
        ... on ClusterPeeringConnectionAccountTGW_v1 {
          account {
            name
            uid
            terraformUsername
            automationToken {
              path
              field
            }
          }
          tags
          cidrBlock
          manageSecurityGroups
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
                manageRoutes
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
    addons {
      name
      parameters {
        id
        value
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


CLUSTERS_MINIMAL_QUERY = """
{
  clusters: clusters_v1 {
    name
    serverUrl
    consoleUrl
    kibanaUrl
    prometheusUrl
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
    managedGroups
    ocm {
      name
    }
    spec {
        private
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
    auth {
      team
    }
  }
}
"""


def get_clusters(minimal=False):
    """ Returns all Clusters """
    gqlapi = gql.get_api()
    query = CLUSTERS_MINIMAL_QUERY if minimal else CLUSTERS_QUERY
    return gqlapi.query(query)['clusters']


KAFKA_CLUSTERS_QUERY = """
{
  clusters: kafka_clusters_v1 {
    name
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
    spec {
      provider
      region
      multi_az
    }
    namespaces {
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
  }
}
"""


def get_kafka_clusters(minimal=False):
    """ Returns all Kafka Clusters """
    gqlapi = gql.get_api()
    return gqlapi.query(KAFKA_CLUSTERS_QUERY)['clusters']


NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    managedRoles
    app {
      name
      serviceOwners {
        name
        email
      }
    }
    terraformResources
      {
        provider
        ... on NamespaceTerraformResourceRDS_v1
        {
          account
          identifier
          output_resource_name
          defaults
          replica_source
        }
        ... on NamespaceTerraformResourceECR_v1
        {
          account
          region
          identifier
          output_resource_name
          mirror {
            url
            pullCredentials {
              path
              field
            }
            tags
            tagsExclude
          }
        }
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
  }
}
"""


def get_namespaces():
    """ Returns all Namespaces """
    gqlapi = gql.get_api()
    return gqlapi.query(NAMESPACES_QUERY)['namespaces']


SA_TOKEN = """
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
serviceAccountName
"""


SERVICEACCOUNT_TOKENS_QUERY = """
{
  namespaces: namespaces_v1 {
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
    sharedResources {
      openshiftServiceAccountTokens {
        %s
      }
    }
    openshiftServiceAccountTokens {
      %s
    }
  }
}
""" % (indent(SA_TOKEN, 8*' '), indent(SA_TOKEN, 6*' '))


def get_serviceaccount_tokens():
    """ Returns all namespaces with ServiceAccount tokens information """
    gqlapi = gql.get_api()
    return gqlapi.query(SERVICEACCOUNT_TOKENS_QUERY)['namespaces']


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
    onboardingStatus
    serviceOwners {
      name
      email
    }
    parentApp {
      path
      name
    }
    codeComponents {
      url
      resource
      gitlabRepoOwners {
        enabled
      }
      gitlabHousekeeping {
        enabled
        rebase
        days_interval
        limit
        enable_closing
        pipeline_timeout
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
    code_components = \
        list(itertools.chain.from_iterable(code_components_lists))
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
            c['gitlabRepoOwners'] and
            c['gitlabRepoOwners']['enabled']]


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


QUAY_ORGS_QUERY = """
{
  quay_orgs: quay_orgs_v1 {
    name
    managedRepos
    instance {
      name
      url
    }
    managedTeams
    automationToken {
      path
      field
      format
      version
    }
    pushCredentials {
      path
      field
      format
      version
    }
    mirror {
      name
      instance {
        name
      }
    }
  }
}
"""


def get_quay_orgs():
    """ Returns all Quay orgs. """
    gqlapi = gql.get_api()
    return gqlapi.query(QUAY_ORGS_QUERY)['quay_orgs']


USERS_QUERY = """
{
  users: users_v1 {
    path
    name
    org_username
    github_username
    slack_username
    pagerduty_username
    public_gpg_key
    {% if refs %}
    requests {
      path
    }
    queries {
      path
    }
    {% endif %}
  }
}
"""


ROLES_QUERY = """
{
  users: users_v1 {
    name
    org_username
    github_username
    slack_username
    tag_on_cluster_updates
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
          quayOrg {
            name
            instance {
              name
              url
            }
          }
          team
        }
      }
      tag_on_cluster_updates
      access {
        cluster {
          name
          path
        }
        clusterRole
        namespace {
          name
          cluster {
            name
          }
        }
        role
      }

      {% if aws %}
      aws_groups {
        name
        path
        account {
          name
        }
        policies
      }
      {% endif %}

      {% if saas_files %}
      owned_saas_files {
        name
      }
      {% endif %}

      {% if sendgrid %}
      sendgrid_accounts {
        path
        name
      }
      {% endif %}
    }
  }
}
"""


def get_roles(aws=True, saas_files=True, sendgrid=False):
    gqlapi = gql.get_api()
    query = Template(ROLES_QUERY).render(aws=aws,
                                         saas_files=saas_files,
                                         sendgrid=sendgrid)
    return gqlapi.query(query)['users']


def get_users(refs=False):
    """ Returnes all Users. """
    gqlapi = gql.get_api()
    query = Template(USERS_QUERY).render(refs=refs)
    return gqlapi.query(query)['users']


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


EXTERNAL_USERS_QUERY = """
{
  external_users: external_users_v1 {
    path
    name
    github_username
  }
}
"""


def get_external_users():
    """ Returnes all Users. """
    gqlapi = gql.get_api()
    return gqlapi.query(EXTERNAL_USERS_QUERY)['external_users']


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
    requestor{
      org_username
      public_gpg_key
    }
    overrides
    {
      db_host
      db_port
      db_name
      db_user
      db_password
    }
    output
    schedule
    query
    queries
  }
}
"""


def get_app_interface_sql_queries():
    """ Returns SqlQuery resources defined in app-interface """
    gqlapi = gql.get_api()
    return gqlapi.query(APP_INTERFACE_SQL_QUERIES_QUERY)['sql_queries']


SAAS_FILES_QUERY_V1 = """
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
      output
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
      notifications {
        start
      }
    }
    managedResourceTypes
    takeover
    compare
    timeout
    publishJobLogs
    clusterAdmin
    imagePatterns
    use_channel_in_image_tag
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
      provider
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
            clusterAdminAutomationToken {
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
        promotion {
          auto
          publish
          subscribe
        }
        parameters
        upstream
        disable
        delete
      }
    }
    roles {
      users {
        org_username
        tag_on_merge_requests
      }
    }
  }
}
"""


SAAS_FILES_QUERY_V2 = """
{
  saas_files: saas_files_v2 {
    path
    name
    app {
      name
    }
    pipelinesProvider {
      name
      provider
      ...on PipelinesProviderTekton_v1 {
        namespace {
          name
          cluster {
            name
            consoleUrl
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
      }
    }
    slack {
      output
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
      notifications {
        start
      }
    }
    managedResourceTypes
    takeover
    compare
    publishJobLogs
    clusterAdmin
    imagePatterns
    use_channel_in_image_tag
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
      provider
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
            clusterAdminAutomationToken {
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
        promotion {
          auto
          publish
          subscribe
        }
        parameters
        upstream {
          instance {
            name
          }
          name
        }
        disable
        delete
      }
    }
    roles {
      users {
        org_username
        tag_on_merge_requests
      }
    }
  }
}
"""


def get_saas_files(saas_file_name=None, env_name=None, app_name=None,
                   v1=True,
                   v2=False):
    """ Returns SaasFile resources defined in app-interface.
    Returns v1 saas files by default. """
    gqlapi = gql.get_api()
    saas_files = []
    if v1:
        saas_files_v1 = gqlapi.query(SAAS_FILES_QUERY_V1)['saas_files']
        for sf in saas_files_v1:
            sf['apiVersion'] = 'v1'
        saas_files.extend(saas_files_v1)
    if v2:
        saas_files_v2 = gqlapi.query(SAAS_FILES_QUERY_V2)['saas_files']
        for sf in saas_files_v2:
            sf['apiVersion'] = 'v2'
        saas_files.extend(saas_files_v2)

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


SAAS_FILES_MINIMAL_QUERY_V1 = """
{
  saas_files: saas_files_v1 {
    path
    name
  }
}
"""


SAAS_FILES_MINIMAL_QUERY_V2 = """
{
  saas_files: saas_files_v2 {
    path
    name
  }
}
"""


def get_saas_files_minimal(v1=True, v2=False):
    """ Returns SaasFile resources defined in app-interface.
    Returns v1 saas files by default. """
    gqlapi = gql.get_api()
    saas_files = []
    if v1:
        saas_files_v1 = gqlapi.query(SAAS_FILES_MINIMAL_QUERY_V1)['saas_files']
        saas_files.extend(saas_files_v1)
    if v2:
        saas_files_v2 = gqlapi.query(SAAS_FILES_MINIMAL_QUERY_V2)['saas_files']
        saas_files.extend(saas_files_v2)

    return saas_files


PIPELINES_PROVIDERS_QUERY = """
{
  pipelines_providers: pipelines_providers_v1 {
    name
    provider
    retention {
      days
      minimum
    }
    ...on PipelinesProviderTekton_v1 {
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
    }
  }
}
"""


def get_pipelines_providers():
    """ Returns PipelinesProvider resources defined in app-interface."""
    gqlapi = gql.get_api()
    return gqlapi.query(PIPELINES_PROVIDERS_QUERY)['pipelines_providers']


JIRA_BOARDS_QUERY = """
{
  jira_boards: jira_boards_v1 {
    path
    name
    server {
      serverUrl
      token {
        path
      }
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
  }
}
"""


def get_jira_boards():
    """ Returns Jira boards resources defined in app-interface """
    gqlapi = gql.get_api()
    return gqlapi.query(JIRA_BOARDS_QUERY)['jira_boards']


UNLEASH_INSTANCES_QUERY = """
{
  unleash_instances: unleash_instances_v1 {
    name
    url
    token {
      path
      field
    }
    notifications {
      slack {
        workspace {
          name
          integrations {
            name
            token {
              path
              field
            }
          }
        }
        channel
        icon_emoji
        username
      }
    }
  }
}
"""


def get_unleash_instances():
    """ Returns Unleash instances defined in app-interface """
    gqlapi = gql.get_api()
    return gqlapi.query(UNLEASH_INSTANCES_QUERY)['unleash_instances']


DNS_ZONES_QUERY = """
{
  zones: dns_zone_v1 {
    name
    account {
      name
      uid
      terraformUsername
      automationToken {
        path
        field
      }
    }
    unmanaged_record_names
    records {
      name
      type
      ttl
      alias {
        name
        zone_id
        evaluate_target_health
      }
      weighted_routing_policy {
        weight
      }
      set_identifier
      records
      _healthcheck {
        fqdn
        port
        type
        resource_path
        failure_threshold
        request_interval
        search_string
      }
      _target_cluster {
        name
        elbFQDN
      }
    }
  }
}
"""


def get_dns_zones():
    """ Returnes all AWS Route53 DNS Zones. """
    gqlapi = gql.get_api()
    return gqlapi.query(DNS_ZONES_QUERY)['zones']


SLACK_WORKSPACES_QUERY = """
{
  slack_workspaces: slack_workspaces_v1 {
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
}
"""


def get_slack_workspace():
    """ Returns a single Slack workspace """
    gqlapi = gql.get_api()
    slack_workspaces = \
        gqlapi.query(SLACK_WORKSPACES_QUERY)['slack_workspaces']
    if len(slack_workspaces) != 1:
        logging.warning('multiple Slack workspaces found.')
    return gqlapi.query(SLACK_WORKSPACES_QUERY)['slack_workspaces'][0]


OCP_RELEASE_ECR_MIRROR_QUERY = """
{
  ocp_release_mirror: ocp_release_mirror_v1 {
    hiveCluster {
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
      managedGroups
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
      automationToken {
        path
        field
        format
      }
      internal
      disable {
        integrations
      }
      auth {
        team
      }
    }
    ecrResourcesNamespace {
      name
      managedTerraformResources
      terraformResources
      {
        provider
        ... on NamespaceTerraformResourceECR_v1
        {
          account
          region
          identifier
          output_resource_name
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
    quayTargetOrgs {
      name
      instance {
        name
      }
    }
    ocpReleaseEcrIdentifier
    ocpArtDevEcrIdentifier
  }
}
"""


def get_ocp_release_mirror():
    gqlapi = gql.get_api()
    return gqlapi.query(OCP_RELEASE_ECR_MIRROR_QUERY)['ocp_release_mirror']


SENDGRID_ACCOUNTS_QUERY = """
{
  sendgrid_accounts: sendgrid_accounts_v1 {
    path
    name
    token {
      path
      field
    }
  }
}
"""


def get_sendgrid_accounts():
    """ Returns SendGrid accounts """
    gqlapi = gql.get_api()
    return gqlapi.query(SENDGRID_ACCOUNTS_QUERY)['sendgrid_accounts']


QUAY_REPOS_QUERY = """
{
  apps: apps_v1 {
    quayRepos {
      org {
        name
        instance {
          name
          url
        }
      }
      items {
        name
        public
        mirror {
          url
          pullCredentials {
            path
            field
          }
          tags
          tagsExclude
        }
      }
    }
  }
}
"""


def get_quay_repos():
    gqlapi = gql.get_api()
    return gqlapi.query(QUAY_REPOS_QUERY)['apps']


SLO_DOCUMENTS_QUERY = """
{
  slo_documents: slo_document_v1 {
    name
    namespaces {
      name
      app {
        name
      }
      cluster {
        name
        automationToken {
          path
          field
          format
        }
        prometheusUrl
        spec {
          private
        }
      }
    }
    slos {
      name
      expr
      SLIType
      SLOParameters {
        window
      }
      SLOTarget
      SLOTargetUnit
    }
  }
}
"""


def get_slo_documents():
    gqlapi = gql.get_api()
    return gqlapi.query(SLO_DOCUMENTS_QUERY)['slo_documents']


SRE_CHECKPOINTS_QUERY = """
{
  sre_checkpoints: sre_checkpoints_v1 {
    app {
      name
      onboardingStatus
    }
    date
  }
}
"""


def get_sre_checkpoints():
    gqlapi = gql.get_api()
    return gqlapi.query(SRE_CHECKPOINTS_QUERY)['sre_checkpoints']


PAGERDUTY_INSTANCES_QUERY = """
{
  pagerduty_instances: pagerduty_instances_v1 {
    name
    token {
      path
      field
    }
  }
}
"""


def get_pagerduty_instances():
    gqlapi = gql.get_api()
    return gqlapi.query(PAGERDUTY_INSTANCES_QUERY)['pagerduty_instances']
