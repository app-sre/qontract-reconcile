import sgqlc.types


qontract_schema = sgqlc.types.Schema()



########################################################################
# Scalars and Enumerations
########################################################################
Boolean = sgqlc.types.Boolean

Float = sgqlc.types.Float

Int = sgqlc.types.Int

class JSON(sgqlc.types.Scalar):
    __schema__ = qontract_schema


String = sgqlc.types.String


########################################################################
# Input Objects
########################################################################

########################################################################
# Output Objects and Interfaces
########################################################################
class ACMDomain_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('domain_name', 'alternate_names')
    domain_name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='domain_name')
    alternate_names = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='alternate_names')


class ASGImage_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('tag_name', 'url', 'ref', 'upstream')
    tag_name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='tag_name')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    ref = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='ref')
    upstream = sgqlc.types.Field('SaasResourceTemplateTargetUpstream_v1', graphql_name='upstream')


class AWSAccountDeletionApproval_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('type', 'name', 'expiration')
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    expiration = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='expiration')


class AWSAccountResetPassword_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('user', 'request_id')
    user = sgqlc.types.Field(sgqlc.types.non_null('User_v1'), graphql_name='user')
    request_id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='requestId')


class AWSAccountSharingOption_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('provider', 'account')
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')
    account = sgqlc.types.Field(sgqlc.types.non_null('AWSAccount_v1'), graphql_name='account')


class AWSAccount_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'console_url', 'uid', 'resources_default_region', 'supported_deployment_regions', 'provider_version', 'terraform_username', 'account_owners', 'automation_token', 'garbage_collection', 'enable_deletion', 'deletion_approvals', 'disable', 'delete_keys', 'reset_passwords', 'premium_support', 'partition', 'sharing', 'ecrs', 'policies')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    console_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='consoleUrl')
    uid = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='uid')
    resources_default_region = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='resourcesDefaultRegion')
    supported_deployment_regions = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='supportedDeploymentRegions')
    provider_version = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='providerVersion')
    terraform_username = sgqlc.types.Field(String, graphql_name='terraformUsername')
    account_owners = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('Owner_v1')), graphql_name='accountOwners')
    automation_token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='automationToken')
    garbage_collection = sgqlc.types.Field(Boolean, graphql_name='garbageCollection')
    enable_deletion = sgqlc.types.Field(Boolean, graphql_name='enableDeletion')
    deletion_approvals = sgqlc.types.Field(sgqlc.types.list_of(AWSAccountDeletionApproval_v1), graphql_name='deletionApprovals')
    disable = sgqlc.types.Field('DisableClusterAutomations_v1', graphql_name='disable')
    delete_keys = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='deleteKeys')
    reset_passwords = sgqlc.types.Field(sgqlc.types.list_of(AWSAccountResetPassword_v1), graphql_name='resetPasswords')
    premium_support = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='premiumSupport')
    partition = sgqlc.types.Field(String, graphql_name='partition')
    sharing = sgqlc.types.Field(sgqlc.types.list_of(AWSAccountSharingOption_v1), graphql_name='sharing')
    ecrs = sgqlc.types.Field(sgqlc.types.list_of('AWSECR_v1'), graphql_name='ecrs')
    policies = sgqlc.types.Field(sgqlc.types.list_of('AWSUserPolicy_v1'), graphql_name='policies')


class AWSECR_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'account', 'name', 'description', 'region')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    account = sgqlc.types.Field(sgqlc.types.non_null(AWSAccount_v1), graphql_name='account')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    region = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='region')


class AWSGroup_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'account', 'name', 'description', 'policies', 'roles')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    account = sgqlc.types.Field(sgqlc.types.non_null(AWSAccount_v1), graphql_name='account')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    policies = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='policies')
    roles = sgqlc.types.Field(sgqlc.types.list_of('Role_v1'), graphql_name='roles')


class AWSInfrastructureAccess_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('aws_group', 'access_level')
    aws_group = sgqlc.types.Field(sgqlc.types.non_null(AWSGroup_v1), graphql_name='awsGroup')
    access_level = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='accessLevel')


class AWSInfrastructureManagementAccount_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('account', 'access_level', 'default')
    account = sgqlc.types.Field(sgqlc.types.non_null(AWSAccount_v1), graphql_name='account')
    access_level = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='accessLevel')
    default = sgqlc.types.Field(Boolean, graphql_name='default')


class AWSS3EventNotification_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('event_type', 'destination', 'destination_type', 'filter_prefix', 'filter_suffix')
    event_type = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='event_type')
    destination = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='destination')
    destination_type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='destination_type')
    filter_prefix = sgqlc.types.Field(String, graphql_name='filter_prefix')
    filter_suffix = sgqlc.types.Field(String, graphql_name='filter_suffix')


class AWSSubnet_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('id',)
    id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='id')


class AWSUserPolicy_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'account', 'name', 'description', 'mandatory', 'policy')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    account = sgqlc.types.Field(sgqlc.types.non_null(AWSAccount_v1), graphql_name='account')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    mandatory = sgqlc.types.Field(Boolean, graphql_name='mandatory')
    policy = sgqlc.types.Field(sgqlc.types.non_null(JSON), graphql_name='policy')


class AWSVPC_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'account', 'name', 'description', 'vpc_id', 'cidr_block', 'region', 'subnets')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    account = sgqlc.types.Field(sgqlc.types.non_null(AWSAccount_v1), graphql_name='account')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    vpc_id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='vpc_id')
    cidr_block = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='cidr_block')
    region = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='region')
    subnets = sgqlc.types.Field(sgqlc.types.list_of(AWSSubnet_v1), graphql_name='subnets')


class Access_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('namespace', 'role', 'cluster', 'group', 'cluster_role')
    namespace = sgqlc.types.Field('Namespace_v1', graphql_name='namespace')
    role = sgqlc.types.Field(String, graphql_name='role')
    cluster = sgqlc.types.Field('Cluster_v1', graphql_name='cluster')
    group = sgqlc.types.Field(String, graphql_name='group')
    cluster_role = sgqlc.types.Field(String, graphql_name='clusterRole')


class AppCodeComponents_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'resource', 'url', 'gitlab_repo_owners', 'gitlab_housekeeping', 'jira')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    resource = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='resource')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    gitlab_repo_owners = sgqlc.types.Field('CodeComponentGitlabOwners_v1', graphql_name='gitlabRepoOwners')
    gitlab_housekeeping = sgqlc.types.Field('CodeComponentGitlabHousekeeping_v1', graphql_name='gitlabHousekeeping')
    jira = sgqlc.types.Field('JiraServer_v1', graphql_name='jira')


class AppEndPointMonitoring_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('provider',)
    provider = sgqlc.types.Field('EndpointMonitoringProvider_v1', graphql_name='provider')


class AppEndPoints_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'description', 'url', 'monitoring')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    monitoring = sgqlc.types.Field(sgqlc.types.list_of(AppEndPointMonitoring_v1), graphql_name='monitoring')


class AppEscalationPolicyChannels_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('slack_user_group', 'email', 'pagerduty', 'jira_board', 'next_escalation_policy')
    slack_user_group = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('PermissionSlackUsergroup_v1')), graphql_name='slackUserGroup')
    email = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='email')
    pagerduty = sgqlc.types.Field('PagerDutyTarget_v1', graphql_name='pagerduty')
    jira_board = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('JiraBoard_v1')), graphql_name='jiraBoard')
    next_escalation_policy = sgqlc.types.Field('AppEscalationPolicy_v1', graphql_name='nextEscalationPolicy')


class AppEscalationPolicy_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('path', 'name', 'labels', 'description', 'channels')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    channels = sgqlc.types.Field(sgqlc.types.non_null(AppEscalationPolicyChannels_v1), graphql_name='channels')


class AppGcrReposItems_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'description', 'public', 'mirror')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    public = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='public')
    mirror = sgqlc.types.Field('ContainerImageMirror_v1', graphql_name='mirror')


class AppGcrRepos_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('project', 'items')
    project = sgqlc.types.Field(sgqlc.types.non_null('GcpProject_v1'), graphql_name='project')
    items = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(AppGcrReposItems_v1)), graphql_name='items')


class AppInterfaceDependencyMapping_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('type', 'services')
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')
    services = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('Dependency_v1')), graphql_name='services')


class AppInterfaceEmailAudience_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('aliases', 'services', 'clusters', 'namespaces', 'aws_accounts', 'roles', 'users')
    aliases = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='aliases')
    services = sgqlc.types.Field(sgqlc.types.list_of('App_v1'), graphql_name='services')
    clusters = sgqlc.types.Field(sgqlc.types.list_of('Cluster_v1'), graphql_name='clusters')
    namespaces = sgqlc.types.Field(sgqlc.types.list_of('Namespace_v1'), graphql_name='namespaces')
    aws_accounts = sgqlc.types.Field(sgqlc.types.list_of(AWSAccount_v1), graphql_name='aws_accounts')
    roles = sgqlc.types.Field(sgqlc.types.list_of('Role_v1'), graphql_name='roles')
    users = sgqlc.types.Field(sgqlc.types.list_of('User_v1'), graphql_name='users')


class AppInterfaceEmail_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'subject', 'to', 'body')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    subject = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='subject')
    to = sgqlc.types.Field(sgqlc.types.non_null(AppInterfaceEmailAudience_v1), graphql_name='to')
    body = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='body')


class AppInterfaceSettings_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'vault', 'kube_binary', 'pull_request_gateway', 'merge_request_gateway', 'saas_deploy_job_template', 'hash_length', 'smtp', 'github_repo_invites', 'dependencies', 'credentials', 'sql_query', 'push_gateway_cluster', 'alerting_services', 'endpoint_monitoring_blackbox_exporter_modules', 'ldap')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    vault = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='vault')
    kube_binary = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='kubeBinary')
    pull_request_gateway = sgqlc.types.Field(String, graphql_name='pullRequestGateway')
    merge_request_gateway = sgqlc.types.Field(String, graphql_name='mergeRequestGateway')
    saas_deploy_job_template = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='saasDeployJobTemplate')
    hash_length = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='hashLength')
    smtp = sgqlc.types.Field('SmtpSettings_v1', graphql_name='smtp')
    github_repo_invites = sgqlc.types.Field('GithubRepoInvites_v1', graphql_name='githubRepoInvites')
    dependencies = sgqlc.types.Field(sgqlc.types.list_of(AppInterfaceDependencyMapping_v1), graphql_name='dependencies')
    credentials = sgqlc.types.Field(sgqlc.types.list_of('CredentialsRequestMap_v1'), graphql_name='credentials')
    sql_query = sgqlc.types.Field('SqlQuerySettings_v1', graphql_name='sqlQuery')
    push_gateway_cluster = sgqlc.types.Field('Cluster_v1', graphql_name='pushGatewayCluster')
    alerting_services = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='alertingServices')
    endpoint_monitoring_blackbox_exporter_modules = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='endpointMonitoringBlackboxExporterModules')
    ldap = sgqlc.types.Field('LdapSettings_v1', graphql_name='ldap')


class AppInterfaceSlackNotificationAudience_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('users',)
    users = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='users')


class AppInterfaceSlackNotification_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'subject', 'channel', 'to', 'body')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    subject = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='subject')
    channel = sgqlc.types.Field(String, graphql_name='channel')
    to = sgqlc.types.Field(sgqlc.types.non_null(AppInterfaceSlackNotificationAudience_v1), graphql_name='to')
    body = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='body')


class AppInterfaceSqlQuery_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'namespace', 'identifier', 'requestor', 'overrides', 'output', 'schedule', 'query', 'queries')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    namespace = sgqlc.types.Field(sgqlc.types.non_null('Namespace_v1'), graphql_name='namespace')
    identifier = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='identifier')
    requestor = sgqlc.types.Field('User_v1', graphql_name='requestor')
    overrides = sgqlc.types.Field('SqlEmailOverrides_v1', graphql_name='overrides')
    output = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='output')
    schedule = sgqlc.types.Field(String, graphql_name='schedule')
    query = sgqlc.types.Field(String, graphql_name='query')
    queries = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='queries')


class AppQuayReposItems_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'description', 'public', 'mirror')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    public = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='public')
    mirror = sgqlc.types.Field('ContainerImageMirror_v1', graphql_name='mirror')


class AppQuayReposNotificationVerificationMethod_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('jira_board',)
    jira_board = sgqlc.types.Field('JiraBoard_v1', graphql_name='jiraBoard')


class AppQuayReposNotifications_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('event', 'severity', 'method', 'escalation_policy', 'verification_method')
    event = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='event')
    severity = sgqlc.types.Field(String, graphql_name='severity')
    method = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='method')
    escalation_policy = sgqlc.types.Field(sgqlc.types.non_null(AppEscalationPolicy_v1), graphql_name='escalationPolicy')
    verification_method = sgqlc.types.Field(AppQuayReposNotificationVerificationMethod_v1, graphql_name='verificationMethod')


class AppQuayReposTeams_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('permissions', 'role')
    permissions = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('PermissionQuayOrgTeam_v1')), graphql_name='permissions')
    role = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='role')


