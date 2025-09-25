import itertools
import logging
import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from textwrap import indent
from typing import Any

from jinja2 import Template

from reconcile.gql_definitions.jumphosts.jumphosts import JumphostsQueryData
from reconcile.gql_definitions.jumphosts.jumphosts import query as jumphosts_query
from reconcile.utils import gql

SECRET_READER_SETTINGS = """
{
  settings: app_interface_settings_v1 {
    vault
  }
}
"""


def get_secret_reader_settings() -> Mapping[str, Any] | None:
    """Returns SecretReader settings"""
    gqlapi = gql.get_api()
    data = gqlapi.query(SECRET_READER_SETTINGS)
    if not data:
        return None
    settings = data.get("settings")
    if settings:
        # assuming a single settings file for now
        return settings[0]
    return None


APP_INTERFACE_SETTINGS_QUERY = """
{
  settings: app_interface_settings_v1 {
    repoUrl
    vault
    kubeBinary
    mergeRequestGateway
    hashLength
    smtp {
      mailAddress
      timeout
      credentials {
        path
        field
        version
        format
      }
    }
    imap {
      timeout
      credentials {
        path
        field
        version
        format
      }
    }
    githubRepoInvites {
      credentials {
        path
        field
        version
        format
      }
    }
    ldap {
      serverUrl
      baseDn
    }
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
        version
        format
      }
    }
    sqlQuery {
      jobImage
      pullSecret {
        path
        version
        labels
        annotations
        type
      }
    }
    alertingServices
    endpointMonitoringBlackboxExporterModules
    jiraWatcher {
      readTimeout
      connectTimeout
    }
    terraformResourcesProviderExclusions {
      provider
      excludeProvisioners {
        name
      }
      excludeAllProvisioners
    }
  }
}
"""


def get_app_interface_settings() -> dict[str, Any]:
    """Returns App Interface settings"""
    gqlapi = gql.get_api()
    data = gqlapi.query(APP_INTERFACE_SETTINGS_QUERY)
    if not data or not (settings := data.get("settings")):
        raise ValueError("no App Interface settings found")
    return settings[0]


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


def get_credentials_requests() -> list[dict[str, Any]]:
    """Returns Credentials Requests resources defined in app-interface"""
    gqlapi = gql.get_api()
    data = gqlapi.query(CREDENTIALS_REQUESTS_QUERY)
    if not data:
        return []
    return data.get("credentials_requests") or []


JUMPHOST_FIELDS = """
hostname
knownHosts
user
port
identity {
  path
  field
  version
  format
}
"""


INTEGRATIONS_QUERY = """
{
  integrations: integrations_v1 {
    name
    upstream
    managed {
      namespace {
        path
        name
        environment {
          name
          parameters
        }
        cluster {
          name
          serverUrl
          insecureSkipTLSVerify
          jumpHost {
            %s
          }
          automationToken {
            path
            field
            version
            format
          }
        }
      }
      shardSpecOverride{
       ... on AWSShardSpecOverride_v1 {
          awsAccounts {
            name
          }
          imageRef
        }
      }
      spec {
        cache
        command
        disableUnleash
        extraArgs
        extraEnv {
          secretName
          secretKey
          name
          value
        }
        internalCertificates
        logs {
          slack
          googleChat
        }
        resources {
          requests {
            cpu
            memory
          }
          limits {
            cpu
            memory
          }
        }
        fluentdResources {
          requests {
            cpu
            memory
          }
          limits {
            cpu
            memory
          }
        }
        shards
        shardingStrategy
        sleepDurationSecs
        state
        storage
        trigger
        cron
        dashdotdb
        concurrencyPolicy
        restartPolicy
        successfulJobHistoryLimit
        failedJobHistoryLimit
        imageRef
        enablePushgateway
      }
    }
  }
}
""" % (indent(JUMPHOST_FIELDS, 12 * " "),)


def get_integrations(managed: bool = False) -> list[dict[str, Any]]:
    gqlapi = gql.get_api()
    query = INTEGRATIONS_QUERY if managed else gql.INTEGRATIONS_QUERY
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("integrations") or []


JENKINS_INSTANCES_QUERY = """
{
  instances: jenkins_instances_v1 {
    name
    serverUrl
    token {
      path
      field
      version
      format
    }
    previousUrls
    deleteMethod
    managedProjects
    buildsCleanupRules {
      name
      keep_hours
    }
    {% if worker_fleets %}
    workerFleets {
      account
      identifier
      sshConnector {
        credentialsId
        jvmOptions
        launchTimeoutSeconds
        maxNumRetries
        port
        retryWaitTime
        sshHostKeyVerificationStrategy
      }
      fsRoot
      labelString
      numExecutors
      idleMinutes
      minSpareSize
      maxTotalUses
      noDelayProvision
      alwaysReconnect
      namespace{
        name
        managedExternalResources
        externalResources {
          provider
          ... on NamespaceTerraformProviderResourceAWS_v1 {
            provisioner {
              name
              resourcesDefaultRegion
            }
            resources {
              provider
              ... on NamespaceTerraformResourceASG_v1 {
                identifier
                defaults
                overrides
              }
            }
          }
        }
      }
    }
    {% endif %}
  }
}
"""


