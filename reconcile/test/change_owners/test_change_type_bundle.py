from typing import (
    Any,
    Optional,
)

import pytest
from pytest_mock.plugin import MockerFixture

from reconcile.change_owners import bundle
from reconcile.change_owners.bundle import (
    BundleFileType,
    FileRef,
    QontractServerFileDiffResolver,
)


@pytest.mark.parametrize(
    "old,new",
    [
        ({"data": "old"}, {"data": "new"}),
        (None, {"data": "new"}),
        ({"data": "old"}, None),
        (None, None),
    ],
)
def test_qontract_server_file_diff_resolver(
    mocker: MockerFixture, old: Optional[dict[str, Any]], new: Optional[dict[str, Any]]
) -> None:
    get_diff_mock = mocker.patch.object(bundle, "get_diff")
    resolved_data = {}
    if old is not None:
        resolved_data["old"] = old
    if new is not None:
        resolved_data["new"] = new
    get_diff_mock.return_value = resolved_data

    resolver = QontractServerFileDiffResolver("sha")
    resolved_old, resolved_new = resolver.lookup_file_diff(
        FileRef(file_type=BundleFileType.DATAFILE, path="path", schema=None)
    )
    assert resolved_old == old
    assert resolved_new == new
