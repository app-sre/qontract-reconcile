from reconcile.utils.unleash.server import Project, UnleashServer


def test_unleash_server_projects(client: UnleashServer) -> None:
    assert client.projects() == [
        Project(pk="default", name="Default", feature_toggles=[])
    ]
