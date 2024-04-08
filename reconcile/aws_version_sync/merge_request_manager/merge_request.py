import re
import string

from pydantic import BaseModel
from ruamel.yaml.compat import StringIO

from reconcile.utils.merge_request_manager.parser import Parser
from reconcile.utils.ruamel import create_ruamel_instance

PROMOTION_DATA_SEPARATOR = (
    "**AVS DATA - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
)
AVS_VERSION = "1.0.0"
AVS_LABEL = "AVS"

VERSION_REF = "avs_version"
PROVIDER_REF = "provider"
ACCOUNT_ID_REF = "account_id"
RESOURCE_PROVIDER_REF = "resource_provider"
RESOURCE_IDENTIFIER_REF = "resource_identifier"
RESOURCE_ENGINE_REF = "resource_engine"
RESOURCE_ENGINE_VERSION_REF = "resource_engine_version"

COMPILED_REGEXES = {
    i: re.compile(rf".*{i}: (.*)$", re.MULTILINE)
    for i in [
        VERSION_REF,
        PROVIDER_REF,
        ACCOUNT_ID_REF,
        RESOURCE_PROVIDER_REF,
        RESOURCE_IDENTIFIER_REF,
        RESOURCE_ENGINE_REF,
        RESOURCE_ENGINE_VERSION_REF,
    ]
}

AVS_DESC = string.Template(
    f"""
This MR is triggered by app-interface's [aws-version-sync (AVS)](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/aws_version_sync).

Please **do not remove the {AVS_LABEL} label** from this MR!

Parts of this description are used by AVS to manage the MR.

{PROMOTION_DATA_SEPARATOR}

* {VERSION_REF}: {AVS_VERSION}
* {PROVIDER_REF}: $provider
* {ACCOUNT_ID_REF}: $account_id
* {RESOURCE_PROVIDER_REF}: $resource_provider
* {RESOURCE_IDENTIFIER_REF}: $resource_identifier
* {RESOURCE_ENGINE_REF}: $resource_engine
* {RESOURCE_ENGINE_VERSION_REF}: $resource_engine_version
"""
)


class AVSInfo(BaseModel):
    provider: str
    account_id: str
    resource_provider: str
    resource_identifier: str
    resource_engine: str
    resource_engine_version: str


def create_parser() -> Parser:
    return Parser[AVSInfo](
        klass=AVSInfo,
        compiled_regexes=COMPILED_REGEXES,
        version_ref=VERSION_REF,
        expected_version=AVS_VERSION,
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

    def _find_resource(
        self,
        content: dict,
        provider: str,
        provisioner_ref: str,
        resource_provider: str,
        resource_identifier: str,
    ) -> dict:
        for external_resource in content["externalResources"]:
            if (
                external_resource["provider"] == provider
                and external_resource["provisioner"]["$ref"] == provisioner_ref
            ):
                for resource in external_resource["resources"]:
                    if (
                        resource["provider"] == resource_provider
                        and resource["identifier"] == resource_identifier
                    ):
                        return resource
        # this should not happen
        raise RuntimeError(
            f"Could not find resource with provider {provider} and identifier {resource_identifier}"
        )

    def render_merge_request_content(
        self,
        current_content: str,
        provider: str,
        provisioner_ref: str,
        resource_provider: str,
        resource_identifier: str,
        resource_engine_version: str,
    ) -> str:
        """Render the content of an MR for AVS based on the current content of a namespace file."""
        yml = create_ruamel_instance(explicit_start=True)
        content = yml.load(current_content)
        resource = self._find_resource(
            content,
            provider,
            provisioner_ref,
            resource_provider,
            resource_identifier,
        )
        overrides = resource.setdefault("overrides", {})
        # ensure that the engine version is always a string
        overrides["engine_version"] = f"{resource_engine_version}"
        with StringIO() as stream:
            yml.dump(content, stream)
            return stream.getvalue()

    def render_description(
        self,
        provider: str,
        account_id: str,
        resource_provider: str,
        resource_identifier: str,
        resource_engine: str,
        resource_engine_version: str,
    ) -> str:
        return AVS_DESC.safe_substitute(
            provider=provider,
            account_id=account_id,
            resource_provider=resource_provider,
            resource_identifier=resource_identifier,
            resource_engine=resource_engine,
            resource_engine_version=resource_engine_version,
        )

    def render_title(self, resource_identifier: str) -> str:
        return f"[auto] update AWS resource version for {resource_identifier}"
