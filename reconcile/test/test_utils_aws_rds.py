import pytest
from terrascript.resource import aws_db_instance

from reconcile.utils.cloud_resource_best_practice.aws_rds import (
    RDSResourceComplianceError,
    verify_rds_best_practices,
)


def test_rds_best_practices_compliant_db():
    db = aws_db_instance(
        "my-db",
        delete_automated_backups=False,
        skip_final_snapshot=False,
        backup_retention_period=7,
    )

    verify_rds_best_practices(db, {"loss_impact": "high"})


def test_rds_best_practices_non_compliant_db():

    db = aws_db_instance(
        "my-db",
        delete_automated_backups=True,
        skip_final_snapshot=True,
        backup_retention_period=7,
    )
    with pytest.raises(RDSResourceComplianceError) as e:
        verify_rds_best_practices(db, {"loss_impact": "high"})
    assert (
        e.value.message
        == "AWS RDS instance my-db does not comply with best practices\nExpected field delete_automated_backups with "
        'value "False", found "True" \nExpected field skip_final_snapshot with value "False", found "True" \n'
    )
