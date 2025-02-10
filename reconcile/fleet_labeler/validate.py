from collections.abc import Mapping

from reconcile.gql_definitions.fleet_labeler.fleet_labels import (
    FleetLabelsSpecV1,
    OpenShiftClusterManagerV1,
)


class OCMAccessTokenClientIdMissing(Exception):
    pass


class OCMAccessTokenClientSecretMissing(Exception):
    pass


class OCMAccessTokenUrlMissing(Exception):
    pass


def validate_label_specs(specs: Mapping[str, FleetLabelsSpecV1]) -> None:
    """
    We cannot catch all potential errors through json schema definition.
    """
    for spec in specs.values():
        _validate_ocm_token_spec(spec.ocm)


def _validate_ocm_token_spec(ocm: OpenShiftClusterManagerV1) -> None:
    """
    OCM tokens are optional in the schema. Lets verify they exist.
    """
    if not ocm.access_token_client_id:
        raise OCMAccessTokenClientIdMissing(
            f"accessTokenClientId missing in ocm spec '{ocm.name}'"
        )
    if not ocm.access_token_client_secret:
        raise OCMAccessTokenClientSecretMissing(
            f"accessTokenClientSecret missing in ocm spec '{ocm.name}'"
        )
    if not ocm.access_token_url:
        raise OCMAccessTokenUrlMissing(
            f"accessTokenUrl missing in ocm spec '{ocm.name}'"
        )