def get_jenkins_instances(worker_fleets: bool = False) -> list[dict[str, Any]]:
    """Returns a list of Jenkins instances"""
    gqlapi = gql.get_api()
    query = Template(JENKINS_INSTANCES_QUERY).render(worker_fleets=worker_fleets)
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("instances") or []


def get_jenkins_instances_previous_urls() -> list[str]:
    instances = get_jenkins_instances()
    all_previous_urls: list[str] = []
    for instance in instances:
        previous_urls = instance.get("previousUrls")
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
      version
      format
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


def get_gitlab_instance() -> dict[str, Any]:
    """Returns a single GitLab instance"""
    gqlapi = gql.get_api()
    data = gqlapi.query(GITLAB_INSTANCES_QUERY)
    if not data or not (instances := data.get("instances")):
        raise ValueError("no GitLab instance found")
    return instances[0]


GITHUB_INSTANCE_QUERY = """
{
  instances: githuborg_v1 {
    url
    token {
      path
      field
      version
      format
    }
  }
}
"""


def get_github_instance() -> dict[str, Any]:
    """Returns a single Github instance"""
    gqlapi = gql.get_api()
    data = gqlapi.query(GITHUB_INSTANCE_QUERY)
    if not data or not (instances := data.get("instances")):
        raise ValueError("no Github instance found")
    for instance in instances:
        if instance["url"] == "https://github.com/app-sre":
            return instance
    raise ValueError("no Github instance found")


GITHUB_ORGS_QUERY = """
{
  orgs: githuborg_v1 {
    name
    two_factor_authentication
    token {
      path
      field
      version
      format
    }
  }
}
"""


def get_github_orgs() -> list[dict[str, Any]]:
    """Returns all GitHub orgs"""
    gqlapi = gql.get_api()
    data = gqlapi.query(GITHUB_ORGS_QUERY)
    if not data:
        return []
    return data.get("orgs") or []


AWS_ACCOUNTS_QUERY = """
{
  accounts: awsaccounts_v1
  {% if search %}
  (
    {% if name %}
    name: "{{ name }}"
    {% endif %}
    {% if uid %}
    uid: "{{ uid }}"
    {% endif %}
  )
  {% endif %}
  {
    path
    name
    uid
    terraformUsername
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
      version
      format
    }
    enableDeletion
    deletionApprovals {
      type
      name
      expiration
    }
    disable {
      integrations
    }
    deleteKeys
    {% if reset_passwords %}
    resetPasswords {
      user {
        org_username
      }
      requestId
    }
    {% endif %}
    premiumSupport
    {% if ecrs %}
    ecrs {
      region
    }
    {% endif %}
    partition
    {% if sharing %}
    sharing {
      provider
      account {
        name
        uid
        supportedDeploymentRegions
      }
      ... on AWSAccountSharingOptionAMI_v1 {
        regex
        region
      }
    }
    {% endif %}
    {% if terraform_state %}
    terraformState {
      provider
      bucket
      region
      integrations {
          key
          integration
      }
    }
    {% endif %}
    {% if cleanup %}
    cleanup {
      provider
      ... on AWSAccountCleanupOptionCloudWatch_v1 {
        regex
        retention_in_days
        delete_empty_log_group
        region
      }
      ... on AWSAccountCleanupOptionAMI_v1 {
        regex
        age
        region
      }
    }
    {% endif %}
  }
}
"""


def get_aws_accounts(
    reset_passwords: bool = False,
    name: str | None = None,
    uid: str | None = None,
    sharing: bool = False,
    terraform_state: bool = False,
    ecrs: bool = True,
    cleanup: bool = False,
) -> list[dict[str, Any]]:
    """Returns all AWS accounts"""
    gqlapi = gql.get_api()
    search = name or uid
    query = Template(AWS_ACCOUNTS_QUERY).render(
        reset_passwords=reset_passwords,
        search=search,
        name=name,
        uid=uid,
        sharing=sharing,
        terraform_state=terraform_state,
        ecrs=ecrs,
        cleanup=cleanup,
    )
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("accounts") or []


def get_state_aws_accounts(reset_passwords: bool = False) -> list[dict[str, Any]]:
    """Returns AWS accounts to use for state management"""
    name = os.environ["APP_INTERFACE_STATE_BUCKET_ACCOUNT"]
    return get_aws_accounts(reset_passwords=reset_passwords, name=name)


def get_queue_aws_accounts() -> list[dict[str, Any]]:
    """Returns AWS accounts to use for queue management"""
    uid = os.environ["gitlab_pr_submitter_queue_url"].split("/")[3]  # noqa: SIM112
    return get_aws_accounts(uid=uid)


def get_jumphosts(hostname: str | None = None) -> JumphostsQueryData:
    """Returns all jumphosts"""
    variables = {}
    # The dictionary must be empty if no hostname is set.
    # That way it will return every hostname.
    # Otherwise GQL will try to find hostname: null
    if hostname:
        variables["hostname"] = hostname
    gqlapi = gql.get_api()
    return jumphosts_query(
        query_func=gqlapi.query,
        variables=variables,
    )


AWS_INFRA_MANAGEMENT_ACCOUNT = """
awsInfrastructureManagementAccounts {
  account {
    name
    uid
    terraformUsername
    resourcesDefaultRegion
    automationToken {
      path
      field
      version
      format
    }
  }
  accessLevel
  default
}
"""

