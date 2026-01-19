from reconcile.gql_definitions.common.smtp_client_settings import (
    SmtpSettingsV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import (
    AppInterfaceSettingsError,
    AppInterfaceSmtpSettingsError,
)


def settings() -> SmtpSettingsV1:
    if settings_ := query(query_func=gql.get_api().query).settings:
        if not settings_[0].smtp:
            raise AppInterfaceSmtpSettingsError("settings.smtp missing")
        return settings_[0].smtp
    raise AppInterfaceSettingsError("settings missing")
