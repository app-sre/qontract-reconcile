from __future__ import annotations

# Shared between qontract_api's ManagedSsoClientSettings.default_output_vault_path_prefix
# (the configurable default) and reconcile's openshift-managed-sso-client-secrets
# integration (which resolves the same path independently, since it has no
# other way to learn qontract-api's resolved setting value). Keeping this
# constant here, importable by both packages under ADR-007's import rules,
# at least keeps the *default* in sync - an operator-configured override of
# the qontract-api setting is still not visible to reconcile.
DEFAULT_OUTPUT_VAULT_PATH_PREFIX = (
    "app-sre/integrations-throughput/managed-sso-client/output"
)


def derive_managed_sso_client_id(app_name: str, name: str) -> str:
    """OIDC clientId derivation.

    Shared by managed_sso_client.integration and
    openshift_managed_sso_client_secrets - see the design doc's "Client naming" section.
    """
    return f"{app_name}-{name}".lower()