class AppQuayRepos_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('org', 'teams', 'notifications', 'items')
    org = sgqlc.types.Field(sgqlc.types.non_null('QuayOrg_v1'), graphql_name='org')
    teams = sgqlc.types.Field(sgqlc.types.list_of(AppQuayReposTeams_v1), graphql_name='teams')
    notifications = sgqlc.types.Field(sgqlc.types.list_of(AppQuayReposNotifications_v1), graphql_name='notifications')
    items = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(AppQuayReposItems_v1)), graphql_name='items')


class AppSentryProjects_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('team', 'projects')
    team = sgqlc.types.Field(sgqlc.types.non_null('SentryTeam_v1'), graphql_name='team')
    projects = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('SentryProjectItems_v1')), graphql_name='projects')


class App_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'onboarding_status', 'grafana_urls', 'sops_url', 'architecture_document', 'parent_app', 'service_docs', 'service_owners', 'service_notifications', 'dependencies', 'gcr_repos', 'quay_repos', 'escalation_policy', 'end_points', 'code_components', 'sentry_projects', 'status_page_components', 'namespaces', 'children_apps', 'jenkins_configs', 'saas_files_v2', 'sre_checkpoints')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    onboarding_status = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='onboardingStatus')
    grafana_urls = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('GrafanaDashboardUrls_v1')), graphql_name='grafanaUrls')
    sops_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='sopsUrl')
    architecture_document = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='architectureDocument')
    parent_app = sgqlc.types.Field('App_v1', graphql_name='parentApp')
    service_docs = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='serviceDocs')
    service_owners = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('Owner_v1')), graphql_name='serviceOwners')
    service_notifications = sgqlc.types.Field(sgqlc.types.list_of('Owner_v1'), graphql_name='serviceNotifications')
    dependencies = sgqlc.types.Field(sgqlc.types.list_of('Dependency_v1'), graphql_name='dependencies')
    gcr_repos = sgqlc.types.Field(sgqlc.types.list_of(AppGcrRepos_v1), graphql_name='gcrRepos')
    quay_repos = sgqlc.types.Field(sgqlc.types.list_of(AppQuayRepos_v1), graphql_name='quayRepos')
    escalation_policy = sgqlc.types.Field(sgqlc.types.non_null(AppEscalationPolicy_v1), graphql_name='escalationPolicy')
    end_points = sgqlc.types.Field(sgqlc.types.list_of(AppEndPoints_v1), graphql_name='endPoints')
    code_components = sgqlc.types.Field(sgqlc.types.list_of(AppCodeComponents_v1), graphql_name='codeComponents')
    sentry_projects = sgqlc.types.Field(sgqlc.types.list_of(AppSentryProjects_v1), graphql_name='sentryProjects')
    status_page_components = sgqlc.types.Field(sgqlc.types.list_of('StatusPageComponent_v1'), graphql_name='statusPageComponents')
    namespaces = sgqlc.types.Field(sgqlc.types.list_of('Namespace_v1'), graphql_name='namespaces')
    children_apps = sgqlc.types.Field(sgqlc.types.list_of('App_v1'), graphql_name='childrenApps')
    jenkins_configs = sgqlc.types.Field(sgqlc.types.list_of('JenkinsConfig_v1'), graphql_name='jenkinsConfigs')
    saas_files_v2 = sgqlc.types.Field(sgqlc.types.list_of('SaasFile_v2'), graphql_name='saasFilesV2')
    sre_checkpoints = sgqlc.types.Field(sgqlc.types.list_of('SRECheckpoint_v1'), graphql_name='sreCheckpoints')


class AssumeRole_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('aws', 'service')
    aws = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='AWS')
    service = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='Service')


class Bot_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'org_username', 'github_username', 'gitlab_username', 'openshift_serviceaccount', 'quay_username', 'owner', 'roles')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    org_username = sgqlc.types.Field(String, graphql_name='org_username')
    github_username = sgqlc.types.Field(String, graphql_name='github_username')
    gitlab_username = sgqlc.types.Field(String, graphql_name='gitlab_username')
    openshift_serviceaccount = sgqlc.types.Field(String, graphql_name='openshift_serviceaccount')
    quay_username = sgqlc.types.Field(String, graphql_name='quay_username')
    owner = sgqlc.types.Field('User_v1', graphql_name='owner')
    roles = sgqlc.types.Field(sgqlc.types.list_of('Role_v1'), graphql_name='roles')


class CloudinitConfig_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('filename', 'content_type', 'content')
    filename = sgqlc.types.Field(String, graphql_name='filename')
    content_type = sgqlc.types.Field(String, graphql_name='content_type')
    content = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='content')


class ClusterAdditionalRouter_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('private', 'route_selectors')
    private = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='private')
    route_selectors = sgqlc.types.Field(JSON, graphql_name='route_selectors')


class ClusterAddonParameters_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('id', 'value')
    id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='id')
    value = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='value')


class ClusterAddon_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'parameters')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    parameters = sgqlc.types.Field(sgqlc.types.list_of(ClusterAddonParameters_v1), graphql_name='parameters')


class ClusterAuth_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('service',)
    service = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='service')


class ClusterExternalConfiguration_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('labels',)
    labels = sgqlc.types.Field(sgqlc.types.non_null(JSON), graphql_name='labels')


class ClusterJumpHost_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('hostname', 'known_hosts', 'user', 'port', 'identity')
    hostname = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='hostname')
    known_hosts = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='knownHosts')
    user = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='user')
    port = sgqlc.types.Field(Int, graphql_name='port')
    identity = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='identity')


class ClusterMachinePool_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('id', 'instance_type', 'replicas', 'labels', 'taints')
    id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='id')
    instance_type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='instance_type')
    replicas = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='replicas')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    taints = sgqlc.types.Field(sgqlc.types.list_of('Taint_v1'), graphql_name='taints')


class ClusterNetwork_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('type', 'vpc', 'service', 'pod')
    type = sgqlc.types.Field(String, graphql_name='type')
    vpc = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='vpc')
    service = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='service')
    pod = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='pod')


class ClusterPeeringConnection_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('provider', 'name', 'description', 'manage_routes', 'delete')
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    manage_routes = sgqlc.types.Field(Boolean, graphql_name='manageRoutes')
    delete = sgqlc.types.Field(Boolean, graphql_name='delete')


class ClusterPeering_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('connections',)
    connections = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(ClusterPeeringConnection_v1)), graphql_name='connections')


class ClusterPrometheus_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('url', 'auth')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    auth = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='auth')


class ClusterSpecAutoScale_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('min_replicas', 'max_replicas')
    min_replicas = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='min_replicas')
    max_replicas = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='max_replicas')


class ClusterSpec_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('id', 'external_id', 'provider', 'region', 'channel', 'version', 'initial_version', 'multi_az', 'nodes', 'instance_type', 'storage', 'load_balancers', 'private', 'provision_shard_id', 'autoscale', 'disable_user_workload_monitoring')
    id = sgqlc.types.Field(String, graphql_name='id')
    external_id = sgqlc.types.Field(String, graphql_name='external_id')
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')
    region = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='region')
    channel = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='channel')
    version = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='version')
    initial_version = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='initial_version')
    multi_az = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='multi_az')
    nodes = sgqlc.types.Field(Int, graphql_name='nodes')
    instance_type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='instance_type')
    storage = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='storage')
    load_balancers = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='load_balancers')
    private = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='private')
    provision_shard_id = sgqlc.types.Field(String, graphql_name='provision_shard_id')
    autoscale = sgqlc.types.Field(ClusterSpecAutoScale_v1, graphql_name='autoscale')
    disable_user_workload_monitoring = sgqlc.types.Field(Boolean, graphql_name='disable_user_workload_monitoring')


class ClusterUpgradePolicyConditions_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('soak_days', 'mutexes')
    soak_days = sgqlc.types.Field(Int, graphql_name='soakDays')
    mutexes = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='mutexes')


class ClusterUpgradePolicy_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schedule_type', 'schedule', 'workloads', 'conditions')
    schedule_type = sgqlc.types.Field(String, graphql_name='schedule_type')
    schedule = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schedule')
    workloads = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='workloads')
    conditions = sgqlc.types.Field(sgqlc.types.non_null(ClusterUpgradePolicyConditions_v1), graphql_name='conditions')


class Cluster_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'auth', 'observability_namespace', 'grafana_url', 'console_url', 'kibana_url', 'prometheus_url', 'alertmanager_url', 'server_url', 'elb_fqdn', 'managed_groups', 'managed_cluster_roles', 'ocm', 'spec', 'external_configuration', 'upgrade_policy', 'additional_routers', 'network', 'machine_pools', 'peering', 'addons', 'insecure_skip_tlsverify', 'jump_host', 'automation_token', 'cluster_admin_automation_token', 'internal', 'disable', 'aws_infrastructure_access', 'aws_infrastructure_management_accounts', 'prometheus', 'namespaces')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    auth = sgqlc.types.Field(ClusterAuth_v1, graphql_name='auth')
    observability_namespace = sgqlc.types.Field('Namespace_v1', graphql_name='observabilityNamespace')
    grafana_url = sgqlc.types.Field(String, graphql_name='grafanaUrl')
    console_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='consoleUrl')
    kibana_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='kibanaUrl')
    prometheus_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='prometheusUrl')
    alertmanager_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='alertmanagerUrl')
    server_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='serverUrl')
    elb_fqdn = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='elbFQDN')
    managed_groups = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='managedGroups')
    managed_cluster_roles = sgqlc.types.Field(Boolean, graphql_name='managedClusterRoles')
    ocm = sgqlc.types.Field('OpenShiftClusterManager_v1', graphql_name='ocm')
    spec = sgqlc.types.Field(ClusterSpec_v1, graphql_name='spec')
    external_configuration = sgqlc.types.Field(ClusterExternalConfiguration_v1, graphql_name='externalConfiguration')
    upgrade_policy = sgqlc.types.Field(ClusterUpgradePolicy_v1, graphql_name='upgradePolicy')
    additional_routers = sgqlc.types.Field(sgqlc.types.list_of(ClusterAdditionalRouter_v1), graphql_name='additionalRouters')
    network = sgqlc.types.Field(ClusterNetwork_v1, graphql_name='network')
    machine_pools = sgqlc.types.Field(sgqlc.types.list_of(ClusterMachinePool_v1), graphql_name='machinePools')
    peering = sgqlc.types.Field(ClusterPeering_v1, graphql_name='peering')
    addons = sgqlc.types.Field(sgqlc.types.list_of(ClusterAddon_v1), graphql_name='addons')
    insecure_skip_tlsverify = sgqlc.types.Field(Boolean, graphql_name='insecureSkipTLSVerify')
    jump_host = sgqlc.types.Field(ClusterJumpHost_v1, graphql_name='jumpHost')
    automation_token = sgqlc.types.Field('VaultSecret_v1', graphql_name='automationToken')
    cluster_admin_automation_token = sgqlc.types.Field('VaultSecret_v1', graphql_name='clusterAdminAutomationToken')
    internal = sgqlc.types.Field(Boolean, graphql_name='internal')
    disable = sgqlc.types.Field('DisableClusterAutomations_v1', graphql_name='disable')
    aws_infrastructure_access = sgqlc.types.Field(sgqlc.types.list_of(AWSInfrastructureAccess_v1), graphql_name='awsInfrastructureAccess')
    aws_infrastructure_management_accounts = sgqlc.types.Field(sgqlc.types.list_of(AWSInfrastructureManagementAccount_v1), graphql_name='awsInfrastructureManagementAccounts')
    prometheus = sgqlc.types.Field(ClusterPrometheus_v1, graphql_name='prometheus')
    namespaces = sgqlc.types.Field(sgqlc.types.list_of('Namespace_v1'), graphql_name='namespaces')


class CodeComponentGitlabHousekeeping_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('enabled', 'rebase', 'days_interval', 'limit', 'enable_closing', 'pipeline_timeout')
    enabled = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='enabled')
    rebase = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='rebase')
    days_interval = sgqlc.types.Field(Int, graphql_name='days_interval')
    limit = sgqlc.types.Field(Int, graphql_name='limit')
    enable_closing = sgqlc.types.Field(Boolean, graphql_name='enable_closing')
    pipeline_timeout = sgqlc.types.Field(Int, graphql_name='pipeline_timeout')


class CodeComponentGitlabOwners_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('enabled',)
    enabled = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='enabled')


class ContainerImageMirror_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('url', 'pull_credentials', 'tags', 'tags_exclude')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    pull_credentials = sgqlc.types.Field('VaultSecret_v1', graphql_name='pullCredentials')
    tags = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='tags')
    tags_exclude = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='tagsExclude')


class CredentialsRequestMap_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'secret')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    secret = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='secret')


class CredentialsRequest_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'user', 'credentials')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    user = sgqlc.types.Field(sgqlc.types.non_null('User_v1'), graphql_name='user')
    credentials = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='credentials')


class Dependency_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'statefulness', 'ops_model', 'status_page', 'sla', 'dependency_failure_impact')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    statefulness = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='statefulness')
    ops_model = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='opsModel')
    status_page = sgqlc.types.Field(String, graphql_name='statusPage')
    sla = sgqlc.types.Field(sgqlc.types.non_null(Float), graphql_name='SLA')
    dependency_failure_impact = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='dependencyFailureImpact')


