import pytest


@pytest.fixture
def env_vars(monkeypatch):
    monkeypatch.setenv('APP_INTERFACE_STATE_BUCKET', 'some-bucket')
    monkeypatch.setenv('APP_INTERFACE_STATE_BUCKET_ACCOUNT', 'some-account')


@pytest.fixture
def mock_queries(mocker):
    mocker.patch('tools.qontract_cli.queries', autospec=True)


@pytest.fixture
def mock_state(mocker):
    return mocker.patch('tools.qontract_cli.State', autospec=True)

