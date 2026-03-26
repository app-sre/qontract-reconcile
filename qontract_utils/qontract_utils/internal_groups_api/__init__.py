"""Internal Groups API client and models.

Provides a client for fetching LDAP group memberships via an OAuth2-protected
internal groups proxy API.

Layer 1 (Pure Communication):
- InternalGroupsApi: Stateless API client with OAuth2 client-credentials flow
- Models: Pydantic models for group members
"""

from qontract_utils.internal_groups_api.api import InternalGroupsApi, TokenExpiredError
from qontract_utils.internal_groups_api.models import Group, GroupMember

__all__ = [
    "Group",
    "GroupMember",
    "InternalGroupsApi",
    "TokenExpiredError",
]
