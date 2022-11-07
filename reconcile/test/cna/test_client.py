from reconcile.cna.client import CNAClient


def test_client_asset_type_metadata_init():
    pass


def test_client_list_assets_for_creator(mocker):
    creator = "creator"
    listed_assets = [
        {
            "asset_type": "null",
            "id": "123",
            "href": "url/123",
            "status": "Running",
            "creator": {"username": creator},
        },
        {
            "asset_type": "null",
            "id": "456",
            "href": "url/456",
            "status": "Running",
            "creator": {},
        },
        {
            "asset_type": "null",
            "id": "789",
            "href": "url/789",
            "status": "Running",
        },
        {
            "asset_type": "null",
            "id": "000",
            "href": "url/000",
            "status": "Running",
            "creator": {"username": "another_user"},
        },
    ]

    mocker.patch.object(CNAClient, "list_assets", return_value=listed_assets)
    cna_client = CNAClient(None)  # type: ignore

    creator_assets = cna_client.list_assets_for_creator(creator)
    for asset in creator_assets:
        assert asset["creator"]["username"] == creator
