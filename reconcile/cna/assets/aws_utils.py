from typing import Optional

from reconcile.gql_definitions.cna.queries.aws_arn import CNAAWSSpecV1


def aws_role_arn_for_module(
    aws_cna_cfg: Optional[CNAAWSSpecV1], module: str
) -> Optional[str]:
    if aws_cna_cfg is None:
        return None
    role_arn = aws_cna_cfg.default_role_arn
    for module_config in aws_cna_cfg.module_role_arns or []:
        if module_config.module == module:
            role_arn = module_config.arn
            break
    return role_arn
