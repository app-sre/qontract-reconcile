# pylint: disable=too-many-lines
# pylint: disable=too-many-instance-attributes
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class Query:
    app_interface_settings_v1: Optional[list[AppInterfaceSettingsV1]] = None
    app_interface_emails_v1: Optional[list[AppInterfaceEmailV1]] = None
    app_interface_slack_notifications_v1: Optional[list[AppInterfaceSlackNotificationV1]] = None
    credentials_requests_v1: Optional[list[CredentialsRequestV1]] = None
    users_v1: Optional[list[UserV1]] = None
    external_users_v1: Optional[list[ExternalUserV1]] = None
    bots_v1: Optional[list[BotV1]] = None
    roles_v1: Optional[list[RoleV1]] = None
    permissions_v1: Optional[list[PermissionV1]] = None
    awsgroups_v1: Optional[list[AWSGroupV1]] = None
    awsaccounts_v1: Optional[list[AWSAccountV1]] = None
    clusters_v1: Optional[list[ClusterV1]] = None
    kafka_clusters_v1: Optional[list[KafkaClusterV1]] = None
    namespaces_v1: Optional[list[NamespaceV1]] = None
    gcp_projects_v1: Optional[list[GcpProjectV1]] = None
    quay_orgs_v1: Optional[list[QuayOrgV1]] = None
    quay_instances_v1: Optional[list[QuayInstanceV1]] = None
    jenkins_instances_v1: Optional[list[JenkinsInstanceV1]] = None
    jenkins_configs_v1: Optional[list[JenkinsConfigV1]] = None
    jira_servers_v1: Optional[list[JiraServerV1]] = None
    jira_boards_v1: Optional[list[JiraBoardV1]] = None
    sendgrid_accounts_v1: Optional[list[SendGridAccountV1]] = None
    products_v1: Optional[list[ProductV1]] = None
    environments_v1: Optional[list[EnvironmentV1]] = None
    apps_v1: Optional[list[AppV1]] = None
    escalation_policies_1: Optional[list[AppEscalationPolicyV1]] = None
    resources_v1: Optional[list[ResourceV1]] = None
    vault_audit_backends_v1: Optional[list[VaultAuditV1]] = None
    vault_auth_backends_v1: Optional[list[VaultAuthV1]] = None
    vault_secret_engines_v1: Optional[list[VaultSecretEngineV1]] = None
    vault_roles_v1: Optional[list[VaultRoleV1]] = None
    vault_policies_v1: Optional[list[VaultPolicyV1]] = None
    dependencies_v1: Optional[list[DependencyV1]] = None
    githuborg_v1: Optional[list[GithubOrgV1]] = None
    gitlabinstance_v1: Optional[list[GitlabInstanceV1]] = None
    integrations_v1: Optional[list[IntegrationV1]] = None
    documents_v1: Optional[list[DocumentV1]] = None
    reports_v1: Optional[list[ReportV1]] = None
    sre_checkpoints_v1: Optional[list[SRECheckpointV1]] = None
    sentry_teams_v1: Optional[list[SentryTeamV1]] = None
    sentry_instances_v1: Optional[list[SentryInstanceV1]] = None
    app_interface_sql_queries_v1: Optional[list[AppInterfaceSqlQueryV1]] = None
    saas_files_v2: Optional[list[SaasFileV2]] = None
    pipelines_providers_v1: Optional[list[PipelinesProviderV1]] = None
    unleash_instances_v1: Optional[list[UnleashInstanceV1]] = None
    gabi_instances_v1: Optional[list[GabiInstanceV1]] = None
    template_tests_v1: Optional[list[TemplateTestV1]] = None
    dns_zone_v1: Optional[list[DnsZoneV1]] = None
    slack_workspaces_v1: Optional[list[SlackWorkspaceV1]] = None
    ocp_release_mirror_v1: Optional[list[OcpReleaseMirrorV1]] = None
    slo_document_v1: Optional[list[SLODocumentV1]] = None
    shared_resources_v1: Optional[list[SharedResourcesV1]] = None
    pagerduty_instances_v1: Optional[list[PagerDutyInstanceV1]] = None
    ocm_instances_v1: Optional[list[OpenShiftClusterManagerV1]] = None
    dyn_traffic_directors_v1: Optional[list[DynTrafficDirectorV1]] = None
    status_page_v1: Optional[list[StatusPageV1]] = None
    status_page_component_v1: Optional[list[StatusPageComponentV1]] = None
    endpoint_monitoring_provider_v1: Optional[list[EndpointMonitoringProviderV1]] = None


@dataclass
class AppInterfaceSettingsV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    vault: Optional[bool] = None
    kube_binary: Optional[str] = None
    pull_request_gateway: Optional[str] = None
    merge_request_gateway: Optional[str] = None
    saas_deploy_job_template: Optional[str] = None
    hash_length: Optional[int] = None
    smtp: Optional[SmtpSettingsV1] = None
    github_repo_invites: Optional[GithubRepoInvitesV1] = None
    dependencies: Optional[list[AppInterfaceDependencyMappingV1]] = None
    credentials: Optional[list[CredentialsRequestMapV1]] = None
    sql_query: Optional[SqlQuerySettingsV1] = None
    push_gateway_cluster: Optional[ClusterV1] = None
    alerting_services: Optional[list[str]] = None
    endpoint_monitoring_blackbox_exporter_modules: Optional[list[str]] = None
    ldap: Optional[LdapSettingsV1] = None


@dataclass
class SmtpSettingsV1:
    mail_address: Optional[str] = None
    credentials: Optional[VaultSecretV1] = None


@dataclass
class VaultSecretV1:
    path: Optional[str] = None
    field: Optional[str] = None
    _format: Optional[str] = None
    version: Optional[int] = None


@dataclass
class GithubRepoInvitesV1:
    credentials: Optional[VaultSecretV1] = None


@dataclass
class AppInterfaceDependencyMappingV1:
    _type: Optional[str] = None
    services: Optional[list[DependencyV1]] = None


@dataclass
class DependencyV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    statefulness: Optional[str] = None
    ops_model: Optional[str] = None
    status_page: Optional[str] = None
    _s_l_a: Optional[float] = None
    dependency_failure_impact: Optional[str] = None


@dataclass
class CredentialsRequestMapV1:
    name: Optional[str] = None
    secret: Optional[VaultSecretV1] = None


@dataclass
class SqlQuerySettingsV1:
    image_repository: Optional[str] = None
    pull_secret: Optional[NamespaceOpenshiftResourceVaultSecretV1] = None


@dataclass
class NamespaceOpenshiftResourceVaultSecretV1:
    provider: Optional[str] = None
    path: Optional[str] = None
    version: Optional[int] = None
    name: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    annotations: Optional[dict[str, str]] = None
    _type: Optional[str] = None
    validate_alertmanager_config: Optional[bool] = None
    alertmanager_config_key: Optional[str] = None


@dataclass
class NamespaceOpenshiftResourceV1:
    provider: Optional[str] = None


