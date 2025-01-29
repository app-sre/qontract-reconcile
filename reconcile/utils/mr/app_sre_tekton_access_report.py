from pydantic import BaseModel

from reconcile.utils.mr.update_access_report_base import UpdateAccessReportBase


class UpdateAppSRETektonAccessReport(UpdateAccessReportBase):
    name = "app_sre_tekton_access_report_mr"
    short_description = "AppSRE Tekton Access Report"
    template = """
| Username | Name | Apps with pipeline namespace access |
| -------- | ---- | ----------------------------------- |
{% for user in users|sort -%}
| {{ user.org_username }} | {{ user.name }} |{% for app in user.apps|sort %} {{app}}{% if not loop.last%},{% endif %}{% endfor %} |
{% endfor %}
""".strip()


# User model
class AppSRETektonAccessReportUserModel(BaseModel):
    org_username: str
    name: str
    apps: set[str]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, AppSRETektonAccessReportUserModel):
            raise NotImplementedError(
                "Cannot compare to non AppSRETektonAccessReportUser objects."
            )
        return self.org_username < other.org_username


# Mutable User class
class AppSRETektonAccessReportUser:
    def __init__(self, name: str, org_username: str, apps: set):
        self._org_username = org_username
        self._name = name
        self._apps = apps

    def add_app(self, app: str) -> None:
        self._apps.add(app)

    def generate_model(self) -> AppSRETektonAccessReportUserModel:
        return AppSRETektonAccessReportUserModel(
            name=self._name, org_username=self._org_username, apps=self._apps
        )
