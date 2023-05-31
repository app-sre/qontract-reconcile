import operator
from typing import Any

from terrascript.resource import aws_db_instance

delete_automated_backups = "delete_automated_backups"
skip_final_snapshot = "skip_final_snapshot"
backup_retention_period = "backup_retention_period"


# Keeping the exception specific now, we can build a generic exception and refactor later
# as more cases arise in the future.
class RDSResourceComplianceError(Exception):
    def __init__(
        self, field_expected_actual: list[tuple[str, Any, Any]], db_identifier: str
    ):
        self.actual_vs_expected = field_expected_actual

        self.message = (
            f"AWS RDS instance {db_identifier} does not comply with best practices\n"
        )

        for field, actual, expected in field_expected_actual:
            self.message += (
                f'Expected field {field} with value "{expected}", found "{actual}" \n'
            )
        super().__init__(self.message)


__loss_impact_levels = {
    "high": [
        (delete_automated_backups, False, operator.__eq__),
        (skip_final_snapshot, False, operator.__eq__),
        (backup_retention_period, 7, operator.__ge__),
    ],
    "medium": [
        (skip_final_snapshot, False, operator.__eq__),
        (backup_retention_period, 7, operator.__ge__),
    ],
    "low": [(backup_retention_period, 3, operator.__ge__)],
    "none": [(backup_retention_period, 0, operator.__ge__)],
}


# Keeping this method here for now, we can re-evaluate if this needs to go to separate util once more
# use-cases are built.
def _check(aws_db_instance: aws_db_instance, checks: list) -> None:
    rds_fields_not_complied = []
    for field, expected_value, op in checks:
        if not op(aws_db_instance.get(field), expected_value):
            rds_fields_not_complied.append(
                (field, aws_db_instance.get(field), expected_value)
            )

    if len(rds_fields_not_complied) > 0:
        raise RDSResourceComplianceError(rds_fields_not_complied, aws_db_instance._name)


def verify_rds_best_practices(
    aws_db_instance: aws_db_instance, data_classification: dict
) -> None:
    if data_classification is None:
        return
    _check(aws_db_instance, __loss_impact_levels[data_classification["loss_impact"]])
