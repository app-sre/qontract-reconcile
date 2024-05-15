from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from typing import Any

from reconcile.typed_queries.cost_report.app_names import App
from tools.cli_commands.cost_report.model import Report


def dfs_build_reports(
    app_name: str,
    parent_app_name: str | None,
    child_apps_by_parent: Mapping[str | None, list[str]],
    responses: Mapping[str, Any],
    reports: MutableMapping[str, Report],
    report_builder: Callable[..., Report],
) -> None:
    """
    Depth-first search to build the reports. Build leaf nodes first to ensure total is calculated correctly.
    """
    child_apps = child_apps_by_parent.get(app_name, [])
    for child_app in child_apps:
        dfs_build_reports(
            app_name=child_app,
            parent_app_name=app_name,
            child_apps_by_parent=child_apps_by_parent,
            responses=responses,
            reports=reports,
            report_builder=report_builder,
        )
    reports[app_name] = report_builder(
        app_name=app_name,
        parent_app_name=parent_app_name,
        child_apps=child_apps,
        reports=reports,
        response=responses[app_name],
    )


def process_reports(
    apps: Iterable[App],
    responses: Mapping[str, Any],
    report_builder: Callable[..., Report],
) -> dict[str, Report]:
    child_apps_by_parent = defaultdict(list)
    for app in apps:
        child_apps_by_parent[app.parent_app_name].append(app.name)

    reports: dict[str, Report] = {}
    root_apps = child_apps_by_parent.get(None, [])
    for app_name in root_apps:
        dfs_build_reports(
            app_name,
            None,
            child_apps_by_parent=child_apps_by_parent,
            responses=responses,
            reports=reports,
            report_builder=report_builder,
        )
    return reports