@dataclass
class ClusterV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    auth: Optional[ClusterAuthV1] = None
    observability_namespace: Optional[NamespaceV1] = None
    grafana_url: Optional[str] = None
    console_url: Optional[str] = None
    kibana_url: Optional[str] = None
    prometheus_url: Optional[str] = None
    alertmanager_url: Optional[str] = None
    server_url: Optional[str] = None
    elb_f_q_d_n: Optional[str] = None
    managed_groups: Optional[list[str]] = None
    managed_cluster_roles: Optional[bool] = None
    ocm: Optional[OpenShiftClusterManagerV1] = None
    spec: Optional[ClusterSpecV1] = None
    external_configuration: Optional[ClusterExternalConfigurationV1] = None
    upgrade_policy: Optional[ClusterUpgradePolicyV1] = None
    additional_routers: Optional[list[ClusterAdditionalRouterV1]] = None
    network: Optional[ClusterNetworkV1] = None
    machine_pools: Optional[list[ClusterMachinePoolV1]] = None
    peering: Optional[ClusterPeeringV1] = None
    addons: Optional[list[ClusterAddonV1]] = None
    insecure_skip_t_l_s_verify: Optional[bool] = None
    jump_host: Optional[ClusterJumpHostV1] = None
    automation_token: Optional[VaultSecretV1] = None
    cluster_admin_automation_token: Optional[VaultSecretV1] = None
    internal: Optional[bool] = None
    disable: Optional[DisableClusterAutomationsV1] = None
    aws_infrastructure_access: Optional[list[AWSInfrastructureAccessV1]] = None
    aws_infrastructure_management_accounts: Optional[list[AWSInfrastructureManagementAccountV1]] = None
    prometheus: Optional[ClusterPrometheusV1] = None
    namespaces: Optional[list[NamespaceV1]] = None


@dataclass
class ClusterAuthV1:
    service: Optional[str] = None


@dataclass
class NamespaceV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    delete: Optional[bool] = None
    description: Optional[str] = None
    grafana_url: Optional[str] = None
    cluster: Optional[ClusterV1] = None
    app: Optional[AppV1] = None
    environment: Optional[EnvironmentV1] = None
    limit_ranges: Optional[LimitRangeV1] = None
    quota: Optional[ResourceQuotaV1] = None
    network_policies_allow: Optional[list[NamespaceV1]] = None
    cluster_admin: Optional[bool] = None
    managed_roles: Optional[bool] = None
    managed_resource_types: Optional[list[str]] = None
    managed_resource_type_overrides: Optional[list[NamespaceManagedResourceTypeOverridesV1]] = None
    managed_resource_names: Optional[list[NamespaceManagedResourceNamesV1]] = None
    shared_resources: Optional[list[SharedResourcesV1]] = None
    openshift_resources: Optional[list[NamespaceOpenshiftResourceV1]] = None
    managed_terraform_resources: Optional[bool] = None
    terraform_resources: Optional[list[NamespaceTerraformResourceV1]] = None
    openshift_service_account_tokens: Optional[list[ServiceAccountTokenSpecV1]] = None
    kafka_cluster: Optional[KafkaClusterV1] = None


@dataclass
class AppV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    onboarding_status: Optional[str] = None
    grafana_urls: Optional[list[GrafanaDashboardUrlsV1]] = None
    sops_url: Optional[str] = None
    architecture_document: Optional[str] = None
    parent_app: Optional[AppV1] = None
    service_docs: Optional[list[str]] = None
    service_owners: Optional[list[OwnerV1]] = None
    service_notifications: Optional[list[OwnerV1]] = None
    dependencies: Optional[list[DependencyV1]] = None
    gcr_repos: Optional[list[AppGcrReposV1]] = None
    quay_repos: Optional[list[AppQuayReposV1]] = None
    escalation_policy: Optional[AppEscalationPolicyV1] = None
    end_points: Optional[list[AppEndPointsV1]] = None
    code_components: Optional[list[AppCodeComponentsV1]] = None
    sentry_projects: Optional[list[AppSentryProjectsV1]] = None
    status_page_components: Optional[list[StatusPageComponentV1]] = None
    namespaces: Optional[list[NamespaceV1]] = None
    children_apps: Optional[list[AppV1]] = None
    jenkins_configs: Optional[list[JenkinsConfigV1]] = None
    saas_files_v2: Optional[list[SaasFileV2]] = None
    sre_checkpoints: Optional[list[SRECheckpointV1]] = None


@dataclass
class GrafanaDashboardUrlsV1:
    title: Optional[str] = None
    url: Optional[str] = None


@dataclass
class OwnerV1:
    name: Optional[str] = None
    email: Optional[str] = None


@dataclass
class AppGcrReposV1:
    project: Optional[GcpProjectV1] = None
    items: Optional[list[AppGcrReposItemsV1]] = None


@dataclass
class GcpProjectV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    managed_teams: Optional[list[str]] = None
    automation_token: Optional[VaultSecretV1] = None
    push_credentials: Optional[VaultSecretV1] = None


@dataclass
class AppGcrReposItemsV1:
    name: Optional[str] = None
    description: Optional[str] = None
    public: Optional[bool] = None
    mirror: Optional[ContainerImageMirrorV1] = None


@dataclass
class ContainerImageMirrorV1:
    url: Optional[str] = None
    pull_credentials: Optional[VaultSecretV1] = None
    tags: Optional[list[str]] = None
    tags_exclude: Optional[list[str]] = None


@dataclass
class AppQuayReposV1:
    org: Optional[QuayOrgV1] = None
    teams: Optional[list[AppQuayReposTeamsV1]] = None
    notifications: Optional[list[AppQuayReposNotificationsV1]] = None
    items: Optional[list[AppQuayReposItemsV1]] = None


@dataclass
class QuayOrgV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    mirror: Optional[QuayOrgV1] = None
    managed_repos: Optional[bool] = None
    instance: Optional[QuayInstanceV1] = None
    server_url: Optional[str] = None
    managed_teams: Optional[list[str]] = None
    automation_token: Optional[VaultSecretV1] = None
    push_credentials: Optional[VaultSecretV1] = None


@dataclass
class QuayInstanceV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None


@dataclass
class AppQuayReposTeamsV1:
    permissions: Optional[list[PermissionQuayOrgTeamV1]] = None
    role: Optional[str] = None


@dataclass
class PermissionQuayOrgTeamV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    service: Optional[str] = None
    quay_org: Optional[QuayOrgV1] = None
    team: Optional[str] = None


@dataclass
class PermissionV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    service: Optional[str] = None


@dataclass
class AppQuayReposNotificationsV1:
    event: Optional[str] = None
    severity: Optional[str] = None
    method: Optional[str] = None
    escalation_policy: Optional[AppEscalationPolicyV1] = None
    verification_method: Optional[AppQuayReposNotificationVerificationMethodV1] = None


@dataclass
class AppEscalationPolicyV1:
    path: Optional[str] = None
    name: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    description: Optional[str] = None
    channels: Optional[AppEscalationPolicyChannelsV1] = None


@dataclass
class AppEscalationPolicyChannelsV1:
    slack_user_group: Optional[list[PermissionSlackUsergroupV1]] = None
    email: Optional[list[str]] = None
    pagerduty: Optional[PagerDutyTargetV1] = None
    jira_board: Optional[list[JiraBoardV1]] = None
    next_escalation_policy: Optional[AppEscalationPolicyV1] = None


@dataclass
class PermissionSlackUsergroupV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    service: Optional[str] = None
    handle: Optional[str] = None
    workspace: Optional[SlackWorkspaceV1] = None
    pagerduty: Optional[list[PagerDutyTargetV1]] = None
    channels: Optional[list[str]] = None
    owners_from_repos: Optional[list[str]] = None
    schedule: Optional[ScheduleV1] = None
    skip: Optional[bool] = None
    roles: Optional[list[RoleV1]] = None


@dataclass
class SlackWorkspaceV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    token: Optional[VaultSecretV1] = None
    api_client: Optional[SlackWorkspaceApiClientV1] = None
    integrations: Optional[list[SlackWorkspaceIntegrationV1]] = None
    managed_usergroups: Optional[list[str]] = None


@dataclass
class SlackWorkspaceApiClientV1:
    _global: Optional[SlackWorkspaceApiClientGlobalConfigV1] = None
    methods: Optional[list[SlackWorkspaceApiClientMethodConfigV1]] = None


@dataclass
class SlackWorkspaceApiClientGlobalConfigV1:
    max_retries: Optional[int] = None
    timeout: Optional[int] = None


@dataclass
class SlackWorkspaceApiClientMethodConfigV1:
    name: Optional[str] = None
    args: Optional[dict[str, str]] = None


