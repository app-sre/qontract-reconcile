def _setup_mocks(mocker, clusters=None, accounts=None):
    mocker.patch("reconcile.queries.get_secret_reader_settings", return_value={})
    mocker.patch(
        "reconcile.queries.get_clusters_with_peering_settings",
        return_value=clusters or [],
    )
    mocker.patch("reconcile.queries.get_aws_accounts", return_value=accounts or [])
    mocker.patch("reconcile.utils.aws_api.AWSApi", autospec=True)
    mocked_ts = mocker.patch(
        "reconcile.utils.terrascript_aws_client.TerrascriptClient", autospec=True
    ).return_value
    mocked_ts.dump.return_value = ["/tmp/a"]

    mocked_tf = mocker.patch(
        "reconcile.utils.terraform_client.TerraformClient", autospec=True
    ).return_value
    mocked_tf.plan.return_value = (False, False)
    mocked_tf.apply.return_value = False
    return {
        "tf": mocked_tf,
    }


def test_dry_run(mocker):
    mocks = _setup_mocks(mocker)

    from reconcile.terraform_tgw_attachments import run

    run(True, enable_deletion=False)

    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_not_called()


def test_non_dry_run(mocker):
    mocks = _setup_mocks(mocker)

    from reconcile.terraform_tgw_attachments import run

    run(False, enable_deletion=False)

    mocks["tf"].plan.assert_called_once_with(False)
    mocks["tf"].apply.assert_called_once()
