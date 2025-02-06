import logging
from abc import abstractmethod
from collections.abc import Sequence
from datetime import UTC, date
from datetime import datetime as dt
from pathlib import Path
from typing import TypeVar

from jinja2 import Template
from pydantic import BaseModel

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE

AccessReportUser = TypeVar("AccessReportUser", bound=BaseModel)


class UpdateAccessReportBase(MergeRequestBase):
    def __init__(
        self,
        users: Sequence[AccessReportUser],
        workbook_path: Path,
        dry_run: bool = True,
    ):
        super().__init__()
        self.labels = [AUTO_MERGE]
        self._users = users
        self._workbook_file_name = str(workbook_path)
        self._isodate = dt.now(tz=UTC).isoformat()
        self._dry_run = dry_run

    @property
    @abstractmethod
    def short_description(self) -> str:
        """
        Short Description of the Merge Request (without dates). It will be used to
        build the Merge Request description as seen in the UI.

        :return: Merge Request description as seen in the Gitlab Web UI without date.
        :rtype: str
        """

    @property
    @abstractmethod
    def template(self) -> str:
        """
        Jinja2 template to generate the report main table.

        :return: report jinja2 template.
        :rtype: str
        """

    @property
    def title(self) -> str:
        return f"[{self.name}] reports for {self._isodate}"

    @property
    def description(self) -> str:
        return f"{self.short_description} for {self._isodate}"

    def _render_current_users_table(self) -> str:
        template = Template(self.template, keep_trailing_newline=True)
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
        workbook_file = gitlab_cli.project.files.get(
            file_path=self._workbook_file_name, ref=self.branch
        )
        workbook_md = self._update_workbook(workbook_file.decode().decode("utf-8"))

        if not self._dry_run:
            logging.info(
                f"updating {self.short_description}: {self._workbook_file_name}"
            )
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=self._workbook_file_name,
                commit_message=f"update {self.short_description}",
                content=workbook_md,
            )
        else:
            logging.info(
                f"dry-run: not updating {self.short_description}: {self._workbook_file_name}"
            )
            logging.info(workbook_md)
