import datetime
from collections.abc import Iterable
from typing import (
    Optional,
    Protocol,
    TypeVar,
    Union,
    cast,
)

DATE_FORMAT = "%Y-%m-%d"


class FilterableRole(Protocol):
    expiration_date: Optional[str]


DictsOrRoles = TypeVar(
    "DictsOrRoles", bound=Union[Iterable[FilterableRole], Iterable[dict]]
)


def date_expired(date: str) -> bool:
    exp_date = datetime.datetime.strptime(date, DATE_FORMAT).date()
    current_date = datetime.datetime.utcnow().date()
    return current_date >= exp_date


def filter(roles: Optional[DictsOrRoles]) -> DictsOrRoles:
    """Filters roles and returns the ones which are not yet expired."""
    filtered = []
    for r in roles or []:
        if isinstance(r, dict):
            key = "expirationDate"
            expiration_date = r.get(key)
        else:
            key = "expiration_date"
            expiration_date = r.expiration_date

        try:
            if not expiration_date or not date_expired(expiration_date):
                filtered.append(r)
        except ValueError:
            raise ValueError(
                f"{key} field is not formatted as YYYY-MM-DD, currently set as {expiration_date}"
            )

    return cast(DictsOrRoles, filtered)