@dataclass
class SlackWorkspaceIntegrationV1:
    name: Optional[str] = None
    token: Optional[VaultSecretV1] = None
    channel: Optional[str] = None
    icon_emoji: Optional[str] = None
    username: Optional[str] = None


@dataclass
class PagerDutyTargetV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    instance: Optional[PagerDutyInstanceV1] = None
    schedule_i_d: Optional[str] = None
    escalation_policy_i_d: Optional[str] = None


@dataclass
class PagerDutyInstanceV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    token: Optional[VaultSecretV1] = None


@dataclass
class ScheduleV1:
    name: Optional[str] = None
    description: Optional[str] = None
    schedule: Optional[list[ScheduleEntryV1]] = None


@dataclass
class ScheduleEntryV1:
    start: Optional[str] = None
    end: Optional[str] = None
    users: Optional[list[UserV1]] = None


@dataclass
class UserV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    org_username: Optional[str] = None
    github_username: Optional[str] = None
    quay_username: Optional[str] = None
    slack_username: Optional[str] = None
    pagerduty_username: Optional[str] = None
    aws_username: Optional[str] = None
    public_gpg_key: Optional[str] = None
    tag_on_merge_requests: Optional[bool] = None
    tag_on_cluster_updates: Optional[bool] = None
    roles: Optional[list[RoleV1]] = None
    requests: Optional[list[CredentialsRequestV1]] = None
    queries: Optional[list[AppInterfaceSqlQueryV1]] = None
    gabi_instances: Optional[list[GabiInstanceV1]] = None


@dataclass
class RoleV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    expiration_date: Optional[str] = None
    permissions: Optional[list[PermissionV1]] = None
    oidc_permissions: Optional[list[OidcPermissionV1]] = None
    tag_on_cluster_updates: Optional[bool] = None
    access: Optional[list[AccessV1]] = None
    aws_groups: Optional[list[AWSGroupV1]] = None
    user_policies: Optional[list[AWSUserPolicyV1]] = None
    sentry_teams: Optional[list[SentryTeamV1]] = None
    sentry_roles: Optional[list[SentryRoleV1]] = None
    sendgrid_accounts: Optional[list[SendGridAccountV1]] = None
    owned_saas_files: Optional[list[SaasFileV2]] = None
    users: Optional[list[UserV1]] = None
    bots: Optional[list[BotV1]] = None


@dataclass
class OidcPermissionV1:
    schema: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    service: Optional[str] = None
    description: Optional[str] = None


@dataclass
class AccessV1:
    namespace: Optional[NamespaceV1] = None
    role: Optional[str] = None
    cluster: Optional[ClusterV1] = None
    group: Optional[str] = None
    cluster_role: Optional[str] = None


@dataclass
class AWSGroupV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    account: Optional[AWSAccountV1] = None
    name: Optional[str] = None
    description: Optional[str] = None
    policies: Optional[list[str]] = None
    roles: Optional[list[RoleV1]] = None


@dataclass
class AWSAccountV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    console_url: Optional[str] = None
    uid: Optional[str] = None
    resources_default_region: Optional[str] = None
    supported_deployment_regions: Optional[list[str]] = None
    provider_version: Optional[str] = None
    terraform_username: Optional[str] = None
    account_owners: Optional[list[OwnerV1]] = None
    automation_token: Optional[VaultSecretV1] = None
    garbage_collection: Optional[bool] = None
    enable_deletion: Optional[bool] = None
    deletion_approvals: Optional[list[AWSAccountDeletionApprovalV1]] = None
    disable: Optional[DisableClusterAutomationsV1] = None
    delete_keys: Optional[list[str]] = None
    reset_passwords: Optional[list[AWSAccountResetPasswordV1]] = None
    premium_support: Optional[bool] = None
    partition: Optional[str] = None
    sharing: Optional[list[AWSAccountSharingOptionV1]] = None
    ecrs: Optional[list[AWSECRV1]] = None
    policies: Optional[list[AWSUserPolicyV1]] = None


@dataclass
class AWSAccountDeletionApprovalV1:
    _type: Optional[str] = None
    name: Optional[str] = None
    expiration: Optional[str] = None


@dataclass
class DisableClusterAutomationsV1:
    integrations: Optional[list[str]] = None
    e2e_tests: Optional[list[str]] = None


@dataclass
class AWSAccountResetPasswordV1:
    user: Optional[UserV1] = None
    request_id: Optional[str] = None


@dataclass
class AWSAccountSharingOptionV1:
    provider: Optional[str] = None
    account: Optional[AWSAccountV1] = None


@dataclass
class AWSECRV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    account: Optional[AWSAccountV1] = None
    name: Optional[str] = None
    description: Optional[str] = None
    region: Optional[str] = None


@dataclass
class AWSUserPolicyV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    account: Optional[AWSAccountV1] = None
    name: Optional[str] = None
    description: Optional[str] = None
    mandatory: Optional[bool] = None
    policy: Optional[dict[str, str]] = None


@dataclass
class SentryTeamV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    instance: Optional[SentryInstanceV1] = None


@dataclass
class SentryInstanceV1:
    schema: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    console_url: Optional[str] = None
    automation_token: Optional[VaultSecretV1] = None
    admin_user: Optional[VaultSecretV1] = None


@dataclass
class SentryRoleV1:
    role: Optional[str] = None
    instance: Optional[SentryInstanceV1] = None


@dataclass
class SendGridAccountV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    token: Optional[VaultSecretV1] = None


@dataclass
class SaasFileV2:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    app: Optional[AppV1] = None
    pipelines_provider: Optional[PipelinesProviderV1] = None
    slack: Optional[SlackOutputV1] = None
    managed_resource_types: Optional[list[str]] = None
    authentication: Optional[SaasFileAuthenticationV1] = None
    parameters: Optional[dict[str, str]] = None
    secret_parameters: Optional[list[SaasSecretParametersV1]] = None
    resource_templates: Optional[list[SaasResourceTemplateV2]] = None
    image_patterns: Optional[list[str]] = None
    takeover: Optional[bool] = None
    compare: Optional[bool] = None
    publish_job_logs: Optional[bool] = None
    cluster_admin: Optional[bool] = None
    use_channel_in_image_tag: Optional[bool] = None
    configurable_resources: Optional[bool] = None
    deploy_resources: Optional[DeployResourcesV1] = None
    roles: Optional[list[RoleV1]] = None


@dataclass
class PipelinesProviderV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None


@dataclass
class SlackOutputV1:
    workspace: Optional[SlackWorkspaceV1] = None
    channel: Optional[str] = None
    icon_emoji: Optional[str] = None
    username: Optional[str] = None
    output: Optional[str] = None
    notifications: Optional[SlackOutputNotificationsV1] = None


@dataclass
class SlackOutputNotificationsV1:
    start: Optional[bool] = None


@dataclass
class SaasFileAuthenticationV1:
    code: Optional[VaultSecretV1] = None
    image: Optional[VaultSecretV1] = None


@dataclass
class SaasSecretParametersV1:
    name: Optional[str] = None
    secret: Optional[VaultSecretV1] = None


@dataclass
class SaasResourceTemplateV2:
    name: Optional[str] = None
    url: Optional[str] = None
    path: Optional[str] = None
    provider: Optional[str] = None
    hash_length: Optional[int] = None
    parameters: Optional[dict[str, str]] = None
    secret_parameters: Optional[list[SaasSecretParametersV1]] = None
    targets: Optional[list[SaasResourceTemplateTargetV2]] = None


@dataclass
class SaasResourceTemplateTargetV2:
    namespace: Optional[NamespaceV1] = None
    ref: Optional[str] = None
    promotion: Optional[SaasResourceTemplateTargetPromotionV1] = None
    parameters: Optional[dict[str, str]] = None
    secret_parameters: Optional[list[SaasSecretParametersV1]] = None
    upstream: Optional[SaasResourceTemplateTargetUpstreamV1] = None
    disable: Optional[bool] = None
    delete: Optional[bool] = None