class DeployResources_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('requests', 'limits')
    requests = sgqlc.types.Field(sgqlc.types.non_null('ResourceRequirements_v1'), graphql_name='requests')
    limits = sgqlc.types.Field(sgqlc.types.non_null('ResourceRequirements_v1'), graphql_name='limits')


class DisableClusterAutomations_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('integrations', 'e2e_tests')
    integrations = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='integrations')
    e2e_tests = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='e2eTests')


class DnsNamespaceZone_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('namespace', 'name')
    namespace = sgqlc.types.Field(sgqlc.types.non_null('Namespace_v1'), graphql_name='namespace')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')


class DnsRecordAlias_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'zone_id', 'evaluate_target_health')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    zone_id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='zone_id')
    evaluate_target_health = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='evaluate_target_health')


class DnsRecordHealthcheck_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('fqdn', 'port', 'type', 'resource_path', 'failure_threshold', 'request_interval', 'search_string')
    fqdn = sgqlc.types.Field(String, graphql_name='fqdn')
    port = sgqlc.types.Field(Int, graphql_name='port')
    type = sgqlc.types.Field(String, graphql_name='type')
    resource_path = sgqlc.types.Field(String, graphql_name='resource_path')
    failure_threshold = sgqlc.types.Field(Int, graphql_name='failure_threshold')
    request_interval = sgqlc.types.Field(Int, graphql_name='request_interval')
    search_string = sgqlc.types.Field(String, graphql_name='search_string')


class DnsRecordWeightedRoutingPolicy_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('weight',)
    weight = sgqlc.types.Field(Int, graphql_name='weight')


class DnsRecord_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'type', 'ttl', 'alias', 'weighted_routing_policy', 'set_identifier', 'records', '_healthcheck', '_target_cluster', '_target_namespace_zone')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')
    ttl = sgqlc.types.Field(Int, graphql_name='ttl')
    alias = sgqlc.types.Field(DnsRecordAlias_v1, graphql_name='alias')
    weighted_routing_policy = sgqlc.types.Field(DnsRecordWeightedRoutingPolicy_v1, graphql_name='weighted_routing_policy')
    set_identifier = sgqlc.types.Field(String, graphql_name='set_identifier')
    records = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='records')
    _healthcheck = sgqlc.types.Field(DnsRecordHealthcheck_v1, graphql_name='_healthcheck')
    _target_cluster = sgqlc.types.Field(Cluster_v1, graphql_name='_target_cluster')
    _target_namespace_zone = sgqlc.types.Field(DnsNamespaceZone_v1, graphql_name='_target_namespace_zone')


class DnsZone_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'labels', 'name', 'description', 'provider', 'account', 'vpc', 'origin', 'unmanaged_record_names', 'records')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')
    account = sgqlc.types.Field(sgqlc.types.non_null(AWSAccount_v1), graphql_name='account')
    vpc = sgqlc.types.Field(AWSVPC_v1, graphql_name='vpc')
    origin = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='origin')
    unmanaged_record_names = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='unmanaged_record_names')
    records = sgqlc.types.Field(sgqlc.types.list_of(DnsRecord_v1), graphql_name='records')


class Document_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'app', 'name', 'content_path')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    app = sgqlc.types.Field(sgqlc.types.non_null(App_v1), graphql_name='app')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    content_path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='content_path')


class DynTrafficDirectorRecord_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('hostname', 'cluster', 'weight')
    hostname = sgqlc.types.Field(String, graphql_name='hostname')
    cluster = sgqlc.types.Field(Cluster_v1, graphql_name='cluster')
    weight = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='weight')


class DynTrafficDirector_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'ttl', 'records')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    ttl = sgqlc.types.Field(Int, graphql_name='ttl')
    records = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(DynTrafficDirectorRecord_v1)), graphql_name='records')


class DynamoDBTableSpecs_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('defaults', 'tables')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    tables = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('KeyValue_v1')), graphql_name='tables')


class EndpointMonitoringProviderBlackboxExporterSettings_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('module', 'namespace', 'exporter_url')
    module = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='module')
    namespace = sgqlc.types.Field(sgqlc.types.non_null('Namespace_v1'), graphql_name='namespace')
    exporter_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='exporterUrl')


class EndpointMonitoringProviderSignalFxSettings_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('namespace', 'exporter_url', 'target_filter_label')
    namespace = sgqlc.types.Field(sgqlc.types.non_null('Namespace_v1'), graphql_name='namespace')
    exporter_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='exporterUrl')
    target_filter_label = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='targetFilterLabel')


class EndpointMonitoringProvider_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'provider', 'metric_labels', 'timeout', 'check_interval')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')
    metric_labels = sgqlc.types.Field(JSON, graphql_name='metricLabels')
    timeout = sgqlc.types.Field(String, graphql_name='timeout')
    check_interval = sgqlc.types.Field(String, graphql_name='checkInterval')


class Environment_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'product', 'parameters', 'secret_parameters', 'depends_on', 'namespaces')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    product = sgqlc.types.Field(sgqlc.types.non_null('Product_v1'), graphql_name='product')
    parameters = sgqlc.types.Field(JSON, graphql_name='parameters')
    secret_parameters = sgqlc.types.Field(sgqlc.types.list_of('SaasSecretParameters_v1'), graphql_name='secretParameters')
    depends_on = sgqlc.types.Field('Environment_v1', graphql_name='dependsOn')
    namespaces = sgqlc.types.Field(sgqlc.types.list_of('Namespace_v1'), graphql_name='namespaces')


class ExternalUser_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'github_username', 'sponsors')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    github_username = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='github_username')
    sponsors = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('User_v1')), graphql_name='sponsors')


class GabiInstance_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'signoff_managers', 'users', 'instances', 'expiration_date')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    signoff_managers = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('User_v1')), graphql_name='signoffManagers')
    users = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('User_v1')), graphql_name='users')
    instances = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('GabiNamespace_v1')), graphql_name='instances')
    expiration_date = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='expirationDate')


class GabiNamespace_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('account', 'identifier', 'namespace')
    account = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='account')
    identifier = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='identifier')
    namespace = sgqlc.types.Field(sgqlc.types.non_null('Namespace_v1'), graphql_name='namespace')


class GcpProject_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'managed_teams', 'automation_token', 'push_credentials')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    managed_teams = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='managedTeams')
    automation_token = sgqlc.types.Field('VaultSecret_v1', graphql_name='automationToken')
    push_credentials = sgqlc.types.Field('VaultSecret_v1', graphql_name='pushCredentials')


class GithubOrg_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'url', 'two_factor_authentication', 'default', 'token', 'managed_teams')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    two_factor_authentication = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='two_factor_authentication')
    default = sgqlc.types.Field(Boolean, graphql_name='default')
    token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='token')
    managed_teams = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='managedTeams')


class GithubRepoInvites_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('credentials',)
    credentials = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='credentials')


class GitlabInstance_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'backup_orgs', 'managed_groups', 'project_requests', 'url', 'token', 'ssl_verify')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    backup_orgs = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='backupOrgs')
    managed_groups = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='managedGroups')
    project_requests = sgqlc.types.Field(sgqlc.types.list_of('GitlabProjects_v1'), graphql_name='projectRequests')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='token')
    ssl_verify = sgqlc.types.Field(Boolean, graphql_name='sslVerify')


class GitlabProjects_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('group', 'projects')
    group = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='group')
    projects = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='projects')


class GrafanaDashboardUrls_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('title', 'url')
    title = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='title')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')


class IntegrationPrCheck_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('cmd', 'state', 'sqs', 'disabled', 'always_run', 'no_validate_schemas', 'run_for_valid_saas_file_changes')
    cmd = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='cmd')
    state = sgqlc.types.Field(Boolean, graphql_name='state')
    sqs = sgqlc.types.Field(Boolean, graphql_name='sqs')
    disabled = sgqlc.types.Field(Boolean, graphql_name='disabled')
    always_run = sgqlc.types.Field(Boolean, graphql_name='always_run')
    no_validate_schemas = sgqlc.types.Field(Boolean, graphql_name='no_validate_schemas')
    run_for_valid_saas_file_changes = sgqlc.types.Field(Boolean, graphql_name='run_for_valid_saas_file_changes')


class Integration_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'upstream', 'schemas', 'pr_check')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    upstream = sgqlc.types.Field(String, graphql_name='upstream')
    schemas = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='schemas')
    pr_check = sgqlc.types.Field(IntegrationPrCheck_v1, graphql_name='pr_check')


class JenkinsConfig_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'app', 'instance', 'type', 'config', 'config_path')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    app = sgqlc.types.Field(sgqlc.types.non_null(App_v1), graphql_name='app')
    instance = sgqlc.types.Field(sgqlc.types.non_null('JenkinsInstance_v1'), graphql_name='instance')
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')
    config = sgqlc.types.Field(JSON, graphql_name='config')
    config_path = sgqlc.types.Field(String, graphql_name='config_path')


class JenkinsInstanceBuildsCleanupRules_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'keep_hours')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    keep_hours = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='keep_hours')


class JenkinsInstance_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'server_url', 'token', 'previous_urls', 'plugins', 'delete_method', 'managed_projects', 'builds_cleanup_rules')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    server_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='serverUrl')
    token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='token')
    previous_urls = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='previousUrls')
    plugins = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='plugins')
    delete_method = sgqlc.types.Field(String, graphql_name='deleteMethod')
    managed_projects = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='managedProjects')
    builds_cleanup_rules = sgqlc.types.Field(sgqlc.types.list_of(JenkinsInstanceBuildsCleanupRules_v1), graphql_name='buildsCleanupRules')


class JiraBoard_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'server', 'severity_priority_mappings', 'slack')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    server = sgqlc.types.Field(sgqlc.types.non_null('JiraServer_v1'), graphql_name='server')
    severity_priority_mappings = sgqlc.types.Field(sgqlc.types.non_null('JiraSeverityPriorityMappings_v1'), graphql_name='severityPriorityMappings')
    slack = sgqlc.types.Field('SlackOutput_v1', graphql_name='slack')


class JiraServer_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'server_url', 'token')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    server_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='serverUrl')
    token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='token')


class JiraSeverityPriorityMappings_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'mappings')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    mappings = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('SeverityPriorityMapping_v1')), graphql_name='mappings')


class KafkaClusterSpec_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('provider', 'region', 'multi_az')
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')
    region = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='region')
    multi_az = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='multi_az')


class KafkaCluster_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'ocm', 'spec', 'namespaces')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    ocm = sgqlc.types.Field('OpenShiftClusterManager_v1', graphql_name='ocm')
    spec = sgqlc.types.Field(KafkaClusterSpec_v1, graphql_name='spec')
    namespaces = sgqlc.types.Field(sgqlc.types.list_of('Namespace_v1'), graphql_name='namespaces')


class KeyValue_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('key', 'value')
    key = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='key')
    value = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='value')


class LdapSettings_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('server_url', 'base_dn')
    server_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='serverUrl')
    base_dn = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='baseDn')


class LimitRangeItem_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('default', 'default_request', 'max', 'max_limit_request_ratio', 'min', 'type')
    default = sgqlc.types.Field('ResourceValues_v1', graphql_name='default')
    default_request = sgqlc.types.Field('ResourceValues_v1', graphql_name='defaultRequest')
    max = sgqlc.types.Field('ResourceValues_v1', graphql_name='max')
    max_limit_request_ratio = sgqlc.types.Field('ResourceValues_v1', graphql_name='maxLimitRequestRatio')
    min = sgqlc.types.Field('ResourceValues_v1', graphql_name='min')
    type = sgqlc.types.Field(String, graphql_name='type')


class LimitRange_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'labels', 'name', 'description', 'limits')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    limits = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(LimitRangeItem_v1)), graphql_name='limits')


class ManualStatusProviderConfig_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('component_status', 'from_', 'until')
    component_status = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='componentStatus')
    from_ = sgqlc.types.Field(String, graphql_name='from')
    until = sgqlc.types.Field(String, graphql_name='until')


class NamespaceManagedResourceNames_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('resource', 'resource_names')
    resource = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='resource')
    resource_names = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='resourceNames')


class NamespaceManagedResourceTypeOverrides_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('resource', 'override')
    resource = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='resource')
    override = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='override')


class NamespaceOpenshiftResource_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('provider',)
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')


class NamespaceTerraformResourceALBAction_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('target', 'weight')
    target = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='target')
    weight = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='weight')


class NamespaceTerraformResourceALBConditon_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('path', 'methods')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    methods = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='methods')


class NamespaceTerraformResourceALBRules_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('condition', 'action')
    condition = sgqlc.types.Field(sgqlc.types.non_null(NamespaceTerraformResourceALBConditon_v1), graphql_name='condition')
    action = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(NamespaceTerraformResourceALBAction_v1)), graphql_name='action')


class NamespaceTerraformResourceALBTargets_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'default', 'ips', 'openshift_service')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    default = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='default')
    ips = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='ips')
    openshift_service = sgqlc.types.Field(String, graphql_name='openshift_service')


