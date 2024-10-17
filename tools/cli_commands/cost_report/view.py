from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from tools.cli_commands.cost_report.model import OptimizationReport, Report

LAYOUT = """\
[TOC]

{header}
{summary}
{month_over_month_change}
{cost_breakdown}\
"""

OPTIMIZATION_LAYOUT = """\
[TOC]

{header}
{optimizations}\
"""

AWS_HEADER = """\
# AWS Cost Report
"""

OPENSHIFT_HEADER = """\
# OpenShift Cost Report
"""

OPTIMIZATION_HEADER = """\
# OpenShift Cost Optimization Report

Report is generated for optimization enabled namespaces
(`insights_cost_management_optimizations='true'` in namespace `labels`).

In Cost optimizations, recommendations get generated when
CPU usage is at or above the 60th percentile and
memory usage is at the 100th percentile.

View details in [Cost Management Optimizations](https://console.redhat.com/openshift/cost-management/optimizations).
"""

AWS_SUMMARY = """\
## Summary

Total AWS Cost for {date}: {total_cost}

```json:table
{json_table}
```
"""

OPENSHIFT_SUMMARY = """\
## Summary

Total OpenShift Cost for {date}: {total_cost}

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
AWS Services Cost: {items_total}, {items_delta_value}{items_delta_percent} \
compared to previous month.
View in [Cost Management Console]({cost_management_console_url}).

```json:table
{json_table}
```
"""

OPENSHIFT_WORKLOADS_COST = """\
OpenShift Workloads Cost: {items_total}, {items_delta_value}{items_delta_percent} \
compared to previous month.

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

OPTIMIZATION = """\
## {app_name}

```json:table
{json_table}
```
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
    items_total: Decimal
    total: Decimal


class MonthOverMonthChangeItem(BaseModel):
    name: str
    delta_value: Decimal
    delta_percent: float | None
    total: Decimal


class ViewReportItem(BaseModel):
    name: str
    delta_value: Decimal
    delta_percent: float | None
    total: Decimal


class ViewChildAppReport(BaseModel):
    name: str
    total: Decimal


class ViewOptimizationReportItem(BaseModel):
    namespace: str
    workload: str
    current_cpu_limit: str | None
    current_cpu_request: str | None
    current_memory_limit: str | None
    current_memory_request: str | None
    recommend_cpu_limit: str | None
    recommend_cpu_request: str | None
    recommend_memory_limit: str | None
    recommend_memory_request: str | None


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


def render_summary(
    template: str,
    reports: Mapping[str, Report],
) -> str:
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
            items_total=round(report.items_total, 2),
            total=round(report.total, 2),
        )
        for name, report in root_apps.items()
    ]
    json_table = JsonTable(
        filter=True,
        items=sorted(summary_items, key=lambda item: item.total, reverse=True),
        fields=[
            TableField(key="name", label="Name", sortable=True),
            TableField(key="items_total", label="Self App ($)", sortable=True),
            TableField(key="child_apps_total", label="Child Apps ($)", sortable=True),
            TableField(key="total", label="Total ($)", sortable=True),
        ],
    )
    return template.format(
        date=get_date(reports),
        total_cost=format_cost_value(total_cost),
        json_table=json_table.json(indent=2),
    )


