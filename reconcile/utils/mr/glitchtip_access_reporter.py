from pydantic import BaseModel

from reconcile.utils.mr.update_access_report_base import UpdateAccessReportBase


class UpdateGlitchtipAccessReport(UpdateAccessReportBase):
    name = "glitchtip_access_report_mr"
    short_description = "glitchtip access report"
    template = """
| Username | Name | Organizations and Access Levels |
| -------- | ---- | ------------------------------- |
{% for user in users|sort -%}
| {{ user.username }} | {{ user.name }} |{% for org in user.organizations %} {{org.name}} ({{ org.access_level }}){% if not loop.last%},{% endif %}{% endfor %} |
{% endfor %}
""".strip()


class GlitchtipAccessReportOrg(BaseModel):
    name: str
    access_level: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GlitchtipAccessReportOrg):
            raise NotImplementedError(
                "Cannot compare to non GlitchtipAccessReportOrg objects."
            )
        return self.name == other.name


class GlitchtipAccessReportUser(BaseModel):
    name: str
    username: str
    organizations: list[GlitchtipAccessReportOrg]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, GlitchtipAccessReportUser):
            raise NotImplementedError(
                "Cannot compare to non GlitchtipAccessReportUser objects."
            )
        return self.username < other.username