class NamespaceTerraformResourceOutputFormat_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('provider',)
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')


class NamespaceTerraformResourceServiceAccountAWSInfrastructureAccess_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('cluster', 'access_level', 'assume_role')
    cluster = sgqlc.types.Field(Cluster_v1, graphql_name='cluster')
    access_level = sgqlc.types.Field(String, graphql_name='access_level')
    assume_role = sgqlc.types.Field(String, graphql_name='assume_role')


class NamespaceTerraformResource_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('provider', 'account', 'identifier', 'output_resource_name', 'output_format', 'annotations')
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')
    account = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='account')
    identifier = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='identifier')
    output_resource_name = sgqlc.types.Field(String, graphql_name='output_resource_name')
    output_format = sgqlc.types.Field(NamespaceTerraformResourceOutputFormat_v1, graphql_name='output_format')
    annotations = sgqlc.types.Field(JSON, graphql_name='annotations')


class Namespace_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'delete', 'description', 'grafana_url', 'cluster', 'app', 'environment', 'limit_ranges', 'quota', 'network_policies_allow', 'cluster_admin', 'managed_roles', 'managed_resource_types', 'managed_resource_type_overrides', 'managed_resource_names', 'shared_resources', 'openshift_resources', 'managed_terraform_resources', 'terraform_resources', 'openshift_service_account_tokens', 'kafka_cluster')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    delete = sgqlc.types.Field(Boolean, graphql_name='delete')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    grafana_url = sgqlc.types.Field(String, graphql_name='grafanaUrl')
    cluster = sgqlc.types.Field(sgqlc.types.non_null(Cluster_v1), graphql_name='cluster')
    app = sgqlc.types.Field(sgqlc.types.non_null(App_v1), graphql_name='app')
    environment = sgqlc.types.Field(sgqlc.types.non_null(Environment_v1), graphql_name='environment')
    limit_ranges = sgqlc.types.Field(LimitRange_v1, graphql_name='limitRanges')
    quota = sgqlc.types.Field('ResourceQuota_v1', graphql_name='quota')
    network_policies_allow = sgqlc.types.Field(sgqlc.types.list_of('Namespace_v1'), graphql_name='networkPoliciesAllow')
    cluster_admin = sgqlc.types.Field(Boolean, graphql_name='clusterAdmin')
    managed_roles = sgqlc.types.Field(Boolean, graphql_name='managedRoles')
    managed_resource_types = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='managedResourceTypes')
    managed_resource_type_overrides = sgqlc.types.Field(sgqlc.types.list_of(NamespaceManagedResourceTypeOverrides_v1), graphql_name='managedResourceTypeOverrides')
    managed_resource_names = sgqlc.types.Field(sgqlc.types.list_of(NamespaceManagedResourceNames_v1), graphql_name='managedResourceNames')
    shared_resources = sgqlc.types.Field(sgqlc.types.list_of('SharedResources_v1'), graphql_name='sharedResources')
    openshift_resources = sgqlc.types.Field(sgqlc.types.list_of(NamespaceOpenshiftResource_v1), graphql_name='openshiftResources')
    managed_terraform_resources = sgqlc.types.Field(Boolean, graphql_name='managedTerraformResources')
    terraform_resources = sgqlc.types.Field(sgqlc.types.list_of(NamespaceTerraformResource_v1), graphql_name='terraformResources')
    openshift_service_account_tokens = sgqlc.types.Field(sgqlc.types.list_of('ServiceAccountTokenSpec_v1'), graphql_name='openshiftServiceAccountTokens')
    kafka_cluster = sgqlc.types.Field(KafkaCluster_v1, graphql_name='kafkaCluster')


class OcpReleaseMirror_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('hive_cluster', 'ecr_resources_namespace', 'ocp_release_ecr_identifier', 'ocp_art_dev_ecr_identifier', 'quay_target_orgs', 'mirror_channels')
    hive_cluster = sgqlc.types.Field(sgqlc.types.non_null(Cluster_v1), graphql_name='hiveCluster')
    ecr_resources_namespace = sgqlc.types.Field(sgqlc.types.non_null(Namespace_v1), graphql_name='ecrResourcesNamespace')
    ocp_release_ecr_identifier = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='ocpReleaseEcrIdentifier')
    ocp_art_dev_ecr_identifier = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='ocpArtDevEcrIdentifier')
    quay_target_orgs = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('QuayOrg_v1')), graphql_name='quayTargetOrgs')
    mirror_channels = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='mirrorChannels')


class OidcPermission_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'labels', 'name', 'service', 'description')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    service = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='service')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')


class OpenShiftClusterManager_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'url', 'access_token_client_id', 'access_token_url', 'offline_token', 'blocked_versions', 'clusters')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    access_token_client_id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='accessTokenClientId')
    access_token_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='accessTokenUrl')
    offline_token = sgqlc.types.Field('VaultSecret_v1', graphql_name='offlineToken')
    blocked_versions = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='blockedVersions')
    clusters = sgqlc.types.Field(sgqlc.types.list_of(Cluster_v1), graphql_name='clusters')


class Owner_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'email')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    email = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='email')


class PagerDutyInstance_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'token')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='token')


class PagerDutyTarget_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'instance', 'schedule_id', 'escalation_policy_id')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    instance = sgqlc.types.Field(sgqlc.types.non_null(PagerDutyInstance_v1), graphql_name='instance')
    schedule_id = sgqlc.types.Field(String, graphql_name='scheduleID')
    escalation_policy_id = sgqlc.types.Field(String, graphql_name='escalationPolicyID')


class Permission_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'service')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    service = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='service')


class PipelinesProviderPipelineTemplates_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('openshift_saas_deploy',)
    openshift_saas_deploy = sgqlc.types.Field(sgqlc.types.non_null('PipelinesProviderTektonObjectTemplate_v1'), graphql_name='openshiftSaasDeploy')


class PipelinesProviderRetention_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('days', 'minimum')
    days = sgqlc.types.Field(Int, graphql_name='days')
    minimum = sgqlc.types.Field(Int, graphql_name='minimum')


class PipelinesProviderTektonObjectTemplate_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'type', 'path', 'variables')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    variables = sgqlc.types.Field(JSON, graphql_name='variables')


class PipelinesProviderTektonProviderDefaults_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'labels', 'description', 'retention', 'task_templates', 'pipeline_templates', 'deploy_resources')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    labels = sgqlc.types.Field(sgqlc.types.non_null(JSON), graphql_name='labels')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    retention = sgqlc.types.Field(sgqlc.types.non_null(PipelinesProviderRetention_v1), graphql_name='retention')
    task_templates = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(PipelinesProviderTektonObjectTemplate_v1)), graphql_name='taskTemplates')
    pipeline_templates = sgqlc.types.Field(sgqlc.types.non_null(PipelinesProviderPipelineTemplates_v1), graphql_name='pipelineTemplates')
    deploy_resources = sgqlc.types.Field(DeployResources_v1, graphql_name='deployResources')


class PipelinesProvider_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'provider')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')


class Product_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'product_owners', 'environments')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    product_owners = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(Owner_v1)), graphql_name='productOwners')
    environments = sgqlc.types.Field(sgqlc.types.list_of(Environment_v1), graphql_name='environments')


class PrometheusAlertMatcherExpression_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('alert', 'labels')
    alert = sgqlc.types.Field(String, graphql_name='alert')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')


class PrometheusAlertMatcher_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('match_expression', 'component_status')
    match_expression = sgqlc.types.Field(sgqlc.types.non_null(PrometheusAlertMatcherExpression_v1), graphql_name='matchExpression')
    component_status = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='componentStatus')


class PrometheusAlertsStatusProviderConfig_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('namespace', 'matchers')
    namespace = sgqlc.types.Field(sgqlc.types.list_of(Namespace_v1), graphql_name='namespace')
    matchers = sgqlc.types.Field(sgqlc.types.list_of(PrometheusAlertMatcher_v1), graphql_name='matchers')


class PromotionChannelData_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('type',)
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')


class PromotionData_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('channel', 'data')
    channel = sgqlc.types.Field(String, graphql_name='channel')
    data = sgqlc.types.Field(sgqlc.types.list_of(PromotionChannelData_v1), graphql_name='data')


class QuayInstance_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'url')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')


class QuayOrg_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'mirror', 'managed_repos', 'instance', 'server_url', 'managed_teams', 'automation_token', 'push_credentials')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    mirror = sgqlc.types.Field('QuayOrg_v1', graphql_name='mirror')
    managed_repos = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='managedRepos')
    instance = sgqlc.types.Field(sgqlc.types.non_null(QuayInstance_v1), graphql_name='instance')
    server_url = sgqlc.types.Field(String, graphql_name='serverUrl')
    managed_teams = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='managedTeams')
    automation_token = sgqlc.types.Field('VaultSecret_v1', graphql_name='automationToken')
    push_credentials = sgqlc.types.Field('VaultSecret_v1', graphql_name='pushCredentials')


