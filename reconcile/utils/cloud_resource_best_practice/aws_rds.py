from typing import Any

from terrascript.resource import aws_db_instance

delete_automated_backups = "delete_automated_backups"
skip_final_snapshot = "skip_final_snapshot"
backup_retention_period = "backup_retention_period"


# Keeping the exception specific now, we can build a generic exception and refactor later
# as more cases arise in the future.
class RDSBestPracticesNotComplied(Exception):
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


OPERATOR_EQUAL_TO = "EQUAL_TO"
OPERATOR_GREATER_THAN_OR_EQUAL_TO = "GREATER_THAN_OR_EQUAL_TO"


__loss_impact_high = [
    (delete_automated_backups, False, OPERATOR_EQUAL_TO),
    (skip_final_snapshot, False, OPERATOR_EQUAL_TO),
    (backup_retention_period, 7, OPERATOR_GREATER_THAN_OR_EQUAL_TO),
]

__loss_impact_medium = [
    (skip_final_snapshot, False, OPERATOR_EQUAL_TO),
    (backup_retention_period, 7, OPERATOR_GREATER_THAN_OR_EQUAL_TO),
]
__loss_impact_low = [(backup_retention_period, 3, OPERATOR_GREATER_THAN_OR_EQUAL_TO)]

__loss_impact_none = [(backup_retention_period, 0, OPERATOR_GREATER_THAN_OR_EQUAL_TO)]


# Keeping this method here for now, we can re-evaluate if this needs to go to separate util once more
# use-cases are built. We could also couple operator with the operations, but keeping that for future iteration.
def _check(aws_db_instance: aws_db_instance, checks: list) -> None:
    rds_fields_not_complied = []
    for field, expected_value, operator in checks:
        if operator == OPERATOR_EQUAL_TO:
            if not aws_db_instance.get(field) == expected_value:
                rds_fields_not_complied.append(
                    (field, aws_db_instance.get(field), expected_value)
                )
        elif operator == OPERATOR_GREATER_THAN_OR_EQUAL_TO:
            if not aws_db_instance.get(field) >= expected_value:
                rds_fields_not_complied.append(
                    (field, aws_db_instance.get(field), expected_value)
                )

    if len(rds_fields_not_complied) > 0:
        raise RDSBestPracticesNotComplied(
            rds_fields_not_complied, aws_db_instance._name
        )


def _verify_loss_impact(aws_db_instance: aws_db_instance, loss_impact: str) -> None:
    if loss_impact == "high":
        _check(aws_db_instance, __loss_impact_high)
    elif loss_impact == "medium":
        _check(aws_db_instance, __loss_impact_medium)
    elif loss_impact == "low":
        _check(aws_db_instance, __loss_impact_low)
    elif loss_impact == "none":
        _check(aws_db_instance, __loss_impact_none)


def verify_rds_best_practices(
    aws_db_instance: aws_db_instance, data_classification: dict
) -> None:
    if data_classification is None:
        return
    _verify_loss_impact(aws_db_instance, data_classification["loss_impact"])
