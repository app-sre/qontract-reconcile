import utils.vault_client as vault_client


def read(secret, settings=None):
    """Returns a value of a key from Vault secret or configuration file.

    The input secret is a dictionary which contains the following fields:
    * path - path to the secret in Vault or config
    * field - the key to read from the secret
    * format (optional) - plain or base64 (defaults to plain)
    * version (optional) - Vault secret version to read
      * Note: if this is Vault secret and a v2 KV engine

    The input settings is an optional app-interface-settings object
    queried from app-interface. It is a dictionary containing `value: true`
    if Vault is to be used as the secret backend.

    Default vault setting is false, to allow using a config file
    without creating app-interface-settings.
    """

    if settings and settings.get('vault'):
        return vault_client.read(secret)
    else:
        raise NotImplementedError(
            'reading secrets from a config file is not yet implemented')


def read_all(secret, settings=None):
    """Returns a dictionary of keys and values
    from Vault secret or configuration file.

    The input secret is a dictionary which contains the following fields:
    * path - path to the secret in Vault or config
    * version (optional) - Vault secret version to read
      * Note: if this is Vault secret and a v2 KV engine

    The input settings is an optional app-interface-settings object
    queried from app-interface. It is a dictionary containing `value: true`
    if Vault is to be used as the secret backend.

    Default vault setting is false, to allow using a config file
    without creating app-interface-settings.
    """

    if settings and settings.get('vault'):
        return vault_client.read_all(secret)
    else:
        raise NotImplementedError(
            'reading secrets from a config file is not yet implemented')