class Query(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('app_interface_settings_v1', 'app_interface_emails_v1', 'app_interface_slack_notifications_v1', 'credentials_requests_v1', 'users_v1', 'external_users_v1', 'bots_v1', 'roles_v1', 'permissions_v1', 'awsgroups_v1', 'awsaccounts_v1', 'clusters_v1', 'kafka_clusters_v1', 'namespaces_v1', 'gcp_projects_v1', 'quay_orgs_v1', 'quay_instances_v1', 'jenkins_instances_v1', 'jenkins_configs_v1', 'jira_servers_v1', 'jira_boards_v1', 'sendgrid_accounts_v1', 'products_v1', 'environments_v1', 'apps_v1', 'escalation_policies_1', 'resources_v1', 'vault_audit_backends_v1', 'vault_auth_backends_v1', 'vault_secret_engines_v1', 'vault_roles_v1', 'vault_policies_v1', 'dependencies_v1', 'githuborg_v1', 'gitlabinstance_v1', 'integrations_v1', 'documents_v1', 'reports_v1', 'sre_checkpoints_v1', 'sentry_teams_v1', 'sentry_instances_v1', 'app_interface_sql_queries_v1', 'saas_files_v2', 'pipelines_providers_v1', 'unleash_instances_v1', 'gabi_instances_v1', 'template_tests_v1', 'dns_zone_v1', 'slack_workspaces_v1', 'ocp_release_mirror_v1', 'slo_document_v1', 'shared_resources_v1', 'pagerduty_instances_v1', 'ocm_instances_v1', 'dyn_traffic_directors_v1', 'status_page_v1', 'status_page_component_v1', 'endpoint_monitoring_provider_v1')
    app_interface_settings_v1 = sgqlc.types.Field(sgqlc.types.list_of(AppInterfaceSettings_v1), graphql_name='app_interface_settings_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    app_interface_emails_v1 = sgqlc.types.Field(sgqlc.types.list_of(AppInterfaceEmail_v1), graphql_name='app_interface_emails_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    app_interface_slack_notifications_v1 = sgqlc.types.Field(sgqlc.types.list_of(AppInterfaceSlackNotification_v1), graphql_name='app_interface_slack_notifications_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    credentials_requests_v1 = sgqlc.types.Field(sgqlc.types.list_of(CredentialsRequest_v1), graphql_name='credentials_requests_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    users_v1 = sgqlc.types.Field(sgqlc.types.list_of('User_v1'), graphql_name='users_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
        ('org_username', sgqlc.types.Arg(String, graphql_name='org_username', default=None)),
))
    )
    external_users_v1 = sgqlc.types.Field(sgqlc.types.list_of(ExternalUser_v1), graphql_name='external_users_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    bots_v1 = sgqlc.types.Field(sgqlc.types.list_of(Bot_v1), graphql_name='bots_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    roles_v1 = sgqlc.types.Field(sgqlc.types.list_of('Role_v1'), graphql_name='roles_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
        ('name', sgqlc.types.Arg(String, graphql_name='name', default=None)),
))
    )
    permissions_v1 = sgqlc.types.Field(sgqlc.types.list_of(Permission_v1), graphql_name='permissions_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    awsgroups_v1 = sgqlc.types.Field(sgqlc.types.list_of(AWSGroup_v1), graphql_name='awsgroups_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    awsaccounts_v1 = sgqlc.types.Field(sgqlc.types.list_of(AWSAccount_v1), graphql_name='awsaccounts_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
        ('name', sgqlc.types.Arg(String, graphql_name='name', default=None)),
        ('uid', sgqlc.types.Arg(String, graphql_name='uid', default=None)),
))
    )
    clusters_v1 = sgqlc.types.Field(sgqlc.types.list_of(Cluster_v1), graphql_name='clusters_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
        ('name', sgqlc.types.Arg(String, graphql_name='name', default=None)),
))
    )
    kafka_clusters_v1 = sgqlc.types.Field(sgqlc.types.list_of(KafkaCluster_v1), graphql_name='kafka_clusters_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    namespaces_v1 = sgqlc.types.Field(sgqlc.types.list_of(Namespace_v1), graphql_name='namespaces_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    gcp_projects_v1 = sgqlc.types.Field(sgqlc.types.list_of(GcpProject_v1), graphql_name='gcp_projects_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    quay_orgs_v1 = sgqlc.types.Field(sgqlc.types.list_of(QuayOrg_v1), graphql_name='quay_orgs_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    quay_instances_v1 = sgqlc.types.Field(sgqlc.types.list_of(QuayInstance_v1), graphql_name='quay_instances_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    jenkins_instances_v1 = sgqlc.types.Field(sgqlc.types.list_of(JenkinsInstance_v1), graphql_name='jenkins_instances_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    jenkins_configs_v1 = sgqlc.types.Field(sgqlc.types.list_of(JenkinsConfig_v1), graphql_name='jenkins_configs_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    jira_servers_v1 = sgqlc.types.Field(sgqlc.types.list_of(JiraServer_v1), graphql_name='jira_servers_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    jira_boards_v1 = sgqlc.types.Field(sgqlc.types.list_of(JiraBoard_v1), graphql_name='jira_boards_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
        ('name', sgqlc.types.Arg(String, graphql_name='name', default=None)),
))
    )
    sendgrid_accounts_v1 = sgqlc.types.Field(sgqlc.types.list_of('SendGridAccount_v1'), graphql_name='sendgrid_accounts_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    products_v1 = sgqlc.types.Field(sgqlc.types.list_of(Product_v1), graphql_name='products_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    environments_v1 = sgqlc.types.Field(sgqlc.types.list_of(Environment_v1), graphql_name='environments_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    apps_v1 = sgqlc.types.Field(sgqlc.types.list_of(App_v1), graphql_name='apps_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
        ('name', sgqlc.types.Arg(String, graphql_name='name', default=None)),
))
    )
    escalation_policies_1 = sgqlc.types.Field(sgqlc.types.list_of(AppEscalationPolicy_v1), graphql_name='escalation_policies_1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    resources_v1 = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('Resource_v1')), graphql_name='resources_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
        ('schema', sgqlc.types.Arg(String, graphql_name='schema', default=None)),
))
    )
    vault_audit_backends_v1 = sgqlc.types.Field(sgqlc.types.list_of('VaultAudit_v1'), graphql_name='vault_audit_backends_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    vault_auth_backends_v1 = sgqlc.types.Field(sgqlc.types.list_of('VaultAuth_v1'), graphql_name='vault_auth_backends_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    vault_secret_engines_v1 = sgqlc.types.Field(sgqlc.types.list_of('VaultSecretEngine_v1'), graphql_name='vault_secret_engines_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    vault_roles_v1 = sgqlc.types.Field(sgqlc.types.list_of('VaultRole_v1'), graphql_name='vault_roles_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    vault_policies_v1 = sgqlc.types.Field(sgqlc.types.list_of('VaultPolicy_v1'), graphql_name='vault_policies_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    dependencies_v1 = sgqlc.types.Field(sgqlc.types.list_of(Dependency_v1), graphql_name='dependencies_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    githuborg_v1 = sgqlc.types.Field(sgqlc.types.list_of(GithubOrg_v1), graphql_name='githuborg_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    gitlabinstance_v1 = sgqlc.types.Field(sgqlc.types.list_of(GitlabInstance_v1), graphql_name='gitlabinstance_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    integrations_v1 = sgqlc.types.Field(sgqlc.types.list_of(Integration_v1), graphql_name='integrations_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    documents_v1 = sgqlc.types.Field(sgqlc.types.list_of(Document_v1), graphql_name='documents_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    reports_v1 = sgqlc.types.Field(sgqlc.types.list_of('Report_v1'), graphql_name='reports_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    sre_checkpoints_v1 = sgqlc.types.Field(sgqlc.types.list_of('SRECheckpoint_v1'), graphql_name='sre_checkpoints_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    sentry_teams_v1 = sgqlc.types.Field(sgqlc.types.list_of('SentryTeam_v1'), graphql_name='sentry_teams_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    sentry_instances_v1 = sgqlc.types.Field(sgqlc.types.list_of('SentryInstance_v1'), graphql_name='sentry_instances_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    app_interface_sql_queries_v1 = sgqlc.types.Field(sgqlc.types.list_of(AppInterfaceSqlQuery_v1), graphql_name='app_interface_sql_queries_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    saas_files_v2 = sgqlc.types.Field(sgqlc.types.list_of('SaasFile_v2'), graphql_name='saas_files_v2', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
        ('name', sgqlc.types.Arg(String, graphql_name='name', default=None)),
))
    )
    pipelines_providers_v1 = sgqlc.types.Field(sgqlc.types.list_of(PipelinesProvider_v1), graphql_name='pipelines_providers_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    unleash_instances_v1 = sgqlc.types.Field(sgqlc.types.list_of('UnleashInstance_v1'), graphql_name='unleash_instances_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    gabi_instances_v1 = sgqlc.types.Field(sgqlc.types.list_of(GabiInstance_v1), graphql_name='gabi_instances_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    template_tests_v1 = sgqlc.types.Field(sgqlc.types.list_of('TemplateTest_v1'), graphql_name='template_tests_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    dns_zone_v1 = sgqlc.types.Field(sgqlc.types.list_of(DnsZone_v1), graphql_name='dns_zone_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    slack_workspaces_v1 = sgqlc.types.Field(sgqlc.types.list_of('SlackWorkspace_v1'), graphql_name='slack_workspaces_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    ocp_release_mirror_v1 = sgqlc.types.Field(sgqlc.types.list_of(OcpReleaseMirror_v1), graphql_name='ocp_release_mirror_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    slo_document_v1 = sgqlc.types.Field(sgqlc.types.list_of('SLODocument_v1'), graphql_name='slo_document_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    shared_resources_v1 = sgqlc.types.Field(sgqlc.types.list_of('SharedResources_v1'), graphql_name='shared_resources_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
        ('name', sgqlc.types.Arg(String, graphql_name='name', default=None)),
))
    )
    pagerduty_instances_v1 = sgqlc.types.Field(sgqlc.types.list_of(PagerDutyInstance_v1), graphql_name='pagerduty_instances_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    ocm_instances_v1 = sgqlc.types.Field(sgqlc.types.list_of(OpenShiftClusterManager_v1), graphql_name='ocm_instances_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    dyn_traffic_directors_v1 = sgqlc.types.Field(sgqlc.types.list_of(DynTrafficDirector_v1), graphql_name='dyn_traffic_directors_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    status_page_v1 = sgqlc.types.Field(sgqlc.types.list_of('StatusPage_v1'), graphql_name='status_page_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    status_page_component_v1 = sgqlc.types.Field(sgqlc.types.list_of('StatusPageComponent_v1'), graphql_name='status_page_component_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )
    endpoint_monitoring_provider_v1 = sgqlc.types.Field(sgqlc.types.list_of(EndpointMonitoringProvider_v1), graphql_name='endpoint_monitoring_provider_v1', args=sgqlc.types.ArgDict((
        ('path', sgqlc.types.Arg(String, graphql_name='path', default=None)),
))
    )


class Report_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'app', 'name', 'date', 'content_format_version', 'content')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    app = sgqlc.types.Field(sgqlc.types.non_null(App_v1), graphql_name='app')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    date = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='date')
    content_format_version = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='contentFormatVersion')
    content = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='content')


class ResourceQuotaItemResources_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('limits', 'requests', 'pods')
    limits = sgqlc.types.Field('ResourceValues_v1', graphql_name='limits')
    requests = sgqlc.types.Field('ResourceValues_v1', graphql_name='requests')
    pods = sgqlc.types.Field(Int, graphql_name='pods')


class ResourceQuotaItem_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'resources', 'scopes')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    resources = sgqlc.types.Field(sgqlc.types.non_null(ResourceQuotaItemResources_v1), graphql_name='resources')
    scopes = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='scopes')


class ResourceQuota_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'labels', 'name', 'description', 'quotas')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    quotas = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(ResourceQuotaItem_v1)), graphql_name='quotas')


class ResourceRequirements_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('cpu', 'memory')
    cpu = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='cpu')
    memory = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='memory')


class ResourceValues_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('cpu', 'memory')
    cpu = sgqlc.types.Field(String, graphql_name='cpu')
    memory = sgqlc.types.Field(String, graphql_name='memory')


class Resource_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('path', 'content', 'sha256sum', 'schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    content = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='content')
    sha256sum = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='sha256sum')
    schema = sgqlc.types.Field(String, graphql_name='schema')


class Role_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'expiration_date', 'permissions', 'oidc_permissions', 'tag_on_cluster_updates', 'access', 'aws_groups', 'user_policies', 'sentry_teams', 'sentry_roles', 'sendgrid_accounts', 'owned_saas_files', 'users', 'bots')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    expiration_date = sgqlc.types.Field(String, graphql_name='expirationDate')
    permissions = sgqlc.types.Field(sgqlc.types.list_of(Permission_v1), graphql_name='permissions')
    oidc_permissions = sgqlc.types.Field(sgqlc.types.list_of(OidcPermission_v1), graphql_name='oidc_permissions')
    tag_on_cluster_updates = sgqlc.types.Field(Boolean, graphql_name='tag_on_cluster_updates')
    access = sgqlc.types.Field(sgqlc.types.list_of(Access_v1), graphql_name='access')
    aws_groups = sgqlc.types.Field(sgqlc.types.list_of(AWSGroup_v1), graphql_name='aws_groups')
    user_policies = sgqlc.types.Field(sgqlc.types.list_of(AWSUserPolicy_v1), graphql_name='user_policies')
    sentry_teams = sgqlc.types.Field(sgqlc.types.list_of('SentryTeam_v1'), graphql_name='sentry_teams')
    sentry_roles = sgqlc.types.Field(sgqlc.types.list_of('SentryRole_v1'), graphql_name='sentry_roles')
    sendgrid_accounts = sgqlc.types.Field(sgqlc.types.list_of('SendGridAccount_v1'), graphql_name='sendgrid_accounts')
    owned_saas_files = sgqlc.types.Field(sgqlc.types.list_of('SaasFile_v2'), graphql_name='owned_saas_files')
    users = sgqlc.types.Field(sgqlc.types.list_of('User_v1'), graphql_name='users')
    bots = sgqlc.types.Field(sgqlc.types.list_of(Bot_v1), graphql_name='bots')


class SLODocumentSLOSLOParameters_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('window',)
    window = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='window')


class SLODocumentSLO_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'slitype', 'slispecification', 'slodetails', 'slotarget', 'sloparameters', 'expr', 'slotarget_unit', 'prometheus_rules', 'prometheus_rules_tests', 'dashboard')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    slitype = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='SLIType')
    slispecification = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='SLISpecification')
    slodetails = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='SLODetails')
    slotarget = sgqlc.types.Field(sgqlc.types.non_null(Float), graphql_name='SLOTarget')
    sloparameters = sgqlc.types.Field(sgqlc.types.non_null(SLODocumentSLOSLOParameters_v1), graphql_name='SLOParameters')
    expr = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='expr')
    slotarget_unit = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='SLOTargetUnit')
    prometheus_rules = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='prometheusRules')
    prometheus_rules_tests = sgqlc.types.Field(String, graphql_name='prometheusRulesTests')
    dashboard = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='dashboard')


class SLODocument_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'labels', 'name', 'namespaces', 'slos')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    namespaces = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(Namespace_v1)), graphql_name='namespaces')
    slos = sgqlc.types.Field(sgqlc.types.list_of(SLODocumentSLO_v1), graphql_name='slos')


class SQSQueuesSpecs_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('defaults', 'queues')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    queues = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(KeyValue_v1)), graphql_name='queues')


class SRECheckpoint_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'app', 'date', 'issue')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    app = sgqlc.types.Field(sgqlc.types.non_null(App_v1), graphql_name='app')
    date = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='date')
    issue = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='issue')


class SaasFileAuthentication_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('code', 'image')
    code = sgqlc.types.Field('VaultSecret_v1', graphql_name='code')
    image = sgqlc.types.Field('VaultSecret_v1', graphql_name='image')


class SaasFile_v2(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'app', 'pipelines_provider', 'slack', 'managed_resource_types', 'authentication', 'parameters', 'secret_parameters', 'resource_templates', 'image_patterns', 'takeover', 'compare', 'publish_job_logs', 'cluster_admin', 'use_channel_in_image_tag', 'configurable_resources', 'deploy_resources', 'roles')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    app = sgqlc.types.Field(sgqlc.types.non_null(App_v1), graphql_name='app')
    pipelines_provider = sgqlc.types.Field(sgqlc.types.non_null(PipelinesProvider_v1), graphql_name='pipelinesProvider')
    slack = sgqlc.types.Field('SlackOutput_v1', graphql_name='slack')
    managed_resource_types = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='managedResourceTypes')
    authentication = sgqlc.types.Field(SaasFileAuthentication_v1, graphql_name='authentication')
    parameters = sgqlc.types.Field(JSON, graphql_name='parameters')
    secret_parameters = sgqlc.types.Field(sgqlc.types.list_of('SaasSecretParameters_v1'), graphql_name='secretParameters')
    resource_templates = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('SaasResourceTemplate_v2')), graphql_name='resourceTemplates')
    image_patterns = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='imagePatterns')
    takeover = sgqlc.types.Field(Boolean, graphql_name='takeover')
    compare = sgqlc.types.Field(Boolean, graphql_name='compare')
    publish_job_logs = sgqlc.types.Field(Boolean, graphql_name='publishJobLogs')
    cluster_admin = sgqlc.types.Field(Boolean, graphql_name='clusterAdmin')
    use_channel_in_image_tag = sgqlc.types.Field(Boolean, graphql_name='use_channel_in_image_tag')
    configurable_resources = sgqlc.types.Field(Boolean, graphql_name='configurableResources')
    deploy_resources = sgqlc.types.Field(DeployResources_v1, graphql_name='deployResources')
    roles = sgqlc.types.Field(sgqlc.types.list_of(Role_v1), graphql_name='roles')