CLUSTER_FILTER_QUERY = """
{% if filter %}
(
  {% if filter.name %}
  name: "{{ filter.name }}"
  {% endif %}
)
{% endif %}
"""

AWS_INFRASTRUCTURE_ACCESS_QUERY = """
{% if aws_infrastructure_access %}
awsInfrastructureAccess {
  awsGroup {
    account {
      name
      uid
      terraformUsername
      automationToken {
        path
        field
        version
        format
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
{% endif %}
"""

CLUSTERS_QUERY = """
{
  clusters: clusters_v1
  %s
  {
    path
    name
    serverUrl
    consoleUrl
    elbFQDN
    prometheusUrl
    managedGroups
    managedClusterRoles
    insecureSkipTLSVerify
    jumpHost {
      %s
    }
    auth {
      service
      ... on ClusterAuthGithubOrg_v1 {
        org
      }
      ... on ClusterAuthGithubOrgTeam_v1 {
        org
        team
      }
      # ... on ClusterAuthOIDC_v1 {
      # }
    }
    ocm {
      name
      environment {
        name
        url
        accessTokenClientId
        accessTokenUrl
        accessTokenClientSecret {
          path
          field
          format
          version
        }
      }
      orgId
      accessTokenClientId
      accessTokenUrl
      accessTokenClientSecret {
        path
        field
        format
        version
      }
      allowedClusterExternalConfigLabels
      blockedVersions
      inheritVersionData {
        name
        orgId
        environment {
          name
        }
        publishVersionData {
          orgId
          name
        }
      }
      sectors {
        name
        maxParallelUpgrades
        dependencies {
          name
        }
      }
    }
    %s
    %s
    spec {
      product
      hypershift
      ... on ClusterSpecOSD_v1 {
        storage
        load_balancers
      }
      ... on ClusterSpecROSA_v1 {
        subnet_ids
        availability_zones
        oidc_endpoint_url
        account {
          name
          uid
          terraformUsername
          resourcesDefaultRegion
          automationToken {
            path
            field
            version
            format
          }
          rosa {
            ocm_environments {
              ocm {
                name
              }
              creator_role_arn
              installer_role_arn
              support_role_arn
              controlplane_role_arn
              worker_role_arn
            }
          }
          billingAccount {
            uid
          }
        }
      }
      id
      external_id
      provider
      region
      channel
      version
      initial_version
      multi_az
      private
      provision_shard_id
      disable_user_workload_monitoring
      fips
    }
    externalConfiguration {
      labels
    }
    upgradePolicy {
      workloads
      schedule
      conditions {
        soakDays
        mutexes
        sector
      }
    }
    additionalRouters {
      private
      route_selectors
    }
    network {
      type
      vpc
      service
      pod
    }
    machinePools {
      id
      instance_type
      replicas
      autoscale {
        min_replicas
        max_replicas
      }
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
                version
                format
              }
            }
            vpc_id
            cidr_block
            region
          }
          assumeRole
        }
        ... on ClusterPeeringConnectionAccountVPCMesh_v1 {
          account {
            name
            uid
            terraformUsername
            automationToken {
              path
              field
              version
              format
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
              version
              format
            }
          }
          tags
          cidrBlock
          cidrBlocks
          manageSecurityGroups
          assumeRole
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
                    version
                    format
                  }
                }
              }
              accessLevel
            }
            %s
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
                  awsInfrastructureManagementAccount {
                    name
                    uid
                    terraformUsername
                    automationToken {
                      path
                      field
                      version
                      format
                    }
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
      version
      format
    }
    clusterAdminAutomationToken {
      path
      field
      version
      format
    }
    clusterAdmin
    internal
    disable {
      integrations
    }
  }
}
""" % (
    indent(CLUSTER_FILTER_QUERY, 2 * " "),
    indent(JUMPHOST_FIELDS, 6 * " "),
    indent(AWS_INFRASTRUCTURE_ACCESS_QUERY, 4 * " "),
    indent(AWS_INFRA_MANAGEMENT_ACCOUNT, 4 * " "),
    indent(AWS_INFRA_MANAGEMENT_ACCOUNT, 12 * " "),
)


CLUSTERS_MINIMAL_QUERY = """
{
  clusters: clusters_v1
  %s
  {
    name
    serverUrl
    consoleUrl
    prometheusUrl
    insecureSkipTLSVerify
    jumpHost {
      %s
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
      version
      format
    }
    internal
    disable {
      integrations
    }
    auth {
      service
      ... on ClusterAuthGithubOrg_v1 {
        org
      }
      ... on ClusterAuthGithubOrgTeam_v1 {
        org
        team
      }
      ... on ClusterAuthOIDC_v1 {
        name
      }
    }
  }
}
""" % (
    indent(CLUSTER_FILTER_QUERY, 2 * " "),
    indent(JUMPHOST_FIELDS, 6 * " "),
)


def get_clusters(
    minimal: bool = False, aws_infrastructure_access: bool = False
) -> list[dict[str, Any]]:
    """Returns all Clusters"""
    gqlapi = gql.get_api()
    tmpl = CLUSTERS_MINIMAL_QUERY if minimal else CLUSTERS_QUERY
    query = Template(tmpl).render(
        filter=None,
        aws_infrastructure_access=aws_infrastructure_access,
    )
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("clusters") or []


