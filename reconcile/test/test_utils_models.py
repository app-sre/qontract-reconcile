import pytest
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    validator,
)

from reconcile.utils.models import (
    CSV,
    cron_validator,
)


class CSVModel(BaseModel):
    csv: CSV


def test_csv_type():
    assert CSVModel(csv="a,b,c").csv == ["a", "b", "c"]
    assert CSVModel(csv="a").csv == ["a"]


def test_csv_type_empty():
    assert CSVModel(csv="").csv == []


class ConstrainedCSVModel(BaseModel):
    csv: CSV = Field(csv_min_items=2, csv_max_items=3)


def test_constrained_csv_type():
    ConstrainedCSVModel(csv="a,b")
    ConstrainedCSVModel(csv="a,b,c")


def test_constrained_csv_type_min_violation():
    with pytest.raises(ValidationError):
        ConstrainedCSVModel(csv="a")


def test_constrained_csv_type_max_violation():
    with pytest.raises(ValidationError):
        ConstrainedCSVModel(csv="a,b,c,d")


class CronModel(BaseModel):
    cron: str
    _cron_validator = validator("cron", allow_reuse=True)(cron_validator)


def test_cron_validation():
    CronModel(cron="0 * * * 1-5")


def test_cron_validation_invalid():
    with pytest.raises(ValidationError):
        CronModel(cron="0 48 * * 1-5")
