"""OCM API exceptions.

Typed exceptions for specific OCM error responses that callers need to
distinguish from generic HTTP failures.
"""

from __future__ import annotations


class OcmUserRoleNotLinkedError(Exception):
    """The STS user_role is not linked to the OCM account.

    OCM returns a 400 with Error_Key=UserRoleIsNotLinkedToAccount when mutating
    identity providers on a cluster whose tenant hasn't linked their STS user role
    to their Red Hat account. Not actionable by AppSRE - the tenant must fix this
    on their side.
    """

    def __init__(self, *, cluster_id: str, reason: str) -> None:
        self.cluster_id = cluster_id
        self.reason = reason
        super().__init__(
            f"Cluster {cluster_id}: STS user_role not linked to account: {reason}"
        )
