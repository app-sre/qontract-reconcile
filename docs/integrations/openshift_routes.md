# Manage Routes via App-Interface (`/openshift/namespace-1.yml`) using Vault

In order to add Routes to a namespace, you need to add them to the `openshiftResources` section of a namespace file with the following attributes:

- `provider`: must be `route`
- `path`: path relative to the resources directory. Note that it starts with `/`.
- `vault_tls_secret_path`: (optional) absolute path to secret in Vault which contains sensitive data to be added to the `.spec.tls` section.
- `vault_tls_secret_version`: (optional, mandatory if `vault_tls_secret_path` is defined) version of secret in Vault.

Notes:
* In case the Route contains no sensitive information, a secret in Vault is not required (hence the fields are optional).
* It is recommended to read through the instructions for [Secrets](/docs/integrations/openshift_vault_secrets.md) before using Routes.
