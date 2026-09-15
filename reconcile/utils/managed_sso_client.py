from __future__ import annotations

# Must stay in sync with qontract-api's
# ManagedSsoClientSettings.default_output_vault_path_prefix default
# (qontract_api/qontract_api/config.py) - this is the only way this
# reconcile-side default can be resolved, since qontract-api's config value
# is never exposed back through app-interface data.
DEFAULT_OUTPUT_VAULT_PATH_PREFIX = (
    "app-sre/integrations-throughput/managed-sso-client/output"
)


def derive_managed_sso_client_id(app_name: str, name: str) -> str:
    """OIDC clientId derivation, shared by managed_sso_client.integration and
    openshift_managed_sso_client_secrets - see the design doc's "Client naming" section."""
    return f"{app_name}-{name}".lower()
