import pytest

from reconcile.aus.models import (
    Sector,
    SectorConfigError,
)


def test_sector_validate_dependencies() -> None:
    sector1 = Sector(name="sector1")
    sector2 = Sector(name="sector2", dependencies=[sector1])
    sector3 = Sector(name="sector3", dependencies=[sector2])
    assert sector3.validate_dependencies()

    # zero-level loop sector1 -> sector1
    sector1 = Sector(name="sector1")
    sector1.dependencies = [sector1]
    with pytest.raises(SectorConfigError):
        sector1.validate_dependencies()

    # single-level loop sector2 -> sector1 -> sector2
    sector1 = Sector(name="sector1")
    sector2 = Sector(name="sector2", dependencies=[sector1])
    sector1.dependencies = [sector2]
    with pytest.raises(SectorConfigError):
        sector2.validate_dependencies()

    # greater-level loop sector3 -> sector2 -> sector1 -> sector3
    sector1 = Sector(name="sector1")
    sector2 = Sector(name="sector2", dependencies=[sector1])
    sector3 = Sector(name="sector3", dependencies=[sector2])
    sector1.dependencies = [sector3]
    with pytest.raises(SectorConfigError):
        sector3.validate_dependencies()
