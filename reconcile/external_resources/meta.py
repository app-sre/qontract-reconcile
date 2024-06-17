from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "external_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


SECRET_ANN_PREFIX = "external-resources"
SECRET_ANN_PROVISION_PROVIDER = SECRET_ANN_PREFIX + "/provision_provider"
SECRET_ANN_PROVISIONER = SECRET_ANN_PREFIX + "/provisioner_name"
SECRET_ANN_PROVIDER = SECRET_ANN_PREFIX + "/provider"
SECRET_ANN_IDENTIFIER = SECRET_ANN_PREFIX + "/identifier"
SECRET_UPDATED_AT = SECRET_ANN_PREFIX + "/updated_at"
SECRET_UPDATED_AT_TIMEFORMAT = "%Y-%m-%dT%H:%M:%SZ"