@dataclass
class SaasResourceTemplateTargetPromotionV1:
    auto: Optional[bool] = None
    publish: Optional[list[str]] = None
    subscribe: Optional[list[str]] = None
    promotion_data: Optional[list[PromotionDataV1]] = None


@dataclass
class PromotionDataV1:
    channel: Optional[str] = None
    data: Optional[list[PromotionChannelDataV1]] = None


@dataclass
class PromotionChannelDataV1:
    _type: Optional[str] = None


@dataclass
class SaasResourceTemplateTargetUpstreamV1:
    instance: Optional[JenkinsInstanceV1] = None
    name: Optional[str] = None


@dataclass
class JenkinsInstanceV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    server_url: Optional[str] = None
    token: Optional[VaultSecretV1] = None
    previous_urls: Optional[list[str]] = None
    plugins: Optional[list[str]] = None
    delete_method: Optional[str] = None
    managed_projects: Optional[list[str]] = None
    builds_cleanup_rules: Optional[list[JenkinsInstanceBuildsCleanupRulesV1]] = None


@dataclass
class JenkinsInstanceBuildsCleanupRulesV1:
    name: Optional[str] = None
    keep_hours: Optional[int] = None


@dataclass
class DeployResourcesV1:
    requests: Optional[ResourceRequirementsV1] = None
    limits: Optional[ResourceRequirementsV1] = None


@dataclass
class ResourceRequirementsV1:
    cpu: Optional[str] = None
    memory: Optional[str] = None


@dataclass
class BotV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    org_username: Optional[str] = None
    github_username: Optional[str] = None
    gitlab_username: Optional[str] = None
    openshift_serviceaccount: Optional[str] = None
    quay_username: Optional[str] = None
    owner: Optional[UserV1] = None
    roles: Optional[list[RoleV1]] = None


@dataclass
class CredentialsRequestV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    user: Optional[UserV1] = None
    credentials: Optional[str] = None


@dataclass
class AppInterfaceSqlQueryV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    namespace: Optional[NamespaceV1] = None
    identifier: Optional[str] = None
    requestor: Optional[UserV1] = None
    overrides: Optional[SqlEmailOverridesV1] = None
    output: Optional[str] = None
    schedule: Optional[str] = None
    query: Optional[str] = None
    queries: Optional[list[str]] = None


@dataclass
class SqlEmailOverridesV1:
    db_host: Optional[str] = None
    db_port: Optional[str] = None
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None


@dataclass
class GabiInstanceV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    signoff_managers: Optional[list[UserV1]] = None
    users: Optional[list[UserV1]] = None
    instances: Optional[list[GabiNamespaceV1]] = None
    expiration_date: Optional[str] = None


@dataclass
class GabiNamespaceV1:
    account: Optional[str] = None
    identifier: Optional[str] = None
    namespace: Optional[NamespaceV1] = None


@dataclass
class JiraBoardV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    server: Optional[JiraServerV1] = None
    severity_priority_mappings: Optional[JiraSeverityPriorityMappingsV1] = None
    slack: Optional[SlackOutputV1] = None


@dataclass
class JiraServerV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    server_url: Optional[str] = None
    token: Optional[VaultSecretV1] = None


@dataclass
class JiraSeverityPriorityMappingsV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    mappings: Optional[list[SeverityPriorityMappingV1]] = None


@dataclass
class SeverityPriorityMappingV1:
    severity: Optional[str] = None
    priority: Optional[str] = None


@dataclass
class AppQuayReposNotificationVerificationMethodV1:
    jira_board: Optional[JiraBoardV1] = None


@dataclass
class AppQuayReposItemsV1:
    name: Optional[str] = None
    description: Optional[str] = None
    public: Optional[bool] = None
    mirror: Optional[ContainerImageMirrorV1] = None


@dataclass
class AppEndPointsV1:
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    monitoring: Optional[list[AppEndPointMonitoringV1]] = None


@dataclass
class AppEndPointMonitoringV1:
    provider: Optional[EndpointMonitoringProviderV1] = None


@dataclass
class EndpointMonitoringProviderV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    metric_labels: Optional[dict[str, str]] = None
    timeout: Optional[str] = None
    check_interval: Optional[str] = None


@dataclass
class AppCodeComponentsV1:
    name: Optional[str] = None
    resource: Optional[str] = None
    url: Optional[str] = None
    gitlab_repo_owners: Optional[CodeComponentGitlabOwnersV1] = None
    gitlab_housekeeping: Optional[CodeComponentGitlabHousekeepingV1] = None
    jira: Optional[JiraServerV1] = None


@dataclass
class CodeComponentGitlabOwnersV1:
    enabled: Optional[bool] = None


@dataclass
class CodeComponentGitlabHousekeepingV1:
    enabled: Optional[bool] = None
    rebase: Optional[bool] = None
    days_interval: Optional[int] = None
    limit: Optional[int] = None
    enable_closing: Optional[bool] = None
    pipeline_timeout: Optional[int] = None


@dataclass
class AppSentryProjectsV1:
    team: Optional[SentryTeamV1] = None
    projects: Optional[list[SentryProjectItemsV1]] = None


@dataclass
class SentryProjectItemsV1:
    name: Optional[str] = None
    description: Optional[str] = None
    email_prefix: Optional[str] = None
    platform: Optional[str] = None
    sensitive_fields: Optional[list[str]] = None
    safe_fields: Optional[list[str]] = None
    auto_resolve_age: Optional[int] = None
    allowed_domains: Optional[list[str]] = None


@dataclass
class StatusPageComponentV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    page: Optional[StatusPageV1] = None
    group_name: Optional[str] = None
    status: Optional[list[StatusProviderV1]] = None
    apps: Optional[list[AppV1]] = None


@dataclass
class StatusPageV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    provider: Optional[str] = None
    api_url: Optional[str] = None
    credentials: Optional[VaultSecretV1] = None
    page_id: Optional[str] = None
    components: Optional[list[StatusPageComponentV1]] = None


@dataclass
class StatusProviderV1:
    provider: Optional[str] = None


@dataclass
class JenkinsConfigV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    app: Optional[AppV1] = None
    instance: Optional[JenkinsInstanceV1] = None
    _type: Optional[str] = None
    config: Optional[dict[str, str]] = None
    config_path: Optional[str] = None


@dataclass
class SRECheckpointV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    app: Optional[AppV1] = None
    date: Optional[str] = None
    issue: Optional[str] = None


@dataclass
class EnvironmentV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    product: Optional[ProductV1] = None
    parameters: Optional[dict[str, str]] = None
    secret_parameters: Optional[list[SaasSecretParametersV1]] = None
    depends_on: Optional[EnvironmentV1] = None
    namespaces: Optional[list[NamespaceV1]] = None


@dataclass
class ProductV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    product_owners: Optional[list[OwnerV1]] = None
    environments: Optional[list[EnvironmentV1]] = None


@dataclass
class LimitRangeV1:
    schema: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    limits: Optional[list[LimitRangeItemV1]] = None


@dataclass
class LimitRangeItemV1:
    default: Optional[ResourceValuesV1] = None
    default_request: Optional[ResourceValuesV1] = None
    max: Optional[ResourceValuesV1] = None
    max_limit_request_ratio: Optional[ResourceValuesV1] = None
    min: Optional[ResourceValuesV1] = None
    _type: Optional[str] = None


@dataclass
class ResourceValuesV1:
    cpu: Optional[str] = None
    memory: Optional[str] = None


@dataclass
class ResourceQuotaV1:
    schema: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    quotas: Optional[list[ResourceQuotaItemV1]] = None