class SaasResourceTemplateTargetPromotion_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('auto', 'publish', 'subscribe', 'promotion_data')
    auto = sgqlc.types.Field(Boolean, graphql_name='auto')
    publish = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='publish')
    subscribe = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='subscribe')
    promotion_data = sgqlc.types.Field(sgqlc.types.list_of(PromotionData_v1), graphql_name='promotion_data')


class SaasResourceTemplateTargetUpstream_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('instance', 'name')
    instance = sgqlc.types.Field(sgqlc.types.non_null(JenkinsInstance_v1), graphql_name='instance')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')


class SaasResourceTemplateTarget_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('namespace', 'ref', 'promotion', 'parameters', 'secret_parameters', 'upstream', 'disable', 'delete')
    namespace = sgqlc.types.Field(sgqlc.types.non_null(Namespace_v1), graphql_name='namespace')
    ref = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='ref')
    promotion = sgqlc.types.Field(SaasResourceTemplateTargetPromotion_v1, graphql_name='promotion')
    parameters = sgqlc.types.Field(JSON, graphql_name='parameters')
    secret_parameters = sgqlc.types.Field(sgqlc.types.list_of('SaasSecretParameters_v1'), graphql_name='secretParameters')
    upstream = sgqlc.types.Field(String, graphql_name='upstream')
    disable = sgqlc.types.Field(Boolean, graphql_name='disable')
    delete = sgqlc.types.Field(Boolean, graphql_name='delete')


class SaasResourceTemplateTarget_v2(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('namespace', 'ref', 'promotion', 'parameters', 'secret_parameters', 'upstream', 'disable', 'delete')
    namespace = sgqlc.types.Field(sgqlc.types.non_null(Namespace_v1), graphql_name='namespace')
    ref = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='ref')
    promotion = sgqlc.types.Field(SaasResourceTemplateTargetPromotion_v1, graphql_name='promotion')
    parameters = sgqlc.types.Field(JSON, graphql_name='parameters')
    secret_parameters = sgqlc.types.Field(sgqlc.types.list_of('SaasSecretParameters_v1'), graphql_name='secretParameters')
    upstream = sgqlc.types.Field(SaasResourceTemplateTargetUpstream_v1, graphql_name='upstream')
    disable = sgqlc.types.Field(Boolean, graphql_name='disable')
    delete = sgqlc.types.Field(Boolean, graphql_name='delete')


class SaasResourceTemplate_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'url', 'path', 'provider', 'hash_length', 'parameters', 'secret_parameters', 'targets')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    provider = sgqlc.types.Field(String, graphql_name='provider')
    hash_length = sgqlc.types.Field(Int, graphql_name='hash_length')
    parameters = sgqlc.types.Field(JSON, graphql_name='parameters')
    secret_parameters = sgqlc.types.Field(sgqlc.types.list_of('SaasSecretParameters_v1'), graphql_name='secretParameters')
    targets = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(SaasResourceTemplateTarget_v1)), graphql_name='targets')


class SaasResourceTemplate_v2(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'url', 'path', 'provider', 'hash_length', 'parameters', 'secret_parameters', 'targets')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    provider = sgqlc.types.Field(String, graphql_name='provider')
    hash_length = sgqlc.types.Field(Int, graphql_name='hash_length')
    parameters = sgqlc.types.Field(JSON, graphql_name='parameters')
    secret_parameters = sgqlc.types.Field(sgqlc.types.list_of('SaasSecretParameters_v1'), graphql_name='secretParameters')
    targets = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(SaasResourceTemplateTarget_v2)), graphql_name='targets')


class SaasSecretParameters_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'secret')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    secret = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='secret')


class ScheduleEntry_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('start', 'end', 'users')
    start = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='start')
    end = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='end')
    users = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('User_v1')), graphql_name='users')


class Schedule_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'description', 'schedule')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(String, graphql_name='description')
    schedule = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(ScheduleEntry_v1)), graphql_name='schedule')


class SendGridAccount_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'token')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='token')


class SentryInstance_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'labels', 'name', 'description', 'console_url', 'automation_token', 'admin_user')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    console_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='consoleUrl')
    automation_token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='automationToken')
    admin_user = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='adminUser')


class SentryProjectItems_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'description', 'email_prefix', 'platform', 'sensitive_fields', 'safe_fields', 'auto_resolve_age', 'allowed_domains')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    email_prefix = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='email_prefix')
    platform = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='platform')
    sensitive_fields = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='sensitive_fields')
    safe_fields = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='safe_fields')
    auto_resolve_age = sgqlc.types.Field(Int, graphql_name='auto_resolve_age')
    allowed_domains = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='allowed_domains')


class SentryRole_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('role', 'instance')
    role = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='role')
    instance = sgqlc.types.Field(sgqlc.types.non_null(SentryInstance_v1), graphql_name='instance')


class SentryTeam_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'instance')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    instance = sgqlc.types.Field(sgqlc.types.non_null(SentryInstance_v1), graphql_name='instance')


class ServiceAccountTokenSpec_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'namespace', 'service_account_name')
    name = sgqlc.types.Field(String, graphql_name='name')
    namespace = sgqlc.types.Field(sgqlc.types.non_null(Namespace_v1), graphql_name='namespace')
    service_account_name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='serviceAccountName')


class SeverityPriorityMapping_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('severity', 'priority')
    severity = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='severity')
    priority = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='priority')


class SharedResources_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'openshift_resources', 'openshift_service_account_tokens', 'terraform_resources')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    openshift_resources = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(NamespaceOpenshiftResource_v1)), graphql_name='openshiftResources')
    openshift_service_account_tokens = sgqlc.types.Field(sgqlc.types.list_of(ServiceAccountTokenSpec_v1), graphql_name='openshiftServiceAccountTokens')
    terraform_resources = sgqlc.types.Field(sgqlc.types.list_of(NamespaceTerraformResource_v1), graphql_name='terraformResources')


class SlackOutputNotifications_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('start',)
    start = sgqlc.types.Field(Boolean, graphql_name='start')


class SlackOutput_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('workspace', 'channel', 'icon_emoji', 'username', 'output', 'notifications')
    workspace = sgqlc.types.Field(sgqlc.types.non_null('SlackWorkspace_v1'), graphql_name='workspace')
    channel = sgqlc.types.Field(String, graphql_name='channel')
    icon_emoji = sgqlc.types.Field(String, graphql_name='icon_emoji')
    username = sgqlc.types.Field(String, graphql_name='username')
    output = sgqlc.types.Field(String, graphql_name='output')
    notifications = sgqlc.types.Field(SlackOutputNotifications_v1, graphql_name='notifications')


class SlackWorkspaceApiClientGlobalConfig_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('max_retries', 'timeout')
    max_retries = sgqlc.types.Field(Int, graphql_name='max_retries')
    timeout = sgqlc.types.Field(Int, graphql_name='timeout')


class SlackWorkspaceApiClientMethodConfig_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'args')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    args = sgqlc.types.Field(sgqlc.types.non_null(JSON), graphql_name='args')


class SlackWorkspaceApiClient_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('global_', 'methods')
    global_ = sgqlc.types.Field(SlackWorkspaceApiClientGlobalConfig_v1, graphql_name='global')
    methods = sgqlc.types.Field(sgqlc.types.list_of(SlackWorkspaceApiClientMethodConfig_v1), graphql_name='methods')


class SlackWorkspaceIntegration_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'token', 'channel', 'icon_emoji', 'username')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='token')
    channel = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='channel')
    icon_emoji = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='icon_emoji')
    username = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='username')


class SlackWorkspace_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'token', 'api_client', 'integrations', 'managed_usergroups')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='token')
    api_client = sgqlc.types.Field(SlackWorkspaceApiClient_v1, graphql_name='api_client')
    integrations = sgqlc.types.Field(sgqlc.types.list_of(SlackWorkspaceIntegration_v1), graphql_name='integrations')
    managed_usergroups = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='managedUsergroups')


class SmtpSettings_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('mail_address', 'credentials')
    mail_address = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='mailAddress')
    credentials = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='credentials')


class SqlEmailOverrides_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('db_host', 'db_port', 'db_name', 'db_user', 'db_password')
    db_host = sgqlc.types.Field(String, graphql_name='db_host')
    db_port = sgqlc.types.Field(String, graphql_name='db_port')
    db_name = sgqlc.types.Field(String, graphql_name='db_name')
    db_user = sgqlc.types.Field(String, graphql_name='db_user')
    db_password = sgqlc.types.Field(String, graphql_name='db_password')


class SqlQuerySettings_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('image_repository', 'pull_secret')
    image_repository = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='imageRepository')
    pull_secret = sgqlc.types.Field(sgqlc.types.non_null('NamespaceOpenshiftResourceVaultSecret_v1'), graphql_name='pullSecret')


class StatusPageComponent_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'display_name', 'description', 'instructions', 'page', 'group_name', 'status', 'apps')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    display_name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='displayName')
    description = sgqlc.types.Field(String, graphql_name='description')
    instructions = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='instructions')
    page = sgqlc.types.Field(sgqlc.types.non_null('StatusPage_v1'), graphql_name='page')
    group_name = sgqlc.types.Field(String, graphql_name='groupName')
    status = sgqlc.types.Field(sgqlc.types.list_of('StatusProvider_v1'), graphql_name='status')
    apps = sgqlc.types.Field(sgqlc.types.list_of(App_v1), graphql_name='apps')


class StatusPage_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'url', 'provider', 'api_url', 'credentials', 'page_id', 'components')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    url = sgqlc.types.Field(String, graphql_name='url')
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')
    api_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='apiUrl')
    credentials = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='credentials')
    page_id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='pageId')
    components = sgqlc.types.Field(sgqlc.types.list_of(StatusPageComponent_v1), graphql_name='components')


class StatusProvider_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('provider',)
    provider = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='provider')


class Taint_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('key', 'value', 'effect')
    key = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='key')
    value = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='value')
    effect = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='effect')


class TemplateTest_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'resource_path', 'expected_result')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    resource_path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='resourcePath')
    expected_result = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='expectedResult')


class UnleashFeatureToggle_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'enabled', 'reason')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    enabled = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='enabled')
    reason = sgqlc.types.Field(String, graphql_name='reason')


class UnleashInstance_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'description', 'url', 'token', 'notifications', 'feature_toggles')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='url')
    token = sgqlc.types.Field(sgqlc.types.non_null('VaultSecret_v1'), graphql_name='token')
    notifications = sgqlc.types.Field('UnleashNotifications_v1', graphql_name='notifications')
    feature_toggles = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(UnleashFeatureToggle_v1)), graphql_name='featureToggles')


class UnleashNotifications_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('slack',)
    slack = sgqlc.types.Field(sgqlc.types.list_of(SlackOutput_v1), graphql_name='slack')


class User_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('schema', 'path', 'labels', 'name', 'org_username', 'github_username', 'quay_username', 'slack_username', 'pagerduty_username', 'aws_username', 'public_gpg_key', 'tag_on_merge_requests', 'tag_on_cluster_updates', 'roles', 'requests', 'queries', 'gabi_instances')
    schema = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='schema')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    org_username = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='org_username')
    github_username = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='github_username')
    quay_username = sgqlc.types.Field(String, graphql_name='quay_username')
    slack_username = sgqlc.types.Field(String, graphql_name='slack_username')
    pagerduty_username = sgqlc.types.Field(String, graphql_name='pagerduty_username')
    aws_username = sgqlc.types.Field(String, graphql_name='aws_username')
    public_gpg_key = sgqlc.types.Field(String, graphql_name='public_gpg_key')
    tag_on_merge_requests = sgqlc.types.Field(Boolean, graphql_name='tag_on_merge_requests')
    tag_on_cluster_updates = sgqlc.types.Field(Boolean, graphql_name='tag_on_cluster_updates')
    roles = sgqlc.types.Field(sgqlc.types.list_of(Role_v1), graphql_name='roles')
    requests = sgqlc.types.Field(sgqlc.types.list_of(CredentialsRequest_v1), graphql_name='requests')
    queries = sgqlc.types.Field(sgqlc.types.list_of(AppInterfaceSqlQuery_v1), graphql_name='queries')
    gabi_instances = sgqlc.types.Field(sgqlc.types.list_of(GabiInstance_v1), graphql_name='gabi_instances')


class VaultAuditOptions_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('_type',)
    _type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='_type')


