from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from tools.cli_commands.cost_report.model import Report

LAYOUT = """\
[TOC]

{header}
{summary}
{month_over_month_change}
{cost_breakdown}\
"""

HEADER = """\
# AWS Cost Report
"""

SUMMARY = """\
## Summary

Total AWS Cost for {date}: {total_cost}

```json:table
{json_table}
```
"""

MONTH_OVER_MONTH_CHANGE = """\
## Month Over Month Change

Month over month change for {date}:

```json:table
{json_table}
```
"""

COST_BREAKDOWN = """\
## Cost Breakdown

{apps}\
"""

APP = """\
### {app_name}

{cost_details}\
"""

AWS_SERVICES_COST = """\
AWS Services Cost: {services_total}, {services_delta_value}{services_delta_percent} \
compared to previous month.
View in [Cost Management Console]({cost_management_console_url}).

```json:table
{json_table}
```
"""

COST_MANAGEMENT_CONSOLE_EXPLORE_URL = (
    "{base_url}/explorer?"
    "dateRangeType=previous_month&"
    "filter[limit]=10&"
    "filter[offset]=0&"
    "filter_by[tag:app]={app}"
    "&group_by[service]=*"
    "&order_by[cost]=desc&"
    "perspective=aws"
)

CHILD_APPS_COST = """\
Child Apps Cost: {child_apps_total}

```json:table
{json_table}
```
"""

TOTAL_COST = """\
Total Cost: {total}
"""


class TableField(BaseModel):
    key: str
    label: str
    sortable: bool


class JsonTable(BaseModel):
    filter: bool
    items: list[Any]
    fields: list[TableField]


class SummaryItem(BaseModel):
    name: str
    child_apps_total: Decimal
    services_total: Decimal
    total: Decimal


class MonthOverMonthChangeItem(BaseModel):
    name: str
    delta_value: Decimal
    delta_percent: float | None
    total: Decimal


def format_cost_value(value: Decimal) -> str:
    return f"${value:,.2f}"


def format_delta_value(value: Decimal) -> str:
    if value >= 0:
        return f"+${value:,.2f}"
    else:
        return f"-${abs(value):,.2f}"


def format_delta_percent(value: float | None) -> str:
    if value is None:
        return ""
    return f" ({value:+.2f}%)"


def get_date(reports: Mapping[str, Report]) -> str:
    return next((d for report in reports.values() if (d := report.date)), "")


def render_summary(reports: Mapping[str, Report]) -> str:
    root_apps = {
        name: report
        for name, report in reports.items()
        if report.parent_app_name is None
    }
    total_cost = round(Decimal(sum(report.total for report in root_apps.values())), 2)
    summary_items = [
        SummaryItem(
            name=name,
            child_apps_total=round(report.child_apps_total, 2),
            services_total=round(report.services_total, 2),
            total=round(report.total, 2),
        )
        for name, report in root_apps.items()
    ]
    json_table = JsonTable(
        filter=True,
        items=sorted(summary_items, key=lambda item: item.total, reverse=True),
        fields=[
            TableField(key="name", label="Name", sortable=True),
            TableField(key="services_total", label="Self App ($)", sortable=True),
            TableField(key="child_apps_total", label="Child Apps ($)", sortable=True),
            TableField(key="total", label="Total ($)", sortable=True),
        ],
    )
    return SUMMARY.format(
        date=get_date(reports),
        total_cost=format_cost_value(total_cost),
        json_table=json_table.json(indent=2),
    )


def render_month_over_month_change(reports: Mapping[str, Report]) -> str:
    items = [
        MonthOverMonthChangeItem(
            name=name,
            delta_value=round(report.services_delta_value, 2),
            delta_percent=(
                round(report.services_delta_percent, 2)
                if report.services_delta_percent is not None
                else None
            ),
            total=round(report.services_total, 2),
        )
        for name, report in reports.items()
    ]
    json_table = JsonTable(
        filter=True,
        items=sorted(items, key=lambda item: item.delta_value, reverse=True),
        fields=[
            TableField(key="name", label="Name", sortable=True),
            TableField(key="delta_value", label="Change ($)", sortable=True),
            TableField(key="delta_percent", label="Change (%)", sortable=True),
            TableField(key="total", label="Total ($)", sortable=True),
        ],
    )
    return MONTH_OVER_MONTH_CHANGE.format(
        date=get_date(reports),
        json_table=json_table.json(indent=2),
    )


