from pydantic import BaseModel

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.glitchtip.glitchtip_settings import query
from reconcile.utils import gql


class GlitchtipSettings(BaseModel):
    read_timeout: int = 30
    max_retries: int = 3
    mail_domain: str = "redhat.com"
    glitchtip_jira_bridge_alert_url: str = "https://gjb.devshift.net/api/v1/alert"
    glitchtip_jira_bridge_token: VaultSecret | None


def get_glitchtip_settings() -> GlitchtipSettings:
    """Returns Glitchtip Settings."""
    gqlapi = gql.get_api()
    settings = query(query_func=gqlapi.query).settings
    ai_gs = settings[0].glitchtip if settings else None
    gs = GlitchtipSettings()
    if ai_gs:
        if ai_gs.read_timeout:
            gs.read_timeout = ai_gs.read_timeout
        if ai_gs.max_retries:
            gs.max_retries = ai_gs.max_retries
        if ai_gs.mail_domain:
            gs.mail_domain = ai_gs.mail_domain
        if ai_gs.glitchtip_jira_bridge_alert_url:
            gs.glitchtip_jira_bridge_alert_url = ai_gs.glitchtip_jira_bridge_alert_url
        if ai_gs.glitchtip_jira_bridge_token:
            gs.glitchtip_jira_bridge_token = ai_gs.glitchtip_jira_bridge_token
    return gs