def render_month_over_month_change(reports: Mapping[str, Report]) -> str:
    items = [
        MonthOverMonthChangeItem(
            name=name,
            delta_value=round(report.items_delta_value, 2),
            delta_percent=(
                round(report.items_delta_percent, 2)
                if report.items_delta_percent is not None
                else None
            ),
            total=round(report.items_total, 2),
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
    json_table = _build_items_cost_json_table(report, name_label="Service")
    return AWS_SERVICES_COST.format(
        cost_management_console_url=build_cost_management_console_url(
            cost_management_console_base_url,
            report.app_name,
        ),
        items_total=format_cost_value(report.items_total),
        items_delta_value=format_delta_value(report.items_delta_value),
        items_delta_percent=format_delta_percent(report.items_delta_percent),
        json_table=json_table.json(indent=2),
    )


def render_openshift_workloads_cost(
    report: Report,
) -> str:
    json_table = _build_items_cost_json_table(report, name_label="Cluster/Namespace")
    return OPENSHIFT_WORKLOADS_COST.format(
        items_total=format_cost_value(report.items_total),
        items_delta_value=format_delta_value(report.items_delta_value),
        items_delta_percent=format_delta_percent(report.items_delta_percent),
        json_table=json_table.json(indent=2),
    )


def _build_items_cost_json_table(report: Report, name_label: str) -> JsonTable:
    items = [
        ViewReportItem(
            name=s.name,
            delta_value=round(s.delta_value, 2),
            delta_percent=round(s.delta_percent, 2)
            if s.delta_percent is not None
            else None,
            total=round(s.total, 2),
        )
        for s in report.items
    ]
    return JsonTable(
        filter=True,
        items=sorted(items, key=lambda item: item.total, reverse=True),
        fields=[
            TableField(key="name", label=name_label, sortable=True),
            TableField(key="delta_value", label="Change ($)", sortable=True),
            TableField(key="delta_percent", label="Change (%)", sortable=True),
            TableField(key="total", label="Total ($)", sortable=True),
        ],
    )


def render_child_apps_cost(report: Report) -> str:
    child_apps = [
        ViewChildAppReport(
            name=app.name,
            total=round(app.total, 2),
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
    item_cost_renderer: Callable[..., str],
    **kwargs: Any,
) -> str:
    cost_details_sections = []
    if report.items:
        cost_details_sections.append(item_cost_renderer(report=report, **kwargs))
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
    item_cost_renderer: Callable[..., str],
    **kwargs: Any,
) -> str:
    apps = "\n".join(
        render_app_cost(
            name=name,
            report=report,
            item_cost_renderer=item_cost_renderer,
            **kwargs,
        )
        for name, report in sorted(
            reports.items(),
            key=lambda item: item[0].lower(),
        )
    )
    return COST_BREAKDOWN.format(apps=apps)


def render_aws_cost_report(
    reports: Mapping[str, Report],
    cost_management_console_base_url: str,
) -> str:
    return LAYOUT.format(
        header=AWS_HEADER,
        summary=render_summary(AWS_SUMMARY, reports),
        month_over_month_change=render_month_over_month_change(reports),
        cost_breakdown=render_cost_breakdown(
            reports,
            item_cost_renderer=render_aws_services_cost,
            cost_management_console_base_url=cost_management_console_base_url,
        ),
    )


def render_openshift_cost_report(
    reports: Mapping[str, Report],
) -> str:
    return LAYOUT.format(
        header=OPENSHIFT_HEADER,
        summary=render_summary(OPENSHIFT_SUMMARY, reports),
        month_over_month_change=render_month_over_month_change(reports),
        cost_breakdown=render_cost_breakdown(
            reports,
            item_cost_renderer=render_openshift_workloads_cost,
        ),
    )


def render_optimization(
    report: OptimizationReport,
) -> str:
    items = [
        ViewOptimizationReportItem(
            namespace=f"{i.cluster}/{i.project}",
            workload=f"{i.workload_type}/{i.workload}/{i.container}",
            current_cpu_limit=i.current_cpu_limit,
            current_cpu_request=i.current_cpu_request,
            current_memory_limit=i.current_memory_limit,
            current_memory_request=i.current_memory_request,
            recommend_cpu_limit=i.recommend_cpu_limit,
            recommend_cpu_request=i.recommend_cpu_request,
            recommend_memory_limit=i.recommend_memory_limit,
            recommend_memory_request=i.recommend_memory_request,
        )
        for i in report.items
    ]
    json_table = JsonTable(
        filter=True,
        items=sorted(items, key=lambda item: (item.namespace, item.workload)),
        fields=[
            TableField(key="namespace", label="Namespace", sortable=True),
            TableField(key="workload", label="Workload", sortable=True),
            TableField(
                key="current_cpu_request", label="Current CPU Request", sortable=True
            ),
            TableField(
                key="recommend_cpu_request",
                label="Recommend CPU Request",
                sortable=True,
            ),
            TableField(
                key="current_cpu_limit", label="Current CPU Limit", sortable=True
            ),
            TableField(
                key="recommend_cpu_limit", label="Recommend CPU Limit", sortable=True
            ),
            TableField(
                key="current_memory_request",
                label="Current Memory Request",
                sortable=True,
            ),
            TableField(
                key="recommend_memory_request",
                label="Recommend Memory Request",
                sortable=True,
            ),
            TableField(
                key="current_memory_limit", label="Current Memory Limit", sortable=True
            ),
            TableField(
                key="recommend_memory_limit",
                label="Recommend Memory Limit",
                sortable=True,
            ),
        ],
    )
    return OPTIMIZATION.format(
        app_name=report.app_name,
        json_table=json_table.json(indent=2),
    )


def render_optimizations(
    reports: Iterable[OptimizationReport],
) -> str:
    return "\n".join(
        render_optimization(report=report)
        for report in sorted(
            reports,
            key=lambda item: item.app_name.lower(),
        )
    )


def render_openshift_cost_optimization_report(
    reports: Iterable[OptimizationReport],
) -> str:
    return OPTIMIZATION_LAYOUT.format(
        header=OPTIMIZATION_HEADER,
        optimizations=render_optimizations(reports),
    )
