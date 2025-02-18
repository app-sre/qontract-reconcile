from collections import Counter
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


class MatchLabelsNotUniqueError(Exception):
    pass


def validate_label_specs(specs: Mapping[str, FleetLabelsSpecV1]) -> None:
    """
    We cannot catch all potential errors through json schema definition.
    """
    for spec in specs.values():
        _validate_ocm_token_spec(spec.ocm)
        _validate_match_labels(spec)
        _validate_unique_ocm_managed_label_combo(spec)


def _validate_unique_ocm_managed_label_combo(spec: FleetLabelsSpecV1) -> None:
    """
    Every fleet labeler spec is pinned to one OCM client and manages a single
    label prefix. We must be sure, that the label prefixes are not overlapping
    for the same OCM client, as that would mean to default label specs will be
    competing.
    """
    # TODO: implement
    pass


def _validate_match_labels(spec: FleetLabelsSpecV1) -> None:
    """
    Match labels should be unique within the same spec.
    """
    for label_default in spec.label_defaults:
        keys = (
            ".".join(
                f"{k}:{v}"
                for k, v in sorted(
                    dict(label_default.match_subscription_labels).items()
                )
            )
            for label_default in spec.label_defaults
        )
        duplicates = [key for key, count in Counter(keys).items() if count > 1]
        if duplicates:
            raise MatchLabelsNotUniqueError(
                f"The 'matchSubscriptionLabels' combinations must be unique within a spec. Found duplicates in spec {spec.name} for matchers: {duplicates}"
            )


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
