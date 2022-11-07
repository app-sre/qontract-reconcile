from reconcile.cna.assets.asset_factory import register_asset_dataclass
from reconcile.cna.assets.null import NullAsset
from reconcile.cna.assets.aws_assume_role import AWSAssumeRoleAsset


register_asset_dataclass(NullAsset)
register_asset_dataclass(AWSAssumeRoleAsset)