class VaultAudit_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('_path', 'type', 'description', 'options')
    _path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='_path')
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    options = sgqlc.types.Field(sgqlc.types.non_null(VaultAuditOptions_v1), graphql_name='options')


class VaultAuthConfig_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('_type',)
    _type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='_type')


class VaultAuthSettings_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('config',)
    config = sgqlc.types.Field(sgqlc.types.non_null(VaultAuthConfig_v1), graphql_name='config')


class VaultAuth_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('_path', 'type', 'description', 'settings', 'policy_mappings')
    _path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='_path')
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    settings = sgqlc.types.Field(VaultAuthSettings_v1, graphql_name='settings')
    policy_mappings = sgqlc.types.Field(sgqlc.types.list_of('VaultPolicyMapping_v1'), graphql_name='policy_mappings')


class VaultPolicyMapping_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('github_team', 'policies')
    github_team = sgqlc.types.Field(sgqlc.types.non_null('PermissionGithubOrgTeam_v1'), graphql_name='github_team')
    policies = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null('VaultPolicy_v1')), graphql_name='policies')


class VaultPolicy_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'rules')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    rules = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='rules')


class VaultRoleOptions_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('_type',)
    _type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='_type')


class VaultRole_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('name', 'type', 'mount', 'options')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')
    mount = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='mount')
    options = sgqlc.types.Field(sgqlc.types.non_null(VaultRoleOptions_v1), graphql_name='options')


class VaultSecretEngineOptions_v1(sgqlc.types.Interface):
    __schema__ = qontract_schema
    __field_names__ = ('_type',)
    _type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='_type')


class VaultSecretEngine_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('_path', 'type', 'description', 'options')
    _path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='_path')
    type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='type')
    description = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='description')
    options = sgqlc.types.Field(VaultSecretEngineOptions_v1, graphql_name='options')


class VaultSecret_v1(sgqlc.types.Type):
    __schema__ = qontract_schema
    __field_names__ = ('path', 'field', 'format', 'version')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    field = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='field')
    format = sgqlc.types.Field(String, graphql_name='format')
    version = sgqlc.types.Field(Int, graphql_name='version')


class AWSAccountSharingOptionAMI_v1(sgqlc.types.Type, AWSAccountSharingOption_v1):
    __schema__ = qontract_schema
    __field_names__ = ('regex', 'region')
    regex = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='regex')
    region = sgqlc.types.Field(String, graphql_name='region')


class ClusterAuthGithubOrgTeam_v1(sgqlc.types.Type, ClusterAuth_v1):
    __schema__ = qontract_schema
    __field_names__ = ('org', 'team')
    org = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='org')
    team = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='team')


class ClusterAuthGithubOrg_v1(sgqlc.types.Type, ClusterAuth_v1):
    __schema__ = qontract_schema
    __field_names__ = ('org',)
    org = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='org')


class ClusterAuthOIDC_v1(sgqlc.types.Type, ClusterAuth_v1):
    __schema__ = qontract_schema
    __field_names__ = ()


class ClusterPeeringConnectionAccountTGW_v1(sgqlc.types.Type, ClusterPeeringConnection_v1):
    __schema__ = qontract_schema
    __field_names__ = ('account', 'tags', 'manage_security_groups', 'cidr_block', 'assume_role')
    account = sgqlc.types.Field(sgqlc.types.non_null(AWSAccount_v1), graphql_name='account')
    tags = sgqlc.types.Field(JSON, graphql_name='tags')
    manage_security_groups = sgqlc.types.Field(Boolean, graphql_name='manageSecurityGroups')
    cidr_block = sgqlc.types.Field(String, graphql_name='cidrBlock')
    assume_role = sgqlc.types.Field(String, graphql_name='assumeRole')


class ClusterPeeringConnectionAccountVPCMesh_v1(sgqlc.types.Type, ClusterPeeringConnection_v1):
    __schema__ = qontract_schema
    __field_names__ = ('account', 'tags')
    account = sgqlc.types.Field(sgqlc.types.non_null(AWSAccount_v1), graphql_name='account')
    tags = sgqlc.types.Field(JSON, graphql_name='tags')


class ClusterPeeringConnectionAccount_v1(sgqlc.types.Type, ClusterPeeringConnection_v1):
    __schema__ = qontract_schema
    __field_names__ = ('vpc', 'assume_role')
    vpc = sgqlc.types.Field(sgqlc.types.non_null(AWSVPC_v1), graphql_name='vpc')
    assume_role = sgqlc.types.Field(String, graphql_name='assumeRole')


class ClusterPeeringConnectionClusterAccepter_v1(sgqlc.types.Type, ClusterPeeringConnection_v1):
    __schema__ = qontract_schema
    __field_names__ = ('cluster', 'aws_infrastructure_management_account', 'assume_role')
    cluster = sgqlc.types.Field(sgqlc.types.non_null(Cluster_v1), graphql_name='cluster')
    aws_infrastructure_management_account = sgqlc.types.Field(AWSAccount_v1, graphql_name='awsInfrastructureManagementAccount')
    assume_role = sgqlc.types.Field(String, graphql_name='assumeRole')


class ClusterPeeringConnectionClusterRequester_v1(sgqlc.types.Type, ClusterPeeringConnection_v1):
    __schema__ = qontract_schema
    __field_names__ = ('cluster', 'assume_role')
    cluster = sgqlc.types.Field(sgqlc.types.non_null(Cluster_v1), graphql_name='cluster')
    assume_role = sgqlc.types.Field(String, graphql_name='assumeRole')


class EndpointMonitoringProviderBlackboxExporter_v1(sgqlc.types.Type, EndpointMonitoringProvider_v1):
    __schema__ = qontract_schema
    __field_names__ = ('blackbox_exporter',)
    blackbox_exporter = sgqlc.types.Field(sgqlc.types.non_null(EndpointMonitoringProviderBlackboxExporterSettings_v1), graphql_name='blackboxExporter')


class EndpointMonitoringProviderSignalFx_v1(sgqlc.types.Type, EndpointMonitoringProvider_v1):
    __schema__ = qontract_schema
    __field_names__ = ('signal_fx',)
    signal_fx = sgqlc.types.Field(sgqlc.types.non_null(EndpointMonitoringProviderSignalFxSettings_v1), graphql_name='signalFx')


class ManualStatusProvider_v1(sgqlc.types.Type, StatusProvider_v1):
    __schema__ = qontract_schema
    __field_names__ = ('manual',)
    manual = sgqlc.types.Field(sgqlc.types.non_null(ManualStatusProviderConfig_v1), graphql_name='manual')


class NamespaceOpenshiftResourceResourceTemplate_v1(sgqlc.types.Type, NamespaceOpenshiftResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('path', 'type', 'variables', 'validate_alertmanager_config', 'alertmanager_config_key')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    type = sgqlc.types.Field(String, graphql_name='type')
    variables = sgqlc.types.Field(JSON, graphql_name='variables')
    validate_alertmanager_config = sgqlc.types.Field(Boolean, graphql_name='validate_alertmanager_config')
    alertmanager_config_key = sgqlc.types.Field(String, graphql_name='alertmanager_config_key')


class NamespaceOpenshiftResourceResource_v1(sgqlc.types.Type, NamespaceOpenshiftResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('path', 'validate_json', 'validate_alertmanager_config', 'alertmanager_config_key')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    validate_json = sgqlc.types.Field(Boolean, graphql_name='validate_json')
    validate_alertmanager_config = sgqlc.types.Field(Boolean, graphql_name='validate_alertmanager_config')
    alertmanager_config_key = sgqlc.types.Field(String, graphql_name='alertmanager_config_key')


class NamespaceOpenshiftResourceRoute_v1(sgqlc.types.Type, NamespaceOpenshiftResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('path', 'vault_tls_secret_path', 'vault_tls_secret_version')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    vault_tls_secret_path = sgqlc.types.Field(String, graphql_name='vault_tls_secret_path')
    vault_tls_secret_version = sgqlc.types.Field(Int, graphql_name='vault_tls_secret_version')


class NamespaceOpenshiftResourceVaultSecret_v1(sgqlc.types.Type, NamespaceOpenshiftResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('path', 'version', 'name', 'labels', 'annotations', 'type', 'validate_alertmanager_config', 'alertmanager_config_key')
    path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='path')
    version = sgqlc.types.Field(sgqlc.types.non_null(Int), graphql_name='version')
    name = sgqlc.types.Field(String, graphql_name='name')
    labels = sgqlc.types.Field(JSON, graphql_name='labels')
    annotations = sgqlc.types.Field(JSON, graphql_name='annotations')
    type = sgqlc.types.Field(String, graphql_name='type')
    validate_alertmanager_config = sgqlc.types.Field(Boolean, graphql_name='validate_alertmanager_config')
    alertmanager_config_key = sgqlc.types.Field(String, graphql_name='alertmanager_config_key')


class NamespaceTerraformResourceACM_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'secret', 'domain')
    region = sgqlc.types.Field(String, graphql_name='region')
    secret = sgqlc.types.Field(VaultSecret_v1, graphql_name='secret')
    domain = sgqlc.types.Field(ACMDomain_v1, graphql_name='domain')


class NamespaceTerraformResourceALB_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'vpc', 'certificate_arn', 'idle_timeout', 'targets', 'rules')
    region = sgqlc.types.Field(String, graphql_name='region')
    vpc = sgqlc.types.Field(sgqlc.types.non_null(AWSVPC_v1), graphql_name='vpc')
    certificate_arn = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='certificate_arn')
    idle_timeout = sgqlc.types.Field(Int, graphql_name='idle_timeout')
    targets = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(NamespaceTerraformResourceALBTargets_v1)), graphql_name='targets')
    rules = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(NamespaceTerraformResourceALBRules_v1)), graphql_name='rules')


class NamespaceTerraformResourceASG_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'defaults', 'cloudinit_configs', 'variables', 'image')
    region = sgqlc.types.Field(String, graphql_name='region')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    cloudinit_configs = sgqlc.types.Field(sgqlc.types.list_of(CloudinitConfig_v1), graphql_name='cloudinit_configs')
    variables = sgqlc.types.Field(JSON, graphql_name='variables')
    image = sgqlc.types.Field(sgqlc.types.non_null(ASGImage_v1), graphql_name='image')


class NamespaceTerraformResourceCloudWatch_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'defaults', 'es_identifier', 'filter_pattern')
    region = sgqlc.types.Field(String, graphql_name='region')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    es_identifier = sgqlc.types.Field(String, graphql_name='es_identifier')
    filter_pattern = sgqlc.types.Field(String, graphql_name='filter_pattern')


class NamespaceTerraformResourceDynamoDB_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'specs')
    region = sgqlc.types.Field(String, graphql_name='region')
    specs = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(DynamoDBTableSpecs_v1)), graphql_name='specs')


class NamespaceTerraformResourceECR_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'mirror', 'public')
    region = sgqlc.types.Field(String, graphql_name='region')
    mirror = sgqlc.types.Field(ContainerImageMirror_v1, graphql_name='mirror')
    public = sgqlc.types.Field(Boolean, graphql_name='public')


class NamespaceTerraformResourceElastiCache_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('defaults', 'parameter_group', 'region', 'overrides')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    parameter_group = sgqlc.types.Field(String, graphql_name='parameter_group')
    region = sgqlc.types.Field(String, graphql_name='region')
    overrides = sgqlc.types.Field(JSON, graphql_name='overrides')


class NamespaceTerraformResourceElasticSearch_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'defaults', 'publish_log_types')
    region = sgqlc.types.Field(String, graphql_name='region')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    publish_log_types = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='publish_log_types')


class NamespaceTerraformResourceGenericSecretOutputFormat_v1(sgqlc.types.Type, NamespaceTerraformResourceOutputFormat_v1):
    __schema__ = qontract_schema
    __field_names__ = ('data',)
    data = sgqlc.types.Field(JSON, graphql_name='data')


class NamespaceTerraformResourceKMS_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'defaults', 'overrides')
    region = sgqlc.types.Field(String, graphql_name='region')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    overrides = sgqlc.types.Field(JSON, graphql_name='overrides')


class NamespaceTerraformResourceKinesis_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'defaults', 'overrides')
    region = sgqlc.types.Field(String, graphql_name='region')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    overrides = sgqlc.types.Field(JSON, graphql_name='overrides')


class NamespaceTerraformResourceRDS_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'defaults', 'availability_zone', 'parameter_group', 'overrides', 'output_resource_db_name', 'reset_password', 'enhanced_monitoring', 'replica_source', 'ca_cert')
    region = sgqlc.types.Field(String, graphql_name='region')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    availability_zone = sgqlc.types.Field(String, graphql_name='availability_zone')
    parameter_group = sgqlc.types.Field(String, graphql_name='parameter_group')
    overrides = sgqlc.types.Field(JSON, graphql_name='overrides')
    output_resource_db_name = sgqlc.types.Field(String, graphql_name='output_resource_db_name')
    reset_password = sgqlc.types.Field(String, graphql_name='reset_password')
    enhanced_monitoring = sgqlc.types.Field(Boolean, graphql_name='enhanced_monitoring')
    replica_source = sgqlc.types.Field(String, graphql_name='replica_source')
    ca_cert = sgqlc.types.Field(VaultSecret_v1, graphql_name='ca_cert')


