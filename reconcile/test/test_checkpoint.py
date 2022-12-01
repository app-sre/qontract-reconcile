from http import HTTPStatus

import pytest
import requests

import reconcile.checkpoint as sut


@pytest.fixture
def valid_app():
    """How a valid application looks like."""
    return {
        "sopsUrl": "https://www.redhat.com/sops",
        "architectureDocument": "https://www.redhat.com/arch",
        "grafanaUrl": "https://www.redhat.com/graf",
        "serviceOwners": [{"name": "A Name", "email": "aname@adomain.com"}],
    }


@pytest.fixture
def valid_owner():
    """How a valid owner looks like."""
    return {"name": "A Name", "email": "a.name@redhat.com"}


def invalid_owners():
    """List the ways in which an owner can be invalid."""
    return [
        {"name": "A Name", "email": None},
        {"name": "A Name", "email": "domainless"},
        {"name": "A Name", "email": "@name.less"},
        {"name": None, "email": "a-name@redhat.com"},
    ]


def test_valid_owner(valid_owner) -> None:
    """Confirm that the valid owner is recognized as such."""
    assert sut.valid_owners([valid_owner])


@pytest.mark.parametrize("invalid_owner", invalid_owners())
def test_invalid_owners(invalid_owner):
    """Confirm that the invalid owners are flagged."""
    assert not sut.valid_owners([invalid_owner])


@pytest.mark.parametrize("invalid_owner", invalid_owners())
def test_invalid_owners_remain_invalid(valid_owner, invalid_owner):
    """Confirm rejection of invalid owners even mixed with good ones."""
    assert not sut.valid_owners([valid_owner, invalid_owner])


def test_url_makes_sense_ok(mocker):
    """Good URLs are accepted."""
    get = mocker.patch.object(requests, "get", autospec=True)
    r = requests.Response()
    r.status_code = HTTPStatus.OK
    get.return_value = r

    assert sut.url_makes_sense("https://www.redhat.com/existing")


def test_url_makes_sense_unknown(mocker):
    """Ensure rejection of URLs pointing to missing documents."""
    get = mocker.patch.object(requests, "get", autospec=True)
    r = requests.Response()
    r.status_code = HTTPStatus.NOT_FOUND
    get.return_value = r
    assert not sut.url_makes_sense("https://www.redhat.com/nonexisting")


def test_url_makes_sense_error():
    """Ensure rejection of URLs returning ConnectionError."""
    assert not sut.url_makes_sense("https://TODO")


def test_url_makes_sense_empty():
    """Ensure rejection of empty URLs."""
    assert not sut.url_makes_sense("")


def test_render_template():
    """Confirm rendering of all placeholders in the ticket template."""
    txt = sut.render_template(
        sut.MISSING_DATA_TEMPLATE, "aname", "apath", "afield", "avalue"
    )
    assert "aname" in txt
    assert "apath" in txt
    assert "afield" in txt
    assert "avalue" in txt


def app_metadata():
    """List some metadata for some fake apps.

    Returns the app structure and whether we expect it to have a
    ticket associated with it
    """
    return [
        (
            {
                "name": "appname",
                "sopsUrl": "https://www.somewhe.re",
                "architectureDocument": "https://www.hereand.now",
                "grafanaUrls": [],
            },
            False,
        ),
        # Missing field - should cut a ticket
        (
            {
                "name": "appname",
                "sopsUrl": "https://www.somewhe.re",
                "grafanaUrls": [],
            },
            True,
        ),
        # Bad field - should cut a ticket
        (
            {
                "name": "appname",
                "architectureDocument": "",
                "grafanaUrls": [],
                "sopsUrl": "http://www.herea.nd",
            },
            True,
        ),
    ]


@pytest.mark.parametrize("app,needs_ticket", app_metadata())
def test_report_invalid_metadata(mocker, app, needs_ticket):
    """Test that valid apps don't get tickets and that invalid apps do."""
    # TODO: I'm pretty sure a fixture can help with this
    jira = mocker.patch.object(sut, "JiraClient", autospec=True)
    filer = mocker.patch.object(sut, "file_ticket", autospec=True)

    valid = sut.VALIDATORS

    sut.VALIDATORS = {
        "sopsUrl": bool,
        "architectureDocument": bool,
        "grafanaUrls": lambda _: True,
    }

    sut.report_invalid_metadata(app, "/a/path", "jiraboard", {}, "TICKET-123")
    if needs_ticket:
        filer.assert_called_once_with(
            jira=jira.return_value,
            app_name=app["name"],
            labels=sut.DEFAULT_CHECKPOINT_LABELS,
            parent="TICKET-123",
            field="architectureDocument",
            bad_value=str(app.get("architectureDocument")),
            app_path="/a/path",
        )
    else:
        filer.assert_not_called()

    sut.VALIDATORS = valid


@pytest.mark.parametrize("app,needs_ticket", app_metadata())
def test_report_invalid_metadata_dry_run(mocker, app, needs_ticket):
    """Test the dry-run mode."""
    renderer = mocker.patch.object(sut, "render_template", autospec=True)
    valid = sut.VALIDATORS
    sut.VALIDATORS = {
        "sopsUrl": bool,
        "architectureDocument": bool,
        "grafanaUrls": lambda _: True,
    }
    sut.report_invalid_metadata(app, "/a/path", "jiraboard", {}, "TICKET-123", True)
    if needs_ticket:
        renderer.assert_called_once()
    else:
        renderer.assert_not_called()
    sut.VALIDATORS = valid
