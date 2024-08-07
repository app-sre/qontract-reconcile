from collections.abc import Iterable

from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)


class SecretNotUniqueError(Exception):
    pass


class TokenNameNotUniqueInSecretError(Exception):
    pass


class KeyNameNotUniqueInSecretError(Exception):
    pass


def validate_token_specs(specs: Iterable[DynatraceTokenProviderTokenSpecV1]) -> None:
    """
    We cannot catch all potential errors through json schema definition.
    """
    for spec in specs:
        seen_secrets: set[str] = set()
        for secret in spec.secrets:
            secret_definition_key = f"{secret.namespace}/{secret.name}"
            if secret_definition_key in seen_secrets:
                raise SecretNotUniqueError(
                    f"A secret cannot be re-defined and must be unique per spec. Secret '{secret.name}' in namespace '{secret.namespace}' is defined multiple times in spec '{spec.name}'."
                )
            seen_secrets.add(secret_definition_key)

            seen_tokens: set[str] = set()
            seen_key_names: set[str] = set()
            for token in secret.tokens:
                if token.name in seen_tokens:
                    raise TokenNameNotUniqueInSecretError(
                        f"A token name must be unique within a secret. Token name '{token.name}' is used more than once in secret '{secret.name}' in token spec '{spec.name}'."
                    )
                seen_tokens.add(token.name)

                secret_key = token.key_name_in_secret or token.name
                if secret_key in seen_key_names:
                    raise KeyNameNotUniqueInSecretError(
                        f"A key name must be unique within a secret. Key name '{secret_key}' is used more than once in secret '{secret.name}' in token spec '{spec.name}'."
                    )
                seen_key_names.add(secret_key)