class NamespaceTerraformResourceRole_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('assume_role', 'assume_condition', 'inline_policy')
    assume_role = sgqlc.types.Field(sgqlc.types.non_null(AssumeRole_v1), graphql_name='assume_role')
    assume_condition = sgqlc.types.Field(JSON, graphql_name='assume_condition')
    inline_policy = sgqlc.types.Field(JSON, graphql_name='inline_policy')


class NamespaceTerraformResourceRoute53Zone_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'name')
    region = sgqlc.types.Field(String, graphql_name='region')
    name = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='name')


class NamespaceTerraformResourceS3CloudFrontPublicKey_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'secret')
    region = sgqlc.types.Field(String, graphql_name='region')
    secret = sgqlc.types.Field(VaultSecret_v1, graphql_name='secret')


class NamespaceTerraformResourceS3CloudFront_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'defaults', 'storage_class')
    region = sgqlc.types.Field(String, graphql_name='region')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    storage_class = sgqlc.types.Field(String, graphql_name='storage_class')


class NamespaceTerraformResourceS3SQS_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'kms_encryption', 'defaults', 'storage_class')
    region = sgqlc.types.Field(String, graphql_name='region')
    kms_encryption = sgqlc.types.Field(Boolean, graphql_name='kms_encryption')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    storage_class = sgqlc.types.Field(String, graphql_name='storage_class')


class NamespaceTerraformResourceS3_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'defaults', 'overrides', 'event_notifications', 'sqs_identifier', 's3_events', 'bucket_policy', 'storage_class')
    region = sgqlc.types.Field(String, graphql_name='region')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='defaults')
    overrides = sgqlc.types.Field(JSON, graphql_name='overrides')
    event_notifications = sgqlc.types.Field(sgqlc.types.list_of(AWSS3EventNotification_v1), graphql_name='event_notifications')
    sqs_identifier = sgqlc.types.Field(String, graphql_name='sqs_identifier')
    s3_events = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='s3_events')
    bucket_policy = sgqlc.types.Field(JSON, graphql_name='bucket_policy')
    storage_class = sgqlc.types.Field(String, graphql_name='storage_class')


class NamespaceTerraformResourceSQS_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'specs')
    region = sgqlc.types.Field(String, graphql_name='region')
    specs = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(SQSQueuesSpecs_v1)), graphql_name='specs')


class NamespaceTerraformResourceSecretsManager_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('region', 'secret')
    region = sgqlc.types.Field(String, graphql_name='region')
    secret = sgqlc.types.Field(VaultSecret_v1, graphql_name='secret')


class NamespaceTerraformResourceServiceAccount_v1(sgqlc.types.Type, NamespaceTerraformResource_v1):
    __schema__ = qontract_schema
    __field_names__ = ('variables', 'policies', 'user_policy', 'aws_infrastructure_access')
    variables = sgqlc.types.Field(JSON, graphql_name='variables')
    policies = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='policies')
    user_policy = sgqlc.types.Field(JSON, graphql_name='user_policy')
    aws_infrastructure_access = sgqlc.types.Field(NamespaceTerraformResourceServiceAccountAWSInfrastructureAccess_v1, graphql_name='aws_infrastructure_access')


class OidcPermissionVault_v1(sgqlc.types.Type, OidcPermission_v1):
    __schema__ = qontract_schema
    __field_names__ = ('vault_policies',)
    vault_policies = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(VaultPolicy_v1)), graphql_name='vault_policies')


class ParentSaasPromotion_v1(sgqlc.types.Type, PromotionChannelData_v1):
    __schema__ = qontract_schema
    __field_names__ = ('parent_saas', 'target_config_hash')
    parent_saas = sgqlc.types.Field(String, graphql_name='parent_saas')
    target_config_hash = sgqlc.types.Field(String, graphql_name='target_config_hash')


class PermissionGithubOrgTeam_v1(sgqlc.types.Type, Permission_v1):
    __schema__ = qontract_schema
    __field_names__ = ('org', 'team', 'role')
    org = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='org')
    team = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='team')
    role = sgqlc.types.Field(String, graphql_name='role')


class PermissionGithubOrg_v1(sgqlc.types.Type, Permission_v1):
    __schema__ = qontract_schema
    __field_names__ = ('org', 'role')
    org = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='org')
    role = sgqlc.types.Field(String, graphql_name='role')


class PermissionGitlabGroupMembership_v1(sgqlc.types.Type, Permission_v1):
    __schema__ = qontract_schema
    __field_names__ = ('group', 'access')
    group = sgqlc.types.Field(String, graphql_name='group')
    access = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='access')


class PermissionJenkinsRole_v1(sgqlc.types.Type, Permission_v1):
    __schema__ = qontract_schema
    __field_names__ = ('instance', 'role', 'token')
    instance = sgqlc.types.Field(sgqlc.types.non_null(JenkinsInstance_v1), graphql_name='instance')
    role = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='role')
    token = sgqlc.types.Field(sgqlc.types.non_null(VaultSecret_v1), graphql_name='token')


class PermissionQuayOrgTeam_v1(sgqlc.types.Type, Permission_v1):
    __schema__ = qontract_schema
    __field_names__ = ('quay_org', 'team')
    quay_org = sgqlc.types.Field(sgqlc.types.non_null(QuayOrg_v1), graphql_name='quayOrg')
    team = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='team')


class PermissionSlackUsergroup_v1(sgqlc.types.Type, Permission_v1):
    __schema__ = qontract_schema
    __field_names__ = ('handle', 'workspace', 'pagerduty', 'channels', 'owners_from_repos', 'schedule', 'skip', 'roles')
    handle = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='handle')
    workspace = sgqlc.types.Field(sgqlc.types.non_null(SlackWorkspace_v1), graphql_name='workspace')
    pagerduty = sgqlc.types.Field(sgqlc.types.list_of(PagerDutyTarget_v1), graphql_name='pagerduty')
    channels = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='channels')
    owners_from_repos = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='ownersFromRepos')
    schedule = sgqlc.types.Field(Schedule_v1, graphql_name='schedule')
    skip = sgqlc.types.Field(Boolean, graphql_name='skip')
    roles = sgqlc.types.Field(sgqlc.types.list_of(Role_v1), graphql_name='roles')


class PipelinesProviderTekton_v1(sgqlc.types.Type, PipelinesProvider_v1):
    __schema__ = qontract_schema
    __field_names__ = ('defaults', 'namespace', 'retention', 'task_templates', 'pipeline_templates', 'deploy_resources')
    defaults = sgqlc.types.Field(sgqlc.types.non_null(PipelinesProviderTektonProviderDefaults_v1), graphql_name='defaults')
    namespace = sgqlc.types.Field(sgqlc.types.non_null(Namespace_v1), graphql_name='namespace')
    retention = sgqlc.types.Field(PipelinesProviderRetention_v1, graphql_name='retention')
    task_templates = sgqlc.types.Field(sgqlc.types.list_of(PipelinesProviderTektonObjectTemplate_v1), graphql_name='taskTemplates')
    pipeline_templates = sgqlc.types.Field(PipelinesProviderPipelineTemplates_v1, graphql_name='pipelineTemplates')
    deploy_resources = sgqlc.types.Field(DeployResources_v1, graphql_name='deployResources')


class PrometheusAlertsStatusProvider_v1(sgqlc.types.Type, StatusProvider_v1):
    __schema__ = qontract_schema
    __field_names__ = ('prometheus_alerts',)
    prometheus_alerts = sgqlc.types.Field(sgqlc.types.non_null(PrometheusAlertsStatusProviderConfig_v1), graphql_name='prometheusAlerts')


class VaultApproleOptions_v1(sgqlc.types.Type, VaultRoleOptions_v1):
    __schema__ = qontract_schema
    __field_names__ = ('bind_secret_id', 'local_secret_ids', 'token_period', 'secret_id_num_uses', 'secret_id_ttl', 'token_explicit_max_ttl', 'token_max_ttl', 'token_no_default_policy', 'token_num_uses', 'token_ttl', 'token_type', 'token_policies', 'policies', 'secret_id_bound_cidrs', 'token_bound_cidrs')
    bind_secret_id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='bind_secret_id')
    local_secret_ids = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='local_secret_ids')
    token_period = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_period')
    secret_id_num_uses = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='secret_id_num_uses')
    secret_id_ttl = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='secret_id_ttl')
    token_explicit_max_ttl = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_explicit_max_ttl')
    token_max_ttl = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_max_ttl')
    token_no_default_policy = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='token_no_default_policy')
    token_num_uses = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_num_uses')
    token_ttl = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_ttl')
    token_type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_type')
    token_policies = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='token_policies')
    policies = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='policies')
    secret_id_bound_cidrs = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='secret_id_bound_cidrs')
    token_bound_cidrs = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='token_bound_cidrs')


class VaultAuditOptionsFile_v1(sgqlc.types.Type, VaultAuditOptions_v1):
    __schema__ = qontract_schema
    __field_names__ = ('file_path', 'log_raw', 'hmac_accessor', 'mode', 'format', 'prefix')
    file_path = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='file_path')
    log_raw = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='log_raw')
    hmac_accessor = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='hmac_accessor')
    mode = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='mode')
    format = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='format')
    prefix = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='prefix')


class VaultAuthConfigGithub_v1(sgqlc.types.Type, VaultAuthConfig_v1):
    __schema__ = qontract_schema
    __field_names__ = ('organization', 'base_url', 'max_ttl', 'ttl')
    organization = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='organization')
    base_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='base_url')
    max_ttl = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='max_ttl')
    ttl = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='ttl')


class VaultAuthConfigOidc_v1(sgqlc.types.Type, VaultAuthConfig_v1):
    __schema__ = qontract_schema
    __field_names__ = ('oidc_discovery_url', 'oidc_client_id', 'oidc_client_secret', 'default_role')
    oidc_discovery_url = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='oidc_discovery_url')
    oidc_client_id = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='oidc_client_id')
    oidc_client_secret = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='oidc_client_secret')
    default_role = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='default_role')


class VaultRoleOidcOptions_v1(sgqlc.types.Type, VaultRoleOptions_v1):
    __schema__ = qontract_schema
    __field_names__ = ('allowed_redirect_uris', 'bound_audiences', 'bound_claims', 'bound_claims_type', 'bound_subject', 'claim_mappings', 'clock_skew_leeway', 'expiration_leeway', 'groups_claim', 'max_age', 'not_before_leeway', 'oidc_scopes', 'role_type', 'token_ttl', 'token_max_ttl', 'token_explicit_max_ttl', 'token_type', 'token_period', 'token_policies', 'token_bound_cidrs', 'token_no_default_policy', 'token_num_uses', 'user_claim', 'verbose_oidc_logging')
    allowed_redirect_uris = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='allowed_redirect_uris')
    bound_audiences = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='bound_audiences')
    bound_claims = sgqlc.types.Field(JSON, graphql_name='bound_claims')
    bound_claims_type = sgqlc.types.Field(String, graphql_name='bound_claims_type')
    bound_subject = sgqlc.types.Field(String, graphql_name='bound_subject')
    claim_mappings = sgqlc.types.Field(JSON, graphql_name='claim_mappings')
    clock_skew_leeway = sgqlc.types.Field(String, graphql_name='clock_skew_leeway')
    expiration_leeway = sgqlc.types.Field(String, graphql_name='expiration_leeway')
    groups_claim = sgqlc.types.Field(String, graphql_name='groups_claim')
    max_age = sgqlc.types.Field(String, graphql_name='max_age')
    not_before_leeway = sgqlc.types.Field(String, graphql_name='not_before_leeway')
    oidc_scopes = sgqlc.types.Field(sgqlc.types.list_of(String), graphql_name='oidc_scopes')
    role_type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='role_type')
    token_ttl = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_ttl')
    token_max_ttl = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_max_ttl')
    token_explicit_max_ttl = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_explicit_max_ttl')
    token_type = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_type')
    token_period = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_period')
    token_policies = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='token_policies')
    token_bound_cidrs = sgqlc.types.Field(sgqlc.types.list_of(sgqlc.types.non_null(String)), graphql_name='token_bound_cidrs')
    token_no_default_policy = sgqlc.types.Field(sgqlc.types.non_null(Boolean), graphql_name='token_no_default_policy')
    token_num_uses = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='token_num_uses')
    user_claim = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='user_claim')
    verbose_oidc_logging = sgqlc.types.Field(Boolean, graphql_name='verbose_oidc_logging')


class VaultSecretEngineOptionsKV_v1(sgqlc.types.Type, VaultSecretEngineOptions_v1):
    __schema__ = qontract_schema
    __field_names__ = ('version',)
    version = sgqlc.types.Field(sgqlc.types.non_null(String), graphql_name='version')



########################################################################
# Unions
########################################################################

########################################################################
# Schema Entry Points
########################################################################
qontract_schema.query_type = Query
qontract_schema.mutation_type = None
qontract_schema.subscription_type = None