@dataclass
class ResourceQuotaItemV1:
    name: Optional[str] = None
    resources: Optional[ResourceQuotaItemResourcesV1] = None
    scopes: Optional[list[str]] = None


@dataclass
class ResourceQuotaItemResourcesV1:
    limits: Optional[ResourceValuesV1] = None
    requests: Optional[ResourceValuesV1] = None
    pods: Optional[int] = None


@dataclass
class NamespaceManagedResourceTypeOverridesV1:
    resource: Optional[str] = None
    override: Optional[str] = None


@dataclass
class NamespaceManagedResourceNamesV1:
    resource: Optional[str] = None
    resource_names: Optional[list[str]] = None


@dataclass
class SharedResourcesV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    openshift_resources: Optional[list[NamespaceOpenshiftResourceV1]] = None
    openshift_service_account_tokens: Optional[list[ServiceAccountTokenSpecV1]] = None
    terraform_resources: Optional[list[NamespaceTerraformResourceV1]] = None


@dataclass
class ServiceAccountTokenSpecV1:
    name: Optional[str] = None
    namespace: Optional[NamespaceV1] = None
    service_account_name: Optional[str] = None


@dataclass
class NamespaceTerraformResourceV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    identifier: Optional[str] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceOutputFormatV1:
    provider: Optional[str] = None


@dataclass
class KafkaClusterV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    ocm: Optional[OpenShiftClusterManagerV1] = None
    spec: Optional[KafkaClusterSpecV1] = None
    namespaces: Optional[list[NamespaceV1]] = None


@dataclass
class OpenShiftClusterManagerV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    access_token_client_id: Optional[str] = None
    access_token_url: Optional[str] = None
    offline_token: Optional[VaultSecretV1] = None
    blocked_versions: Optional[list[str]] = None
    clusters: Optional[list[ClusterV1]] = None


@dataclass
class KafkaClusterSpecV1:
    provider: Optional[str] = None
    region: Optional[str] = None
    multi_az: Optional[bool] = None


@dataclass
class ClusterSpecV1:
    _id: Optional[str] = None
    external_id: Optional[str] = None
    provider: Optional[str] = None
    region: Optional[str] = None
    channel: Optional[str] = None
    version: Optional[str] = None
    initial_version: Optional[str] = None
    multi_az: Optional[bool] = None
    nodes: Optional[int] = None
    instance_type: Optional[str] = None
    storage: Optional[int] = None
    load_balancers: Optional[int] = None
    private: Optional[bool] = None
    provision_shard_id: Optional[str] = None
    autoscale: Optional[ClusterSpecAutoScaleV1] = None
    disable_user_workload_monitoring: Optional[bool] = None


@dataclass
class ClusterSpecAutoScaleV1:
    min_replicas: Optional[int] = None
    max_replicas: Optional[int] = None


@dataclass
class ClusterExternalConfigurationV1:
    labels: Optional[dict[str, str]] = None


@dataclass
class ClusterUpgradePolicyV1:
    schedule_type: Optional[str] = None
    schedule: Optional[str] = None
    workloads: Optional[list[str]] = None
    conditions: Optional[ClusterUpgradePolicyConditionsV1] = None


@dataclass
class ClusterUpgradePolicyConditionsV1:
    soak_days: Optional[int] = None
    mutexes: Optional[list[str]] = None


@dataclass
class ClusterAdditionalRouterV1:
    private: Optional[bool] = None
    route_selectors: Optional[dict[str, str]] = None


@dataclass
class ClusterNetworkV1:
    _type: Optional[str] = None
    vpc: Optional[str] = None
    service: Optional[str] = None
    pod: Optional[str] = None


@dataclass
class ClusterMachinePoolV1:
    _id: Optional[str] = None
    instance_type: Optional[str] = None
    replicas: Optional[int] = None
    labels: Optional[dict[str, str]] = None
    taints: Optional[list[TaintV1]] = None


@dataclass
class TaintV1:
    key: Optional[str] = None
    value: Optional[str] = None
    effect: Optional[str] = None


@dataclass
class ClusterPeeringV1:
    connections: Optional[list[ClusterPeeringConnectionV1]] = None


@dataclass
class ClusterPeeringConnectionV1:
    provider: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    manage_routes: Optional[bool] = None
    delete: Optional[bool] = None


@dataclass
class ClusterAddonV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[list[ClusterAddonParametersV1]] = None


@dataclass
class ClusterAddonParametersV1:
    _id: Optional[str] = None
    value: Optional[str] = None


@dataclass
class ClusterJumpHostV1:
    hostname: Optional[str] = None
    known_hosts: Optional[str] = None
    user: Optional[str] = None
    port: Optional[int] = None
    identity: Optional[VaultSecretV1] = None


@dataclass
class AWSInfrastructureAccessV1:
    aws_group: Optional[AWSGroupV1] = None
    access_level: Optional[str] = None


@dataclass
class AWSInfrastructureManagementAccountV1:
    account: Optional[AWSAccountV1] = None
    access_level: Optional[str] = None
    default: Optional[bool] = None


@dataclass
class ClusterPrometheusV1:
    url: Optional[str] = None
    auth: Optional[VaultSecretV1] = None


@dataclass
class LdapSettingsV1:
    server_url: Optional[str] = None
    base_dn: Optional[str] = None


@dataclass
class AppInterfaceEmailV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    subject: Optional[str] = None
    _to: Optional[AppInterfaceEmailAudienceV1] = None
    body: Optional[str] = None


@dataclass
class AppInterfaceEmailAudienceV1:
    aliases: Optional[list[str]] = None
    services: Optional[list[AppV1]] = None
    clusters: Optional[list[ClusterV1]] = None
    namespaces: Optional[list[NamespaceV1]] = None
    aws_accounts: Optional[list[AWSAccountV1]] = None
    roles: Optional[list[RoleV1]] = None
    users: Optional[list[UserV1]] = None


@dataclass
class AppInterfaceSlackNotificationV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    subject: Optional[str] = None
    channel: Optional[str] = None
    _to: Optional[AppInterfaceSlackNotificationAudienceV1] = None
    body: Optional[str] = None


@dataclass
class AppInterfaceSlackNotificationAudienceV1:
    users: Optional[list[str]] = None


@dataclass
class ExternalUserV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    github_username: Optional[str] = None
    sponsors: Optional[list[UserV1]] = None


@dataclass
class ResourceV1:
    path: Optional[str] = None
    content: Optional[str] = None
    sha256sum: Optional[str] = None
    schema: Optional[str] = None


@dataclass
class VaultAuditV1:
    _path: Optional[str] = None
    _type: Optional[str] = None
    description: Optional[str] = None
    options: Optional[VaultAuditOptionsV1] = None


@dataclass
class VaultAuditOptionsV1:
    _type: Optional[str] = None


@dataclass
class VaultAuthV1:
    _path: Optional[str] = None
    _type: Optional[str] = None
    description: Optional[str] = None
    settings: Optional[VaultAuthSettingsV1] = None
    policy_mappings: Optional[list[VaultPolicyMappingV1]] = None


@dataclass
class VaultAuthSettingsV1:
    config: Optional[VaultAuthConfigV1] = None


@dataclass
class VaultAuthConfigV1:
    _type: Optional[str] = None


@dataclass
class VaultPolicyMappingV1:
    github_team: Optional[PermissionGithubOrgTeamV1] = None
    policies: Optional[list[VaultPolicyV1]] = None


@dataclass
class PermissionGithubOrgTeamV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    service: Optional[str] = None
    org: Optional[str] = None
    team: Optional[str] = None
    role: Optional[str] = None


@dataclass
class VaultPolicyV1:
    name: Optional[str] = None
    rules: Optional[str] = None


@dataclass
class VaultSecretEngineV1:
    _path: Optional[str] = None
    _type: Optional[str] = None
    description: Optional[str] = None
    options: Optional[VaultSecretEngineOptionsV1] = None