def build_cost_management_console_url(base_url: str, app: str) -> str:
    return (
        f"{base_url}/explorer?"
        "dateRangeType=previous_month&"
        "filter[limit]=10&"
        "filter[offset]=0&"
        f"filter_by[tag:app]={app}&"
        "group_by[service]=*&"
        "order_by[cost]=desc&"
        "perspective=aws"
    )


def render_aws_services_cost(
    report: Report,
    cost_management_console_base_url: str,
) -> str:
    services = [
        s.copy(
            update={
                "delta_value": round(s.delta_value, 2),
                "delta_percent": round(s.delta_percent, 2)
                if s.delta_percent is not None
                else None,
                "total": round(s.total, 2),
            }
        )
        for s in report.services
    ]
    json_table = JsonTable(
        filter=True,
        items=sorted(services, key=lambda service: service.total, reverse=True),
        fields=[
            TableField(key="service", label="Service", sortable=True),
            TableField(key="delta_value", label="Change ($)", sortable=True),
            TableField(key="delta_percent", label="Change (%)", sortable=True),
            TableField(key="total", label="Total ($)", sortable=True),
        ],
    )
    return AWS_SERVICES_COST.format(
        cost_management_console_url=build_cost_management_console_url(
            cost_management_console_base_url,
            report.app_name,
        ),
        services_total=format_cost_value(report.services_total),
        services_delta_value=format_delta_value(report.services_delta_value),
        services_delta_percent=format_delta_percent(report.services_delta_percent),
        json_table=json_table.json(indent=2),
    )


def render_child_apps_cost(report: Report) -> str:
    child_apps = [
        app.copy(
            update={
                "total": round(app.total, 2),
            }
        )
        for app in report.child_apps
    ]
    json_table = JsonTable(
        filter=True,
        items=sorted(child_apps, key=lambda app: app.total, reverse=True),
        fields=[
            TableField(key="name", label="Name", sortable=True),
            TableField(key="total", label="Total ($)", sortable=True),
        ],
    )
    return CHILD_APPS_COST.format(
        child_apps_total=format_cost_value(report.child_apps_total),
        json_table=json_table.json(indent=2),
    )


def render_total_cost(report: Report) -> str:
    return TOTAL_COST.format(
        total=format_cost_value(report.total),
    )


def render_app_cost(
    name: str,
    report: Report,
    cost_management_console_base_url: str,
) -> str:
    cost_details_sections = []
    if report.services:
        cost_details_sections.append(
            render_aws_services_cost(
                report,
                cost_management_console_base_url,
            )
        )
    if report.child_apps:
        cost_details_sections.append(render_child_apps_cost(report))
        cost_details_sections.append(render_total_cost(report))
    cost_details = (
        "\n".join(cost_details_sections) if cost_details_sections else "No data"
    )
    return APP.format(
        app_name=name,
        cost_details=cost_details,
    )


def render_cost_breakdown(
    reports: Mapping[str, Report],
    cost_management_console_base_url: str,
) -> str:
    apps = "\n".join(
        render_app_cost(
            name,
            report,
            cost_management_console_base_url,
        )
        for name, report in sorted(
            reports.items(),
            key=lambda item: item[0].lower(),
        )
    )
    return COST_BREAKDOWN.format(apps=apps)


def render_report(
    reports: Mapping[str, Report],
    cost_management_console_base_url: str,
) -> str:
    return LAYOUT.format(
        header=HEADER,
        summary=render_summary(reports),
        month_over_month_change=render_month_over_month_change(reports),
        cost_breakdown=render_cost_breakdown(
            reports,
            cost_management_console_base_url,
        ),
    )
