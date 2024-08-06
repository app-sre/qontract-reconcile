import re
import string

from pydantic import BaseModel
from ruamel.yaml.compat import StringIO

from reconcile.utils.merge_request_manager.parser import Parser
from reconcile.utils.ruamel import create_ruamel_instance

VERSION = "1.0.0"
INTEGRATION = "endpoints-discovery"
LABEL = "ENDPOINTS-DISCOVERY"

INTEGRATION_REF = "integration"
VERSION_REF = "endpoints-discover-version"
HASH_REF = "hash"
COMPILED_REGEXES = {
    i: re.compile(rf".*{i}: (.*)$", re.MULTILINE)
    for i in [INTEGRATION_REF, VERSION_REF, HASH_REF]
}

PROMOTION_DATA_SEPARATOR = "**DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
DESC = string.Template(
    f"""
This MR is triggered by app-interface's [endpoints-discovery](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/endpoints_discovery).

Please **do not remove the `{LABEL}` label** from this MR!

Parts of this description are used to manage the MR.

{PROMOTION_DATA_SEPARATOR}

* {INTEGRATION_REF}: {INTEGRATION}
* {VERSION_REF}: {VERSION}
* {HASH_REF}: $hash
"""
)


class EPDInfo(BaseModel):
    integration: str = INTEGRATION
    hash: str


def create_parser() -> Parser:
    return Parser[EPDInfo](
        klass=EPDInfo,
        compiled_regexes=COMPILED_REGEXES,
        version_ref=VERSION_REF,
        expected_version=VERSION,
        data_separator=PROMOTION_DATA_SEPARATOR,
    )


class Renderer:
    """
    This class is only concerned with rendering text for MRs.
    Most logic evolves around ruamel yaml modification.
    This class makes testing for MergeRequestManager easier.

    Note, that this class is very susceptible to schema changes
    as it mainly works on raw dicts.
    """

    def render_merge_request_content(
        self,
        current_content: str,
        endpoints_to_add: list[dict],
        endpoints_to_change: dict[str, dict],
        endpoints_to_delete: list[str],
    ) -> str:
        """Update the app-interface app file for a merge request."""
        yml = create_ruamel_instance(explicit_start=True)
        content = yml.load(current_content)
        new_endpoints = []
        for app_endpoint in content.setdefault("endPoints", []):
            if app_endpoint["name"] in endpoints_to_delete:
                continue
            elif app_endpoint["name"] in endpoints_to_change:
                new_endpoints.append(endpoints_to_change[app_endpoint["name"]])
            else:
                new_endpoints.append(app_endpoint)

        new_endpoints.extend(endpoints_to_add)
        content["endPoints"] = new_endpoints
        with StringIO() as stream:
            yml.dump(content, stream)
            return stream.getvalue()

    def render_description(self, hash: str) -> str:
        """Render the description for a merge request."""
        return DESC.safe_substitute(EPDInfo(hash=hash).dict())

    def render_title(self) -> str:
        """Render the title for a merge request."""
        return f"[auto] {INTEGRATION}: update application endpoints"