@dataclass
class VaultSecretEngineOptionsV1:
    _type: Optional[str] = None


@dataclass
class VaultRoleV1:
    name: Optional[str] = None
    _type: Optional[str] = None
    mount: Optional[str] = None
    options: Optional[VaultRoleOptionsV1] = None


@dataclass
class VaultRoleOptionsV1:
    _type: Optional[str] = None


@dataclass
class GithubOrgV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    two_factor_authentication: Optional[bool] = None
    default: Optional[bool] = None
    token: Optional[VaultSecretV1] = None
    managed_teams: Optional[list[str]] = None


@dataclass
class GitlabInstanceV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    backup_orgs: Optional[list[str]] = None
    managed_groups: Optional[list[str]] = None
    project_requests: Optional[list[GitlabProjectsV1]] = None
    url: Optional[str] = None
    token: Optional[VaultSecretV1] = None
    ssl_verify: Optional[bool] = None


@dataclass
class GitlabProjectsV1:
    group: Optional[str] = None
    projects: Optional[list[str]] = None


@dataclass
class IntegrationV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    upstream: Optional[str] = None
    schemas: Optional[list[str]] = None
    pr_check: Optional[IntegrationPrCheckV1] = None


@dataclass
class IntegrationPrCheckV1:
    cmd: Optional[str] = None
    state: Optional[bool] = None
    sqs: Optional[bool] = None
    disabled: Optional[bool] = None
    always_run: Optional[bool] = None
    no_validate_schemas: Optional[bool] = None
    run_for_valid_saas_file_changes: Optional[bool] = None


@dataclass
class DocumentV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    app: Optional[AppV1] = None
    name: Optional[str] = None
    content_path: Optional[str] = None


@dataclass
class ReportV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    app: Optional[AppV1] = None
    name: Optional[str] = None
    date: Optional[str] = None
    content_format_version: Optional[str] = None
    content: Optional[str] = None


@dataclass
class UnleashInstanceV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    token: Optional[VaultSecretV1] = None
    notifications: Optional[UnleashNotificationsV1] = None
    feature_toggles: Optional[list[UnleashFeatureToggleV1]] = None


@dataclass
class UnleashNotificationsV1:
    slack: Optional[list[SlackOutputV1]] = None


@dataclass
class UnleashFeatureToggleV1:
    name: Optional[str] = None
    enabled: Optional[bool] = None
    reason: Optional[str] = None


@dataclass
class TemplateTestV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    resource_path: Optional[str] = None
    expected_result: Optional[str] = None


@dataclass
class DnsZoneV1:
    schema: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    account: Optional[AWSAccountV1] = None
    vpc: Optional[AWSVPCV1] = None
    origin: Optional[str] = None
    unmanaged_record_names: Optional[list[str]] = None
    records: Optional[list[DnsRecordV1]] = None


@dataclass
class AWSVPCV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    account: Optional[AWSAccountV1] = None
    name: Optional[str] = None
    description: Optional[str] = None
    vpc_id: Optional[str] = None
    cidr_block: Optional[str] = None
    region: Optional[str] = None
    subnets: Optional[list[AWSSubnetV1]] = None


@dataclass
class AWSSubnetV1:
    _id: Optional[str] = None


@dataclass
class DnsRecordV1:
    name: Optional[str] = None
    _type: Optional[str] = None
    ttl: Optional[int] = None
    alias: Optional[DnsRecordAliasV1] = None
    weighted_routing_policy: Optional[DnsRecordWeightedRoutingPolicyV1] = None
    set_identifier: Optional[str] = None
    records: Optional[list[str]] = None
    _healthcheck: Optional[DnsRecordHealthcheckV1] = None
    _target_cluster: Optional[ClusterV1] = None
    _target_namespace_zone: Optional[DnsNamespaceZoneV1] = None


@dataclass
class DnsRecordAliasV1:
    name: Optional[str] = None
    zone_id: Optional[str] = None
    evaluate_target_health: Optional[bool] = None


@dataclass
class DnsRecordWeightedRoutingPolicyV1:
    weight: Optional[int] = None


@dataclass
class DnsRecordHealthcheckV1:
    fqdn: Optional[str] = None
    port: Optional[int] = None
    _type: Optional[str] = None
    resource_path: Optional[str] = None
    failure_threshold: Optional[int] = None
    request_interval: Optional[int] = None
    search_string: Optional[str] = None


@dataclass
class DnsNamespaceZoneV1:
    namespace: Optional[NamespaceV1] = None
    name: Optional[str] = None


@dataclass
class OcpReleaseMirrorV1:
    hive_cluster: Optional[ClusterV1] = None
    ecr_resources_namespace: Optional[NamespaceV1] = None
    ocp_release_ecr_identifier: Optional[str] = None
    ocp_art_dev_ecr_identifier: Optional[str] = None
    quay_target_orgs: Optional[list[QuayOrgV1]] = None
    mirror_channels: Optional[list[str]] = None


@dataclass
class SLODocumentV1:
    schema: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    namespaces: Optional[list[NamespaceV1]] = None
    slos: Optional[list[SLODocumentSLOV1]] = None


@dataclass
class SLODocumentSLOV1:
    name: Optional[str] = None
    _s_l_i_type: Optional[str] = None
    _s_l_i_specification: Optional[str] = None
    _s_l_o_details: Optional[str] = None
    _s_l_o_target: Optional[float] = None
    _s_l_o_parameters: Optional[SLODocumentSLOSLOParametersV1] = None
    expr: Optional[str] = None
    _s_l_o_target_unit: Optional[str] = None
    prometheus_rules: Optional[str] = None
    prometheus_rules_tests: Optional[str] = None
    dashboard: Optional[str] = None


@dataclass
class SLODocumentSLOSLOParametersV1:
    window: Optional[str] = None


@dataclass
class DynTrafficDirectorV1:
    name: Optional[str] = None
    ttl: Optional[int] = None
    records: Optional[list[DynTrafficDirectorRecordV1]] = None


@dataclass
class DynTrafficDirectorRecordV1:
    hostname: Optional[str] = None
    cluster: Optional[ClusterV1] = None
    weight: Optional[int] = None


@dataclass
class VaultAuditOptionsFileV1:
    _type: Optional[str] = None
    file_path: Optional[str] = None
    log_raw: Optional[str] = None
    hmac_accessor: Optional[str] = None
    mode: Optional[str] = None
    _format: Optional[str] = None
    prefix: Optional[str] = None


@dataclass
class VaultAuthConfigGithubV1:
    _type: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[str] = None
    max_ttl: Optional[str] = None
    ttl: Optional[str] = None


@dataclass
class VaultAuthConfigOidcV1:
    _type: Optional[str] = None
    oidc_discovery_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    default_role: Optional[str] = None


@dataclass
class VaultSecretEngineOptionsKVV1:
    _type: Optional[str] = None
    version: Optional[str] = None


@dataclass
class VaultApproleOptionsV1:
    _type: Optional[str] = None
    bind_secret_id: Optional[str] = None
    local_secret_ids: Optional[str] = None
    token_period: Optional[str] = None
    secret_id_num_uses: Optional[str] = None
    secret_id_ttl: Optional[str] = None
    token_explicit_max_ttl: Optional[str] = None
    token_max_ttl: Optional[str] = None
    token_no_default_policy: Optional[bool] = None
    token_num_uses: Optional[str] = None
    token_ttl: Optional[str] = None
    token_type: Optional[str] = None
    token_policies: Optional[list[str]] = None
    policies: Optional[list[str]] = None
    secret_id_bound_cidrs: Optional[list[str]] = None
    token_bound_cidrs: Optional[list[str]] = None


