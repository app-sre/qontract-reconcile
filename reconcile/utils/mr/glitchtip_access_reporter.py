import logging
from collections.abc import Sequence
from datetime import UTC, date
from datetime import datetime as dt
from pathlib import Path

from jinja2 import Template
from pydantic import BaseModel

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE

CURRENT_USERS_TABLE_TEMPLATE = """
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


class UpdateGlitchtipAccessReport(MergeRequestBase):
    name = "glitchtip_access_report_mr"

    def __init__(
        self,
        users: Sequence[GlitchtipAccessReportUser],
        glitchtip_access_revalidation_workbook: Path,
        dry_run: bool = True,
    ):
        super().__init__()
        self.labels = [AUTO_MERGE]
        self._users = users
        self._glitchtip_access_revalidation_workbook = str(
            glitchtip_access_revalidation_workbook
        )
        self._isodate = dt.now(tz=UTC).isoformat()
        self._dry_run = dry_run

    @property
    def title(self) -> str:
        return f"[{self.name}] reports for {self._isodate}"

    @property
    def description(self) -> str:
        return f"glitchtip access report for {self._isodate}"

    def _render_current_users_table(self) -> str:
        template = Template(CURRENT_USERS_TABLE_TEMPLATE, keep_trailing_newline=True)
        return template.render(users=self._users)

    def _render_tracking_table_row(self, old_number_of_users: int) -> str:
        # | Date Reviewed | Number of Current Users | +/- Red Hat Users |
        return f"| {date.today()} | {len(self._users)} | {len(self._users) - old_number_of_users} |\n"

    def _update_workbook(self, workbook_md: str) -> str:
        new_workbook_md = ""
        number_of_skipped_lines = 0
        skip = False
        for line in workbook_md.splitlines():
            if "<!-- current users table: start -->" in line:
                # do not copy the old current users table
                skip = True
                # insert the new table including the marker
                new_workbook_md += line + "\n"
                new_workbook_md += self._render_current_users_table()
            elif "<!-- current users table: end -->" in line:
                skip = False
                # insert the marker
                new_workbook_md += line + "\n"
            elif "<!-- tracking table: next row -->" in line:
                # insert the new row including the marker
                new_workbook_md += self._render_tracking_table_row(
                    old_number_of_users=number_of_skipped_lines - 2
                    if number_of_skipped_lines > 0
                    else 0
                )
                new_workbook_md += line + "\n"
            elif not skip:
                new_workbook_md += line + "\n"
            else:
                # count the number of skipped current users table lines
                # this number minus the table header is the old number of users
                number_of_skipped_lines += 1

        return new_workbook_md

    def process(self, gitlab_cli: GitLabApi) -> None:
        workbook_md = gitlab_cli.project.files.get(
            file_path=self._glitchtip_access_revalidation_workbook, ref=self.branch
        )
        workbook_md = self._update_workbook(workbook_md.decode().decode("utf-8"))

        if not self._dry_run:
            logging.info(
                f"updating glitchtip access report: {self._glitchtip_access_revalidation_workbook}"
            )
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=self._glitchtip_access_revalidation_workbook,
                commit_message="update glitchtip access report",
                content=workbook_md,
            )
        else:
            logging.info(
                f"dry-run: not updating glitchtip access report: {self._glitchtip_access_revalidation_workbook}"
            )
            logging.info(workbook_md)