CLUSTER_PEERING_QUERY = """
{
  clusters: clusters_v1
  {
    path
    name
    ocm {
      name
      environment {
        name
        url
        accessTokenClientId
        accessTokenUrl
        accessTokenClientSecret {
          path
          field
          format
          version
        }
      }
      orgId
      accessTokenClientId
      accessTokenUrl
      accessTokenClientSecret {
        path
        field
        format
        version
      }
      blockedVersions
    }
    awsInfrastructureManagementAccounts {
      account {
        name
        uid
        terraformUsername
        resourcesDefaultRegion
        automationToken {
          path
          field
          version
          format
        }
      }
      accessLevel
      default
    }

    spec {
      id
      region
      private
      hypershift
      ... on ClusterSpecROSA_v1 {
        account {
          name
          uid
          terraformUsername
          automationToken {
            path
            field
            version
            format
          }
        }
      }
    }
    network {
      vpc
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
                version
                format
              }
            }
            vpc_id
            cidr_block
            region
          }
          assumeRole
          manageAccountRoutes
        }
        ... on ClusterPeeringConnectionAccountVPCMesh_v1 {
          account {
            name
            uid
            terraformUsername
            automationToken {
              path
              field
              version
              format
            }
          }
          tags
          assumeRole
        }
        ... on ClusterPeeringConnectionAccountTGW_v1 {
          account {
            name
            uid
            terraformUsername
            automationToken {
              path
              field
              version
              format
            }
          }
          tags
          cidrBlock
          manageSecurityGroups
          manageRoute53Associations
          assumeRole
        }
        ... on ClusterPeeringConnectionClusterRequester_v1 {
          cluster {
            name
            network {
              vpc
            }
            spec {
              id
              region
              private
              hypershift
              ... on ClusterSpecROSA_v1 {
                account {
                  name
                  uid
                  terraformUsername
                  automationToken {
                    path
                    field
                    version
                    format
                  }
                }
              }
            }
            awsInfrastructureManagementAccounts {
              account {
                name
                uid
                terraformUsername
                resourcesDefaultRegion
                automationToken {
                  path
                  field
                  version
                  format
                }
              }
              accessLevel
              default
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
                    spec {
                      ... on ClusterSpecROSA_v1 {
                        account {
                          name
                          uid
                          terraformUsername
                          automationToken {
                            path
                            field
                            version
                            format
                          }
                        }
                      }
                    }
                  }
                  assumeRole
                  awsInfrastructureManagementAccount {
                    name
                    uid
                    terraformUsername
                    automationToken {
                      path
                      field
                      version
                      format
                    }
                  }
                }
              }
            }
          }
          assumeRole
        }
      }
    }
    disable {
      integrations
    }
  }
}
"""


def get_clusters_with_peering_settings() -> list[dict[str, Any]]:
    data = gql.get_api().query(CLUSTER_PEERING_QUERY)
    if not data:
        return []
    clusters = data.get("clusters") or []
    return [c for c in clusters if c.get("peering") is not None]


@dataclass
class ClusterFilter:
    name: str = ""


def get_clusters_by(
    filter: ClusterFilter, minimal: bool = False
) -> list[dict[str, Any]]:
    """Returns all Clusters fitting given filter"""
    gqlapi = gql.get_api()
    tmpl = CLUSTERS_MINIMAL_QUERY if minimal else CLUSTERS_QUERY
    query = Template(tmpl).render(
        filter=filter,
    )
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("clusters") or []


OCM_QUERY = """
{
  instances: ocm_instances_v1 {
    path
    name
    environment {
      name
      url
      labels
      accessTokenClientId
      accessTokenUrl
      accessTokenClientSecret {
        path
        field
        format
        version
      }
    }
    orgId
    blockedVersions
    recommendedVersions {
      recommendedVersion
      workload
      channel
      initialVersion
    }
    recommendedVersionWeight {
      highest
      majority
    }
    accessTokenClientId
    accessTokenUrl
    accessTokenClientSecret {
      path
      field
      format
      version
    }
    addonManagedUpgrades
    addonUpgradeTests {
      addon {
        name
      }
      instance {
        name
        token {
          path
          field
          version
          format
        }
      }
      name
    }
    inheritVersionData {
      name
      publishVersionData {
        name
      }
    }
    sectors {
      name
      maxParallelUpgrades
      dependencies {
        name
        ocm {
          name
        }
      }
    }
    upgradePolicyAllowedWorkloads
    upgradePolicyDefaults {
      name
      matchLabels
      upgradePolicy {
        workloads
        schedule
        conditions {
          sector
          soakDays
          mutexes
        }
      }
      upgradePolicyTemplate {
        path {
          content
        }
        type
        variables
      }
    }
    upgradePolicyClusters {
      name
      upgradePolicy {
        workloads
        schedule
        conditions {
          sector
          soakDays
          mutexes
          sector
        }
      }
    }
  }
}
"""


def get_openshift_cluster_managers() -> list[dict[str, Any]]:
    data = gql.get_api().query(OCM_QUERY)
    if not data:
        return []
    return data.get("instances") or []


NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    delete
    labels
    clusterAdmin
    managedRoles
    app {
      name
      serviceOwners {
        name
        email
      }
    }
    managedExternalResources
    externalResources {
      provider
      provisioner {
        name
      }
      ... on NamespaceTerraformProviderResourceAWS_v1 {
        resources {
          provider
          ... on NamespaceTerraformResourceRDS_v1
          {
            identifier
            output_resource_name
            defaults
            replica_source
          }
          ... on NamespaceTerraformResourceECR_v1
          {
            region
            identifier
            output_resource_name
            mirror {
              url
              pullCredentials {
                path
                field
                version
                format
              }
              tags
              tagsExclude
            }
          }
        }
      }
    }
    cluster {
      name
      serverUrl
      insecureSkipTLSVerify
      jumpHost {
        %s
      }
      automationToken {
        path
        field
        version
        format
      }
      clusterAdminAutomationToken {
        path
        field
        version
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
          pods
        }
        scopes
      }
    }
  }
}
""" % (indent(JUMPHOST_FIELDS, 8 * " "),)

NAMESPACES_MINIMAL_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    delete
    labels
    cluster {
      name
      serverUrl
      insecureSkipTLSVerify
      jumpHost {
        %s
      }
      automationToken {
        path
        field
        version
        format
      }
      internal
      disable {
        integrations
      }
    }
  }
}
""" % (indent(JUMPHOST_FIELDS, 8 * " "),)


def get_namespaces(minimal: bool = False) -> list[dict[str, Any]]:
    """Returns all Namespaces"""
    gqlapi = gql.get_api()
    query = NAMESPACES_MINIMAL_QUERY if minimal else NAMESPACES_QUERY
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("namespaces") or []


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


def get_products() -> list[dict[str, Any]]:
    """Returns all Products"""
    gqlapi = gql.get_api()
    data = gqlapi.query(PRODUCTS_QUERY)
    if not data:
        return []
    return data.get("products") or []


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