@dataclass
class VaultRoleOidcOptionsV1:
    _type: Optional[str] = None
    allowed_redirect_uris: Optional[list[str]] = None
    bound_audiences: Optional[list[str]] = None
    bound_claims: Optional[dict[str, str]] = None
    bound_claims_type: Optional[str] = None
    bound_subject: Optional[str] = None
    claim_mappings: Optional[dict[str, str]] = None
    clock_skew_leeway: Optional[str] = None
    expiration_leeway: Optional[str] = None
    groups_claim: Optional[str] = None
    max_age: Optional[str] = None
    not_before_leeway: Optional[str] = None
    oidc_scopes: Optional[list[str]] = None
    role_type: Optional[str] = None
    token_ttl: Optional[str] = None
    token_max_ttl: Optional[str] = None
    token_explicit_max_ttl: Optional[str] = None
    token_type: Optional[str] = None
    token_period: Optional[str] = None
    token_policies: Optional[list[str]] = None
    token_bound_cidrs: Optional[list[str]] = None
    token_no_default_policy: Optional[bool] = None
    token_num_uses: Optional[str] = None
    user_claim: Optional[str] = None
    verbose_oidc_logging: Optional[bool] = None


@dataclass
class KeyValueV1:
    key: Optional[str] = None
    value: Optional[str] = None


@dataclass
class ClusterAuthGithubOrgV1:
    service: Optional[str] = None
    org: Optional[str] = None


@dataclass
class ClusterAuthGithubOrgTeamV1:
    service: Optional[str] = None
    org: Optional[str] = None
    team: Optional[str] = None


@dataclass
class ClusterAuthOIDCV1:
    service: Optional[str] = None


@dataclass
class ClusterPeeringConnectionAccountV1:
    provider: Optional[str] = None
    name: Optional[str] = None
    vpc: Optional[AWSVPCV1] = None
    description: Optional[str] = None
    manage_routes: Optional[bool] = None
    delete: Optional[bool] = None
    assume_role: Optional[str] = None


@dataclass
class ClusterPeeringConnectionAccountVPCMeshV1:
    provider: Optional[str] = None
    name: Optional[str] = None
    account: Optional[AWSAccountV1] = None
    description: Optional[str] = None
    tags: Optional[dict[str, str]] = None
    manage_routes: Optional[bool] = None
    delete: Optional[bool] = None


@dataclass
class ClusterPeeringConnectionAccountTGWV1:
    provider: Optional[str] = None
    name: Optional[str] = None
    account: Optional[AWSAccountV1] = None
    description: Optional[str] = None
    tags: Optional[dict[str, str]] = None
    manage_routes: Optional[bool] = None
    manage_security_groups: Optional[bool] = None
    cidr_block: Optional[str] = None
    delete: Optional[bool] = None
    assume_role: Optional[str] = None


@dataclass
class ClusterPeeringConnectionClusterRequesterV1:
    provider: Optional[str] = None
    name: Optional[str] = None
    cluster: Optional[ClusterV1] = None
    description: Optional[str] = None
    manage_routes: Optional[bool] = None
    delete: Optional[bool] = None
    assume_role: Optional[str] = None


@dataclass
class ClusterPeeringConnectionClusterAccepterV1:
    provider: Optional[str] = None
    name: Optional[str] = None
    cluster: Optional[ClusterV1] = None
    aws_infrastructure_management_account: Optional[AWSAccountV1] = None
    description: Optional[str] = None
    manage_routes: Optional[bool] = None
    delete: Optional[bool] = None
    assume_role: Optional[str] = None


@dataclass
class AWSAccountSharingOptionAMIV1:
    provider: Optional[str] = None
    account: Optional[AWSAccountV1] = None
    regex: Optional[str] = None
    region: Optional[str] = None


@dataclass
class AWSS3EventNotificationV1:
    event_type: Optional[list[str]] = None
    destination: Optional[str] = None
    destination_type: Optional[str] = None
    filter_prefix: Optional[str] = None
    filter_suffix: Optional[str] = None


@dataclass
class ACMDomainV1:
    domain_name: Optional[str] = None
    alternate_names: Optional[list[str]] = None


@dataclass
class NamespaceOpenshiftResourceResourceV1:
    provider: Optional[str] = None
    path: Optional[str] = None
    validate_json: Optional[bool] = None
    validate_alertmanager_config: Optional[bool] = None
    alertmanager_config_key: Optional[str] = None


@dataclass
class NamespaceOpenshiftResourceResourceTemplateV1:
    provider: Optional[str] = None
    path: Optional[str] = None
    _type: Optional[str] = None
    variables: Optional[dict[str, str]] = None
    validate_alertmanager_config: Optional[bool] = None
    alertmanager_config_key: Optional[str] = None


@dataclass
class NamespaceOpenshiftResourceRouteV1:
    provider: Optional[str] = None
    path: Optional[str] = None
    vault_tls_secret_path: Optional[str] = None
    vault_tls_secret_version: Optional[int] = None


@dataclass
class NamespaceTerraformResourceGenericSecretOutputFormatV1:
    provider: Optional[str] = None
    data: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceASGV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    defaults: Optional[str] = None
    cloudinit_configs: Optional[list[CloudinitConfigV1]] = None
    variables: Optional[dict[str, str]] = None
    image: Optional[ASGImageV1] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class CloudinitConfigV1:
    filename: Optional[str] = None
    content_type: Optional[str] = None
    content: Optional[str] = None


@dataclass
class ASGImageV1:
    tag_name: Optional[str] = None
    url: Optional[str] = None
    ref: Optional[str] = None
    upstream: Optional[SaasResourceTemplateTargetUpstreamV1] = None


@dataclass
class NamespaceTerraformResourceSecretsManagerV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    secret: Optional[VaultSecretV1] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceS3CloudFrontPublicKeyV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    secret: Optional[VaultSecretV1] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceACMV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    secret: Optional[VaultSecretV1] = None
    domain: Optional[ACMDomainV1] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceElasticSearchV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    defaults: Optional[str] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None
    publish_log_types: Optional[list[str]] = None


