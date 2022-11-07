from reconcile.cna.assets.aws_assume_role import AWSAssumeRoleAsset
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNAAssumeRoleAssetV1,
    CNAAssumeRoleAssetConfigV1,
)
from reconcile.gql_definitions.cna.queries.aws_account_fragment import (
    CNAAWSAccountRoleARNs,
    CNAAWSSpecV1,
)


def test_from_query_class():
    name = "name"
    slug = "slug"
    arn = "arn"
    query_asset = CNAAssumeRoleAssetV1(
        provider=AWSAssumeRoleAsset.provider(),
        name=name,
        aws_assume_role=CNAAssumeRoleAssetConfigV1(
            slug=slug,
            account=CNAAWSAccountRoleARNs(
                name="acc",
                cna=CNAAWSSpecV1(defaultRoleARN=arn, moduleRoleARNS=None),
            ),
        ),
    )
    asset = AWSAssumeRoleAsset.from_query_class(query_asset)
    assert isinstance(asset, AWSAssumeRoleAsset)
    assert asset.name == name
    assert asset.verify_slug == slug
    assert asset.role_arn == arn