def get_environments() -> list[dict[str, Any]]:
    """Returns all Products"""
    gqlapi = gql.get_api()
    data = gqlapi.query(ENVIRONMENTS_QUERY)
    if not data:
        return []
    return data.get("environments") or []


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
      name
      url
      resource
      showInReviewQueue
      gitlabRepoOwners {
        enabled
        persistentLgtm
      }
      gitlabHousekeeping {
        enabled
        rebase
        days_interval
        limit
        enable_closing
        pipeline_timeout
        labels_allowed {
          role {
            users {
              org_username
            }
          }
        }
        must_pass
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

CODE_COMPONENT_REPO_QUERY = """
{
  apps: apps_v1 {
    codeComponents {
      url
      managePermissions
    }
  }
}
"""


def get_apps() -> list[dict[str, Any]]:
    """Returns all Apps."""
    gqlapi = gql.get_api()
    data = gqlapi.query(APPS_QUERY)
    if not data:
        return []
    return data.get("apps") or []


def get_code_components() -> list[dict[str, Any]]:
    """Returns code components from all apps."""
    apps = get_apps()
    code_components_lists = [
        a["codeComponents"] for a in apps if a["codeComponents"] is not None
    ]
    code_components = list(itertools.chain.from_iterable(code_components_lists))
    return code_components


def get_review_repos() -> list[dict[str, str]]:
    """Returns name and url of code components marked for review"""
    code_components = get_code_components()
    return [
        {"url": c["url"], "name": c["name"]}
        for c in code_components
        if c["showInReviewQueue"] is not None
    ]


def get_repos(server: str = "", exclude_manage_permissions: bool = False) -> list[str]:
    """Returns all repos defined under codeComponents
    Optional arguments:
    server: url of the server to return. for example: https://github.com
    """
    data = gql.get_api().query(CODE_COMPONENT_REPO_QUERY)
    if not data:
        return []
    apps = data.get("apps") or []
    repos: list[str] = []
    for a in apps:
        if a["codeComponents"] is not None:
            for c in a["codeComponents"]:
                if exclude_manage_permissions and c.get("managePermissions") is False:
                    continue
                if c["url"].startswith(server):
                    repos.append(c["url"])
    return repos


def get_repos_gitlab_owner(server: str = "") -> list[dict[str, Any]]:
    """Returns all repos defined under codeComponents that have gitlabOwner
    enabled.
    Optional arguments:
    server: url of the server to return. for example: https://github.com
    """
    code_components = get_code_components()
    return [
        {"url": c["url"], "gitlabRepoOwners": c["gitlabRepoOwners"]}
        for c in code_components
        if c["url"].startswith(server)
        and c["gitlabRepoOwners"]
        and c["gitlabRepoOwners"]["enabled"]
    ]


def get_repos_gitlab_housekeeping(server: str = "") -> list[dict[str, Any]]:
    """Returns all repos defined under codeComponents that have
    gitlabHousekeeping enabled.
    Optional arguments:
    server: url of the server to return. for example: https://github.com
    """
    code_components = get_code_components()
    return [
        {"url": c["url"], "housekeeping": c["gitlabHousekeeping"]}
        for c in code_components
        if c["url"].startswith(server)
        and c["gitlabHousekeeping"]
        and c["gitlabHousekeeping"]["enabled"]
    ]


def get_repos_gitlab_jira(server: str = "") -> list[dict[str, Any]]:
    code_components = get_code_components()
    return [
        {"url": c["url"], "jira": c["jira"]}
        for c in code_components
        if c["url"].startswith(server) and c.get("jira")
    ]


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
    mirrorFilters {
      ... on QuayOrgMirrorFilter_v1 {
        name
        tags
        tagsExclude
      }
    }
  }
}
"""


def get_quay_orgs() -> list[dict[str, Any]]:
    """Returns all Quay orgs."""
    gqlapi = gql.get_api()
    data = gqlapi.query(QUAY_ORGS_QUERY)
    if not data:
        return []
    return data.get("quay_orgs") or []


USERS_QUERY = """
{
  users: users_v1
  {% if filter %}
  (
    {% if filter.org_username %}
    org_username: "{{ filter.org_username }}"
    {% endif %}
  )
  {% endif %}
  {
    path
    name
    org_username
    github_username
    pagerduty_username
    public_gpg_key
    {% if refs %}
    aws_accounts {
      path
    }
    requests {
      path
    }
    queries {
      path
    }
    gabi_instances {
      path
    }
    schedules {
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
    tag_on_cluster_updates
    labels
    roles {
      name
      path
      {% if permissions %}
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
      {% endif %}
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
      self_service {
        datafiles {
          ... on SaasFile_v2 {
            name
          }
        }
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


def get_roles(
    aws: bool = True,
    saas_files: bool = True,
    sendgrid: bool = False,
    permissions: bool = True,
) -> list[dict[str, Any]]:
    gqlapi = gql.get_api()
    query = Template(ROLES_QUERY).render(
        aws=aws, saas_files=saas_files, sendgrid=sendgrid, permissions=permissions
    )
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("users") or []


def get_users(refs: bool = False) -> list[dict[str, Any]]:
    """Returnes all Users."""
    gqlapi = gql.get_api()
    query = Template(USERS_QUERY).render(
        filter=None,
        refs=refs,
    )
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("users") or []


@dataclass
class UserFilter:
    org_username: str = ""


def get_users_by(filter: UserFilter, refs: bool = False) -> list[dict[str, str]]:
    """Returnes all Users that satisfy given filter"""
    gqlapi = gql.get_api()
    query = Template(USERS_QUERY).render(
        filter=filter,
        refs=refs,
    )
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("users") or []


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


def get_bots() -> list[dict[str, Any]]:
    """Returnes all Bots."""
    gqlapi = gql.get_api()
    data = gqlapi.query(BOTS_QUERY)
    if not data:
        return []
    return data.get("bots") or []


EXTERNAL_USERS_QUERY = """
{
  external_users: external_users_v1 {
    path
    name
    github_username
  }
}
"""


def get_external_users() -> list[dict[str, Any]]:
    """Returnes all Users."""
    gqlapi = gql.get_api()
    data = gqlapi.query(EXTERNAL_USERS_QUERY)
    if not data:
        return []
    return data.get("external_users") or []


APP_INTERFACE_SQL_QUERIES_QUERY = """
{
  sql_queries: app_interface_sql_queries_v1 {
    path
    name
    namespace
    {
      name
      managedExternalResources
      externalResources {
        provider
        provisioner {
          name
        }
        ... on NamespaceTerraformProviderResourceAWS_v1 {
          resources {
            provider
            ... on NamespaceTerraformResourceRDS_v1
            {
              identifier
              output_resource_name
              defaults
              overrides
            }
          }
        }
      }
      app {
        name
      }
      environment {
        name
      }
      cluster
      {
        name
        serverUrl
        automationToken
        {
          path
          field
          version
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
    delete
    query
    queries
  }
}
"""


def get_app_interface_sql_queries() -> list[dict[str, Any]]:
    """Returns SqlQuery resources defined in app-interface"""
    gqlapi = gql.get_api()
    data = gqlapi.query(APP_INTERFACE_SQL_QUERIES_QUERY)
    if not data:
        return []
    return data.get("sql_queries") or []


PIPELINES_PROVIDERS_QUERY = """
{
  pipelines_providers: pipelines_providers_v1 {
    name
    provider
    ...on PipelinesProviderTekton_v1 {
      defaults {
        retention {
          days
          minimum
        }
        taskTemplates {
          ...on PipelinesProviderTektonObjectTemplate_v1 {
            name
            type
            path
            variables
          }
        }
        pipelineTemplates {
          openshiftSaasDeploy {
            name
            type
            path
            variables
          }
        }
        deployResources {
          requests {
            cpu
            memory
          }
          limits {
            cpu
            memory
          }
        }
      }
      namespace {
        name
        delete
        cluster {
          name
          serverUrl
          insecureSkipTLSVerify
          jumpHost {
            %s
          }
          automationToken {
            path
            field
            version
            format
          }
          internal
          disable {
            integrations
          }
        }
      }
      retention {
        days
        minimum
      }
      taskTemplates {
        ...on PipelinesProviderTektonObjectTemplate_v1 {
          name
          type
          path
          variables
        }
      }
      pipelineTemplates {
        openshiftSaasDeploy {
          name
          type
          path
          variables
        }
      }
      deployResources {
        requests {
          cpu
          memory
        }
        limits {
          cpu
          memory
        }
      }
    }
  }
}
""" % (indent(JUMPHOST_FIELDS, 12 * " "),)


def get_pipelines_providers() -> list[dict[str, Any]]:
    """Returns PipelinesProvider resources defined in app-interface."""
    gqlapi = gql.get_api()
    data = gqlapi.query(PIPELINES_PROVIDERS_QUERY)
    if not data:
        return []
    pipelines_providers = data.get("pipelines_providers") or []

    for pp in pipelines_providers:
        defaults = pp.pop("defaults")
        for k, v in defaults.items():
            if k not in pp or not pp[k]:
                pp[k] = v

    return pipelines_providers


# Use APATH as the place holder because Python formatting interferes
# with graphql use of curly braces
JIRA_BOARDS_QUICK_QUERY = """
{
  jira_boards: jira_boards_v1 (path: "APATH") {
    path
    name
    server {
      serverUrl
      token {
        path
        field
        version
        format
      }
    }
  }
}
"""


def get_simple_jira_boards(app_path: str) -> list[dict[str, Any]]:
    gqlapi = gql.get_api()
    query = JIRA_BOARDS_QUICK_QUERY.replace("APATH", shlex.quote(app_path))
    data = gqlapi.query(query)
    if not data:
        return []
    return data.get("jira_boards") or []


UNLEASH_INSTANCES_QUERY = """
{
  unleash_instances: unleash_instances_v1 {
    name
    url
    token {
      path
      field
      version
      format
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
              version
              format
            }
          }
          api_client {
            global {
              max_retries
              timeout
            }
            methods {
              name
              args
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


def get_unleash_instances() -> list[dict[str, Any]]:
    """Returns Unleash instances defined in app-interface"""
    gqlapi = gql.get_api()
    data = gqlapi.query(UNLEASH_INSTANCES_QUERY)
    if not data:
        return []
    return data.get("unleash_instances") or []


DNS_RECORD = """
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
geolocation_routing_policy {
  continent
  country
  subdivision
}
set_identifier
records
"""


DNS_ZONES_QUERY = """
{
  zones: dns_zone_v1 {
    name
    domain_name
    account {
      name
      uid
      terraformUsername
      automationToken {
        path
        field
        version
        format
      }
    }
    vpc {
      vpc_id
      region
    }
    allowed_vault_secret_paths
    records {
      %s
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
      _records_from_vault {
        path
        field
        key
        version
      }
      _target_namespace_zone {
        namespace {
          managedExternalResources
          externalResources {
            provider
            provisioner {
              name
            }
            ... on NamespaceTerraformProviderResourceAWS_v1 {
              resources {
                provider
                ... on NamespaceTerraformResourceRoute53Zone_v1 {
                  region
                  name
                }
              }
            }
          }
        }
        name
      }
    }
  }
}
""" % (indent(DNS_RECORD, 6 * " "),)


def get_dns_zones(account_name: str | None = None) -> list[dict[str, Any]]:
    """Returnes all AWS Route53 DNS Zones."""
    gqlapi = gql.get_api()
    data = gqlapi.query(DNS_ZONES_QUERY)
    if not data:
        return []
    zones = data.get("zones") or []
    if account_name:
        zones = [z for z in zones if z.get("account", {}).get("name") == account_name]

    return zones


SLACK_WORKSPACES_QUERY = """
{
  slack_workspaces: slack_workspaces_v1 {
    name
    integrations {
      name
      token {
        path
        field
        version
        format
      }
      channel
      icon_emoji
      username
    }
    api_client {
      global {
        max_retries
        timeout
      }
      methods {
        name
        args
      }
    }
  }
}
"""


def get_slack_workspace() -> dict[str, Any] | None:
    """Returns a single Slack workspace"""
    gqlapi = gql.get_api()
    data = gqlapi.query(SLACK_WORKSPACES_QUERY)
    if not data:
        return None
    slack_workspaces = data.get("slack_workspaces") or []
    if len(slack_workspaces) > 1:
        logging.warning("multiple Slack workspaces found.")
    return slack_workspaces[0] if slack_workspaces else None


SENDGRID_ACCOUNTS_QUERY = """
{
  sendgrid_accounts: sendgrid_accounts_v1 {
    path
    name
    token {
      path
      field
      version
      format
    }
  }
}
"""


def get_sendgrid_accounts() -> list[dict[str, Any]]:
    """Returns SendGrid accounts"""
    gqlapi = gql.get_api()
    data = gqlapi.query(SENDGRID_ACCOUNTS_QUERY)
    if not data:
        return []
    return data.get("sendgrid_accounts") or []


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
            version
            format
          }
          tags
          tagsExclude
        }
      }
    }
  }
}
"""


def get_quay_repos() -> list[dict[str, Any]]:
    gqlapi = gql.get_api()
    data = gqlapi.query(QUAY_REPOS_QUERY)
    if not data:
        return []
    return data.get("apps") or []


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


def get_sre_checkpoints() -> list[dict[str, Any]]:
    gqlapi = gql.get_api()
    data = gqlapi.query(SRE_CHECKPOINTS_QUERY)
    if not data:
        return []
    return data.get("sre_checkpoints") or []


GABI_INSTANCES_QUERY = """
{
  gabi_instances: gabi_instances_v1 {
    path
    name
    signoffManagers{
      org_username
    }
    users{
      github_username
      org_username
    }
    instances{
      account
      identifier
      namespace{
        name
        managedExternalResources
        externalResources {
          provider
          provisioner {
            name
          }
          ... on NamespaceTerraformProviderResourceAWS_v1 {
            resources {
              provider
              identifier
            }
          }
        }
        cluster {
          name
          serverUrl
          insecureSkipTLSVerify
          jumpHost {
            %s
          }
          automationToken {
            path
            field
            version
            format
          }
          internal
          disable {
            integrations
          }
          auth {
            service
          }
        }
      }
    }
    expirationDate
  }
}
""" % (indent(JUMPHOST_FIELDS, 12 * " "),)


def get_gabi_instances() -> list[dict[str, Any]]:
    gqlapi = gql.get_api()
    data = gqlapi.query(GABI_INSTANCES_QUERY)
    if not data:
        return []
    return data.get("gabi_instances") or []


CLOSED_BOX_MONITORING_PROBES_QUERY = """
{
  apps: apps_v1 {
    endPoints {
      name
      description
      url
      monitoring {
        provider {
          name
          description
          provider
          metricLabels
          timeout
          checkInterval
          ... on EndpointMonitoringProviderBlackboxExporter_v1 {
            blackboxExporter {
              module
              namespace {
                name
                cluster {
                  name
                  serverUrl
                  automationToken {
                    path
                    field
                    version
                  }
                  internal
                }
              }
              exporterUrl
            }
          }
          ... on EndpointMonitoringProviderSignalFx_v1 {
            signalFx {
              exporterUrl
              targetFilterLabel
              namespace {
                name
                cluster {
                  name
                  serverUrl
                  automationToken {
                    path
                    field
                    version
                  }
                  internal
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


def get_service_monitoring_endpoints() -> list[dict[str, Any]]:
    gqlapi = gql.get_api()
    data = gqlapi.query(CLOSED_BOX_MONITORING_PROBES_QUERY)
    if not data:
        return []
    return data.get("apps") or []


# Use APATH as place holder because query strings have a lot of curly
# braces and it would be confusing to add more to use f-strings or
# format.
APP_METADATA = """
{
  apps: apps_v1 (path: "APATH") {
    labels
    name
    description
    sopsUrl
    grafanaUrls {
      url
    }
    architectureDocument
    serviceOwners {
      name
      email
    }
    escalationPolicy {
      description
      channels {
        jiraBoard {
          name
          server {
            serverUrl
            token {
              path
              field
            }
          }
        }
        slackUserGroup {
          name
        }
      }
    }
  }
}
"""


def get_app_metadata(app_path: str) -> dict:
    """Fetch the metadata for the path stored in app_path."""
    app_query = APP_METADATA.replace("APATH", shlex.quote(app_path))
    gqlapi = gql.get_api()
    data = gqlapi.query(app_query)
    if not data:
        return {}
    return data.get("apps", {})


BLACKBOX_EXPORTER_MONITORING_PROVIDER = """
{
  providers: endpoint_monitoring_provider_v1 {
    name
    provider
    description
    ... on EndpointMonitoringProviderBlackboxExporter_v1 {
      blackboxExporter {
        module
        namespace {
          name
        }
        exporterUrl
      }
    }
  }
}
"""


def get_blackbox_exporter_monitoring_provider() -> dict:
    gqlapi = gql.get_api()
    data = gqlapi.query(BLACKBOX_EXPORTER_MONITORING_PROVIDER)
    if not data:
        return {}
    return data.get("providers", {})


JENKINS_CONFIGS = """
{
  jenkins_configs: jenkins_configs_v1 {
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
        version
        format
      }
      deleteMethod
    }
    type
    config
    config_path {
      content
    }
  }
}
"""


def get_jenkins_configs() -> list[dict[str, Any]]:
    gqlapi = gql.get_api()
    data = gqlapi.query(JENKINS_CONFIGS)
    if not data:
        return []
    return data.get("jenkins_configs") or []


TF_RESOURCES_PROVIDER_EXCLUSIONS_BY_PROVISIONER = """
{
  tf_provider_exclusions: app_interface_settings_v1 {
    terraformResourcesProviderExclusions {
      provider
      excludeProvisioners {
        name
      }
      excludeAllProvisioners
    }
  }
}
"""


def get_tf_resources_provider_exclusions_by_provisioner() -> (
    list[dict[str, Any]] | None
):
    gqlapi = gql.get_api()
    data = gqlapi.query(TF_RESOURCES_PROVIDER_EXCLUSIONS_BY_PROVISIONER)
    if not data:
        return None
    settings = data.get("tf_provider_exclusions")
    if (
        settings
        and len(settings) == 1
        and "terraformResourcesProviderExclusions" in settings[0]
    ):
        return settings[0]["terraformResourcesProviderExclusions"]
    return None


SCHEMAS_QUERY = """
{
  schemas: __schema {
    types {
      name
      fields {
        name
        type {
          kind
          name
          ofType {
            kind
            name
          }
        }
      }
    }
  }
}
"""


# TODO: replace with typed query following https://issues.redhat.com/browse/APPSRE-10983
def get_schemas() -> dict:
    gqlapi = gql.get_api()
    data = gqlapi.query(SCHEMAS_QUERY)
    if not data:
        return {}
    return data.get("schemas", {})