@dataclass
class NamespaceTerraformResourceRDSV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    defaults: Optional[str] = None
    availability_zone: Optional[str] = None
    parameter_group: Optional[str] = None
    overrides: Optional[dict[str, str]] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    output_resource_db_name: Optional[str] = None
    reset_password: Optional[str] = None
    enhanced_monitoring: Optional[bool] = None
    replica_source: Optional[str] = None
    ca_cert: Optional[VaultSecretV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceS3V1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    defaults: Optional[str] = None
    overrides: Optional[dict[str, str]] = None
    event_notifications: Optional[list[AWSS3EventNotificationV1]] = None
    sqs_identifier: Optional[str] = None
    s3_events: Optional[list[str]] = None
    bucket_policy: Optional[dict[str, str]] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    storage_class: Optional[str] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceServiceAccountAWSInfrastructureAccessV1:
    cluster: Optional[ClusterV1] = None
    access_level: Optional[str] = None
    assume_role: Optional[str] = None


@dataclass
class NamespaceTerraformResourceServiceAccountV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    identifier: Optional[str] = None
    variables: Optional[dict[str, str]] = None
    policies: Optional[list[str]] = None
    user_policy: Optional[dict[str, str]] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    aws_infrastructure_access: Optional[NamespaceTerraformResourceServiceAccountAWSInfrastructureAccessV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class AssumeRoleV1:
    _a_w_s: Optional[list[str]] = None
    _service: Optional[list[str]] = None


@dataclass
class NamespaceTerraformResourceRoleV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    identifier: Optional[str] = None
    assume_role: Optional[AssumeRoleV1] = None
    assume_condition: Optional[dict[str, str]] = None
    inline_policy: Optional[dict[str, str]] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceElastiCacheV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    identifier: Optional[str] = None
    defaults: Optional[str] = None
    parameter_group: Optional[str] = None
    region: Optional[str] = None
    overrides: Optional[dict[str, str]] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class SQSQueuesSpecsV1:
    defaults: Optional[str] = None
    queues: Optional[list[KeyValueV1]] = None


@dataclass
class NamespaceTerraformResourceSQSV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    specs: Optional[list[SQSQueuesSpecsV1]] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class DynamoDBTableSpecsV1:
    defaults: Optional[str] = None
    tables: Optional[list[KeyValueV1]] = None


@dataclass
class NamespaceTerraformResourceDynamoDBV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    specs: Optional[list[DynamoDBTableSpecsV1]] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceECRV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    mirror: Optional[ContainerImageMirrorV1] = None
    public: Optional[bool] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceS3CloudFrontV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    defaults: Optional[str] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    storage_class: Optional[str] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceS3SQSV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    kms_encryption: Optional[bool] = None
    defaults: Optional[str] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    storage_class: Optional[str] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceCloudWatchV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    defaults: Optional[str] = None
    es_identifier: Optional[str] = None
    filter_pattern: Optional[str] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceKMSV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    defaults: Optional[str] = None
    overrides: Optional[dict[str, str]] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceKinesisV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    defaults: Optional[str] = None
    overrides: Optional[dict[str, str]] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceALBV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    identifier: Optional[str] = None
    region: Optional[str] = None
    vpc: Optional[AWSVPCV1] = None
    certificate_arn: Optional[str] = None
    idle_timeout: Optional[int] = None
    targets: Optional[list[NamespaceTerraformResourceALBTargetsV1]] = None
    rules: Optional[list[NamespaceTerraformResourceALBRulesV1]] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class NamespaceTerraformResourceALBTargetsV1:
    name: Optional[str] = None
    default: Optional[bool] = None
    ips: Optional[list[str]] = None
    openshift_service: Optional[str] = None


@dataclass
class NamespaceTerraformResourceALBRulesV1:
    condition: Optional[NamespaceTerraformResourceALBConditonV1] = None
    action: Optional[list[NamespaceTerraformResourceALBActionV1]] = None


@dataclass
class NamespaceTerraformResourceALBConditonV1:
    path: Optional[str] = None
    methods: Optional[list[str]] = None


@dataclass
class NamespaceTerraformResourceALBActionV1:
    target: Optional[str] = None
    weight: Optional[int] = None


@dataclass
class NamespaceTerraformResourceRoute53ZoneV1:
    provider: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    identifier: Optional[str] = None
    name: Optional[str] = None
    output_resource_name: Optional[str] = None
    output_format: Optional[NamespaceTerraformResourceOutputFormatV1] = None
    annotations: Optional[dict[str, str]] = None


@dataclass
class SaasResourceTemplateV1:
    name: Optional[str] = None
    url: Optional[str] = None
    path: Optional[str] = None
    provider: Optional[str] = None
    hash_length: Optional[int] = None
    parameters: Optional[dict[str, str]] = None
    secret_parameters: Optional[list[SaasSecretParametersV1]] = None
    targets: Optional[list[SaasResourceTemplateTargetV1]] = None


@dataclass
class SaasResourceTemplateTargetV1:
    namespace: Optional[NamespaceV1] = None
    ref: Optional[str] = None
    promotion: Optional[SaasResourceTemplateTargetPromotionV1] = None
    parameters: Optional[dict[str, str]] = None
    secret_parameters: Optional[list[SaasSecretParametersV1]] = None
    upstream: Optional[str] = None
    disable: Optional[bool] = None
    delete: Optional[bool] = None


@dataclass
class ParentSaasPromotionV1:
    _type: Optional[str] = None
    parent_saas: Optional[str] = None
    target_config_hash: Optional[str] = None


@dataclass
class PipelinesProviderTektonV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    defaults: Optional[PipelinesProviderTektonProviderDefaultsV1] = None
    namespace: Optional[NamespaceV1] = None
    retention: Optional[PipelinesProviderRetentionV1] = None
    task_templates: Optional[list[PipelinesProviderTektonObjectTemplateV1]] = None
    pipeline_templates: Optional[PipelinesProviderPipelineTemplatesV1] = None
    deploy_resources: Optional[DeployResourcesV1] = None


@dataclass
class PipelinesProviderTektonProviderDefaultsV1:
    name: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    description: Optional[str] = None
    retention: Optional[PipelinesProviderRetentionV1] = None
    task_templates: Optional[list[PipelinesProviderTektonObjectTemplateV1]] = None
    pipeline_templates: Optional[PipelinesProviderPipelineTemplatesV1] = None
    deploy_resources: Optional[DeployResourcesV1] = None


@dataclass
class PipelinesProviderRetentionV1:
    days: Optional[int] = None
    minimum: Optional[int] = None


@dataclass
class PipelinesProviderTektonObjectTemplateV1:
    name: Optional[str] = None
    _type: Optional[str] = None
    path: Optional[str] = None
    variables: Optional[dict[str, str]] = None


@dataclass
class PipelinesProviderPipelineTemplatesV1:
    openshift_saas_deploy: Optional[PipelinesProviderTektonObjectTemplateV1] = None


@dataclass
class OidcPermissionVaultV1:
    schema: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    service: Optional[str] = None
    description: Optional[str] = None
    vault_policies: Optional[list[VaultPolicyV1]] = None


@dataclass
class PermissionGithubOrgV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    service: Optional[str] = None
    org: Optional[str] = None
    role: Optional[str] = None


@dataclass
class PermissionJenkinsRoleV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    service: Optional[str] = None
    instance: Optional[JenkinsInstanceV1] = None
    role: Optional[str] = None
    token: Optional[VaultSecretV1] = None


@dataclass
class PermissionGitlabGroupMembershipV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    service: Optional[str] = None
    group: Optional[str] = None
    access: Optional[str] = None


@dataclass
class EndpointMonitoringProviderBlackboxExporterV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    metric_labels: Optional[dict[str, str]] = None
    timeout: Optional[str] = None
    check_interval: Optional[str] = None
    blackbox_exporter: Optional[EndpointMonitoringProviderBlackboxExporterSettingsV1] = None


@dataclass
class EndpointMonitoringProviderBlackboxExporterSettingsV1:
    module: Optional[str] = None
    namespace: Optional[NamespaceV1] = None
    exporter_url: Optional[str] = None


@dataclass
class EndpointMonitoringProviderSignalFxV1:
    schema: Optional[str] = None
    path: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    metric_labels: Optional[dict[str, str]] = None
    timeout: Optional[str] = None
    check_interval: Optional[str] = None
    signal_fx: Optional[EndpointMonitoringProviderSignalFxSettingsV1] = None


@dataclass
class EndpointMonitoringProviderSignalFxSettingsV1:
    namespace: Optional[NamespaceV1] = None
    exporter_url: Optional[str] = None
    target_filter_label: Optional[str] = None


@dataclass
class PrometheusAlertsStatusProviderV1:
    provider: Optional[str] = None
    prometheus_alerts: Optional[PrometheusAlertsStatusProviderConfigV1] = None


@dataclass
class PrometheusAlertsStatusProviderConfigV1:
    namespace: Optional[list[NamespaceV1]] = None
    matchers: Optional[list[PrometheusAlertMatcherV1]] = None


@dataclass
class PrometheusAlertMatcherV1:
    match_expression: Optional[PrometheusAlertMatcherExpressionV1] = None
    component_status: Optional[str] = None


@dataclass
class PrometheusAlertMatcherExpressionV1:
    alert: Optional[str] = None
    labels: Optional[dict[str, str]] = None


@dataclass
class ManualStatusProviderV1:
    provider: Optional[str] = None
    manual: Optional[ManualStatusProviderConfigV1] = None


@dataclass
class ManualStatusProviderConfigV1:
    component_status: Optional[str] = None
    _from: Optional[str] = None
    until: Optional[str] = None
