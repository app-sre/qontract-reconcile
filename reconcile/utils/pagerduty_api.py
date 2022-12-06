import logging
from collections.abc import (
    Callable,
    Iterable,
)
from datetime import datetime as dt
from typing import (
    Optional,
    Protocol,
)

import pypd
import requests
from pydantic import BaseModel
from sretoolbox.utils import retry

from reconcile.utils.secret_reader import (
    HasSecret,
    SecretReader,
)


class PagerDutyTargetException(Exception):
    pass


class PagerDutyInstance(Protocol):
    """This protocol defines mandatory attributes/methods
    which must be implemented by a class to be compatible."""

    name: str

    @property
    def token(self) -> HasSecret:
        pass


class PagerDutyUser(Protocol):
    """This protocol defines mandatory attributes/methods
    which must be implemented by a class to be compatible."""

    org_username: str
    pagerduty_username: Optional[str]


class PagerDutyTarget(Protocol):
    """This protocol defines mandatory attributes/methods
    which must be implemented by a class to be compatible."""

    name: str
    instance: PagerDutyInstance
    escalation_policy_id: Optional[str]
    schedule_id: Optional[str]


class PagerDutyConfig(BaseModel):
    """PagerDuty Config."""

    name: str
    token: str


class PagerDutyApi:
    """Wrapper around PagerDuty API calls"""

    def __init__(self, token: str, init_users: bool = True) -> None:
        pypd.api_key = token
        if init_users:
            self.init_users()
        else:
            self.users: list[pypd.User] = []

    def init_users(self) -> None:
        self.users = pypd.User.find()

    def get_pagerduty_users(
        self, resource_type: str, resource_id: str
    ) -> list[pypd.User]:
        now = dt.utcnow()

        try:
            if resource_type == "schedule":
                users = self.get_schedule_users(resource_id, now)
            elif resource_type == "escalationPolicy":
                users = self.get_escalation_policy_users(resource_id, now)
        except requests.exceptions.HTTPError as e:
            logging.warning(str(e))
            return []

        return users

    def get_user(self, user_id: str) -> str:
        for user in self.users:
            if user.id == user_id:
                return user.email.split("@")[0]

        # handle for users not initiated
        user = pypd.User.fetch(user_id)
        self.users.append(user)
        return user.email.split("@")[0]

    def get_schedule_users(self, schedule_id: str, now: dt) -> list[pypd.User]:
        s = pypd.Schedule.fetch(id=schedule_id, since=now, until=now, time_zone="UTC")
        entries = s["final_schedule"]["rendered_schedule_entries"]

        return [
            self.get_user(entry["user"]["id"])
            for entry in entries
            if not entry["user"].get("deleted_at")
        ]

    def get_escalation_policy_users(
        self, escalation_policy_id: str, now: dt
    ) -> list[pypd.User]:
        ep = pypd.EscalationPolicy.fetch(
            id=escalation_policy_id, since=now, until=now, time_zone="UTC"
        )
        users = []
        rules = ep["escalation_rules"]
        for rule in rules:
            targets = rule["targets"]
            for target in targets:
                target_type = target["type"]
                if target_type == "schedule_reference":
                    schedule_users = self.get_schedule_users(target["id"], now)
                    users.extend(schedule_users)
                elif target_type == "user_reference":
                    users.append(self.get_user(target["id"]))
            if users and rule["escalation_delay_in_minutes"] != 0:
                # process rules until users are found
                # and next escalation is not 0 minutes from now
                break
        return users


class PagerDutyMap:
    """A collection of PagerDutyApi instances per PagerDuty instance"""

    def __init__(
        self,
        instances: list[PagerDutyConfig],
        init_users: bool = True,
        pager_duty_api_class: type[PagerDutyApi] = PagerDutyApi,
    ) -> None:
        self.pd_apis: dict[str, PagerDutyApi] = {}
        for i in instances:
            self.pd_apis[i.name] = pager_duty_api_class(i.token, init_users=init_users)

    def get(self, name: str) -> PagerDutyApi:
        """Get PagerDutyApi by instance name

        Args:
            name (string): instance name

        Returns:
            PagerDutyApi: PagerDutyApi instance
        """
        return self.pd_apis[name]


def get_pagerduty_map(
    secret_reader: SecretReader,
    pagerduty_instances: Iterable[PagerDutyInstance],
    init_users: bool = True,
    pager_duty_api_class: type[PagerDutyApi] = PagerDutyApi,
) -> PagerDutyMap:
    """Initiate a PagerDutyMap for given PagerDuty instances."""
    return PagerDutyMap(
        instances=[
            PagerDutyConfig(name=i.name, token=secret_reader.read_secret(i.token))
            for i in pagerduty_instances
        ],
        init_users=init_users,
        pager_duty_api_class=pager_duty_api_class,
    )


def get_pagerduty_name(user: PagerDutyUser) -> str:
    return user.pagerduty_username or user.org_username


@retry(no_retry_exceptions=PagerDutyTargetException)
def get_usernames_from_pagerduty(
    pagerduties: Iterable[PagerDutyTarget],
    users: Iterable[PagerDutyUser],
    usergroup: str,
    pagerduty_map: PagerDutyMap,
    get_username_method: Callable[[PagerDutyUser], str] = get_pagerduty_name,
) -> list[str]:
    """Return usernames from all given PagerDuty targets."""
    all_output_usernames = []
    all_pagerduty_names = [get_pagerduty_name(u) for u in users]
    for pagerduty in pagerduties:
        if pagerduty.schedule_id is None and pagerduty.escalation_policy_id is None:
            raise PagerDutyTargetException(
                f"pagerduty {pagerduty.name}: Either schedule_id or escalation_policy_id must be set!"
            )
        if pagerduty.schedule_id is not None:
            pd_resource_type = "schedule"
            pd_resource_id = pagerduty.schedule_id
        if pagerduty.escalation_policy_id is not None:
            pd_resource_type = "escalationPolicy"
            pd_resource_id = pagerduty.escalation_policy_id

        pd = pagerduty_map.get(pagerduty.instance.name)
        pagerduty_names = pd.get_pagerduty_users(pd_resource_type, pd_resource_id)
        if not pagerduty_names:
            continue
        pagerduty_names = [
            name.split("+", 1)[0] for name in pagerduty_names if "nobody" not in name
        ]
        if not pagerduty_names:
            continue
        all_output_usernames += [
            get_username_method(u)
            for u in users
            if get_pagerduty_name(u) in pagerduty_names
        ]
        not_found_pagerduty_names = [
            pagerduty_name
            for pagerduty_name in pagerduty_names
            if pagerduty_name not in all_pagerduty_names
        ]
        if not_found_pagerduty_names:
            msg = (
                f"[{usergroup}] PagerDuty username not found in app-interface: {not_found_pagerduty_names}"
                " (hint: user files should contain pagerduty_username if it is different than org_username)"
            )
            logging.warning(msg)

    return all_output_usernames
