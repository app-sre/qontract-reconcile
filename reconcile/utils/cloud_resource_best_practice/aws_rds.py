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


__loss_impact_high = {
    delete_automated_backups: "no",
    skip_final_snapshot: "no",
    backup_retention_period: 7,
}

__loss_impact_medium = {
    delete_automated_backups: "yes",
    skip_final_snapshot: "no",
    backup_retention_period: 7,
}

__loss_impact_low = {
    delete_automated_backups: "yes",
    skip_final_snapshot: "yes",
    backup_retention_period: 3,
}

__loss_impact_none = {
    delete_automated_backups: "yes",
    skip_final_snapshot: "yes",
    backup_retention_period: 0,
}


# Keeping this method here for now, we can re-evaluate if this needs to go to separate util once more
# use-cases are built.
def _check(aws_db_instance: aws_db_instance, d: dict) -> None:
    rds_fields_not_complied = []
    for k, v in d.items():
        if k in aws_db_instance:
            if v != aws_db_instance[k]:
                rds_fields_not_complied.append((k, aws_db_instance[k], v))
        else:
            rds_fields_not_complied.append((k, None, v))

    if len(rds_fields_not_complied) > 0:
        raise RDSBestPracticesNotComplied(
            rds_fields_not_complied, aws_db_instance._name
        )


def _verify_loss_impact(aws_db_instance: aws_db_instance, loss_impact: str) -> None:
    if loss_impact == "high":
        _check(aws_db_instance, __loss_impact_high)
    if loss_impact == "medium":
        _check(aws_db_instance, __loss_impact_medium)
    if loss_impact == "low":
        _check(aws_db_instance, __loss_impact_low)
    if loss_impact == "none":
        _check(aws_db_instance, __loss_impact_none)


def verify_rds_best_practices(
    aws_db_instance: aws_db_instance, data_classification: dict
) -> None:
    if data_classification is None:
        return
    _verify_loss_impact(aws_db_instance, data_classification["loss_impact"])
