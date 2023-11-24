from textwrap import dedent

import pytest

from reconcile.aws_version_sync.merge_request_manager.merge_request import (
    ACCOUNT_ID_REF,
    AVS_VERSION,
    PROMOTION_DATA_SEPARATOR,
    PROVIDER_REF,
    RESOURCE_ENGINE_REF,
    RESOURCE_ENGINE_VERSION_REF,
    RESOURCE_IDENTIFIER_REF,
    RESOURCE_PROVIDER_REF,
    VERSION_REF,
    AVSInfo,
    Parser,
    ParserError,
    ParserVersionError,
    Renderer,
)


@pytest.mark.parametrize(
    "description,expected",
    [
        pytest.param(
            "",
            None,
            marks=pytest.mark.xfail(strict=True, raises=ParserError),
            id="empty",
        ),
        pytest.param(
            f"foobar\n{PROMOTION_DATA_SEPARATOR}",
            None,
            marks=pytest.mark.xfail(strict=True, raises=ParserError),
            id="no version",
        ),
        pytest.param(
            f"foobar\n{PROMOTION_DATA_SEPARATOR}\n* {VERSION_REF}: 0.0.0.0.0.1",
            None,
            marks=pytest.mark.xfail(strict=True, raises=ParserVersionError),
            id="outdated",
        ),
        pytest.param(
            f"""dadfbar
            {PROMOTION_DATA_SEPARATOR}
            * {VERSION_REF}: {AVS_VERSION}
            """,
            None,
            marks=pytest.mark.xfail(strict=True, raises=ParserError),
            id="no data",
        ),
        pytest.param(
            f"""dadfbar
            {PROMOTION_DATA_SEPARATOR}
            * {VERSION_REF}: {AVS_VERSION}
            * {PROVIDER_REF}: provider
            * {ACCOUNT_ID_REF}: 32168
            * {RESOURCE_PROVIDER_REF}: resource_provider
            * {RESOURCE_IDENTIFIER_REF}: resource_identifier
            * {RESOURCE_ENGINE_REF}: resource_engine
            * {RESOURCE_ENGINE_VERSION_REF}: resource_engine_version
            """,
            AVSInfo(
                provider="provider",
                account_id="32168",
                resource_provider="resource_provider",
                resource_identifier="resource_identifier",
                resource_engine="resource_engine",
                resource_engine_version="resource_engine_version",
            ),
            id="all fine",
        ),
        pytest.param(
            f"""lorem ipsum dolor sit amet

               consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua
            more lorem ipsum dolor sit amet consectetur

            adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua
            more lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua

            {PROMOTION_DATA_SEPARATOR}

     {VERSION_REF}: {AVS_VERSION}
                    * {RESOURCE_IDENTIFIER_REF}: resource_identifier
            * {PROVIDER_REF}: provider
            * {ACCOUNT_ID_REF}: 32168
     {RESOURCE_ENGINE_VERSION_REF}: resource_engine_version
            * {RESOURCE_PROVIDER_REF}: resource_provider
                    {RESOURCE_ENGINE_REF}: resource_engine
            """,
            AVSInfo(
                provider="provider",
                account_id="32168",
                resource_provider="resource_provider",
                resource_identifier="resource_identifier",
                resource_engine="resource_engine",
                resource_engine_version="resource_engine_version",
            ),
            id="more description, other ordering, indentation, and formatting",
        ),
    ],
)
def test_parser_parse(description: str, expected: AVSInfo) -> None:
    parser = Parser()
    assert parser.parse(description) == expected


def test_renderer_render_description() -> None:
    renderer = Renderer()
    assert (
        renderer.render_description(
            provider="provider",
            account_id="32168",
            resource_provider="resource_provider_test",
            resource_identifier="resource_identifier_test",
            resource_engine="resource_engine_test",
            resource_engine_version="resource_engine_version_test",
        )
        == """
This MR is triggered by app-interface's [aws-version-sync (AVS)](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/aws_version_sync).

Please **do not remove the AVS label** from this MR!

Parts of this description are used by AVS to manage the MR.

**AVS DATA - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**

* avs_version: 1.0.0
* provider: provider
* account_id: 32168
* resource_provider: resource_provider_test
* resource_identifier: resource_identifier_test
* resource_engine: resource_engine_test
* resource_engine_version: resource_engine_version_test
"""
    )


