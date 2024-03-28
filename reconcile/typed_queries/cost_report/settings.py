from reconcile.gql_definitions.cost_report.settings import CostReportSettingsV1, query
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils.gql import GqlApi


def get_cost_report_settings(
    gql_api: GqlApi,
) -> CostReportSettingsV1:
    data = query(gql_api.query)
    if not data.settings:
        raise AppInterfaceSettingsError("No settings configured")
    cost_report_settings = data.settings[0].cost_report
    if cost_report_settings is None:
        raise AppInterfaceSettingsError("No cost report configured")
    return cost_report_settings
