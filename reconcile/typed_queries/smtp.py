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
    if _settings := query(query_func=gql.get_api().query).settings:
        if not _settings[0].smtp:
            raise AppInterfaceSmtpSettingsError("settings.smtp missing")
        return _settings[0].smtp
    raise AppInterfaceSettingsError("settings missing")