def test_renderer_render_title() -> None:
    renderer = Renderer()
    assert (
        renderer.render_title(
            resource_identifier="resource_identifier_test",
        )
        == "[auto] update AWS resource version for resource_identifier_test"
    )


@pytest.mark.parametrize(
    "current_content, provider, provisioner_ref, resource_provider, resource_identifier, resource_engine_version,expected",
    [
        pytest.param(
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                """
            ),
            "aws",
            "account-1",
            "rds",
            "rds-1",
            "15.1",
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                    overrides:
                      engine_version: '15.1'
                """
            ),
            id="just-rds-1",
        ),
        pytest.param(
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                    overrides:
                      engine_version: '15.0'
                      apply_immediately: true
                """
            ),
            "aws",
            "account-1",
            "rds",
            "rds-1",
            "15.1",
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                    overrides:
                      engine_version: '15.1'
                      apply_immediately: true
                """
            ),
            id="rds-1-with-overrides",
        ),
        pytest.param(
            dedent(
                """
                ---

                # this is a test
                foobar: 1

                whatever: 2 # test test test

                # just onother comment


                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  # and here comes the RDS
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                """
            ),
            "aws",
            "account-1",
            "rds",
            "rds-1",
            "15.1",
            dedent(
                """
                ---

                # this is a test
                foobar: 1

                whatever: 2 # test test test

                # just onother comment


                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  # and here comes the RDS
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                    overrides:
                      engine_version: '15.1'
                """
            ),
            id="just-rds-1-with-comments-and-empty-lines",
        ),
        pytest.param(
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                  - provider: rds
                    identifier: rds-2
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-2
                """
            ),
            "aws",
            "account-1",
            "rds",
            "rds-1",
            "15.1",
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                    overrides:
                      engine_version: '15.1'
                  - provider: rds
                    identifier: rds-2
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-2
                """
            ),
            id="multiple-rds-defined",
        ),
        pytest.param(
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                  - provider: rds
                    identifier: rds-2
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-2
                - provider: aws
                  provisioner:
                    $ref: account-2
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                  - provider: rds
                    identifier: rds-2
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-2
                """
            ),
            "aws",
            "account-2",
            "rds",
            "rds-1",
            "15.1",
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                  - provider: rds
                    identifier: rds-2
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-2
                - provider: aws
                  provisioner:
                    $ref: account-2
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                    overrides:
                      engine_version: '15.1'
                  - provider: rds
                    identifier: rds-2
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-2
                """
            ),
            id="multiple-rds-and-provisioner-defined",
        ),
        pytest.param(
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                  - provider: elasticache
                    identifier: elasticache-stage-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: elasticache-stage-1
                """
            ),
            "aws",
            "account-1",
            "elasticache",
            "elasticache-stage-1",
            "6.1",
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                  - provider: elasticache
                    identifier: elasticache-stage-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: elasticache-stage-1
                    overrides:
                      engine_version: '6.1'
                """
            ),
            id="ec-update",
        ),
        pytest.param(
            dedent(
                """
                ---
                externalResources:
                - provider: aws
                  provisioner:
                    $ref: account-1
                  resources:
                  - provider: rds
                    identifier: rds-1
                    defaults: /path/to/defaults/file.yml
                    output_resource_name: rds-1
                """
            ),
            "aws",
            "another-account",
            "rds",
            "rds-1",
            "15.1",
            "",
            marks=pytest.mark.xfail(strict=True, raises=RuntimeError),
            id="instance-not-found-should-not-happen",
        ),
    ],
)
def test_renderer_render_merge_request_content(
    current_content: str,
    provider: str,
    provisioner_ref: str,
    resource_provider: str,
    resource_identifier: str,
    resource_engine_version: str,
    expected: str,
) -> None:
    renderer = Renderer()
    new = renderer.render_merge_request_content(
        current_content=current_content,
        provider=provider,
        provisioner_ref=provisioner_ref,
        resource_provider=resource_provider,
        resource_identifier=resource_identifier,
        resource_engine_version=resource_engine_version,
    )
    assert new.strip("\n") == expected.strip("\n")
