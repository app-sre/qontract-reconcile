import pytest
from reconcile.glitchtip import fetch_current_state
from reconcile.utils.glitchtip import GlitchtipClient, Organization, Project, Team, User


@pytest.fixture
def glitchtip_client(mocker) -> GlitchtipClient:
    gtc = mocker.patch("reconcile.utils.glitchtip.GlitchtipClient", autospec=True)
    gtc.organizations.return_value = [
        Organization(id=1, name="ESA", slug="esa", projects=[], teams=[], users=[]),
        Organization(id=2, name="NASA", slug="nasa", projects=[], teams=[], users=[]),
    ]

    # glitchtip_client.teams called twice (orgs:  ESA, NASA)
    gtc.teams.side_effect = (
        # ESA teams
        [
            Team(
                id=1,
                slug="esa-pilots",
                users=[],
            ),
            Team(id=2, slug="esa-flight-control", users=[]),
        ],
        # NASA teams
        [
            Team(
                id=3,
                slug="nasa-pilots",
                users=[],
            ),
            Team(
                id=4,
                slug="nasa-flight-control",
                users=[],
            ),
        ],
    )

    # glitchtip_client.projects called twice (orgs:  ESA, NASA)
    gtc.projects.side_effect = (
        # ESA projects
        [
            Project(
                id=1,
                name="rosetta-spacecraft",
                slug="",
                platform="python",
                teams=[
                    Team(
                        id=1,
                        slug="esa-pilots",
                        users=[],
                    ),
                    Team(
                        id=2,
                        slug="esa-flight-control",
                        users=[],
                    ),
                ],
            ),
            Project(
                id=2,
                name="rosetta-flight-control",
                slug="",
                platform="python",
                teams=[
                    Team(
                        id=2,
                        slug="esa-flight-control",
                        users=[],
                    )
                ],
            ),
        ],
        # NASA projects
        [
            Project(
                id=3,
                name="apollo-11-spacecraft",
                slug="",
                platform="python",
                teams=[
                    Team(
                        id=3,
                        slug="nasa-pilots",
                        users=[],
                    ),
                    Team(
                        id=4,
                        slug="nasa-flight-control",
                        users=[],
                    ),
                ],
            ),
            Project(
                id=4,
                name="apollo-11-flight-control",
                slug="",
                platform="python",
                teams=[
                    Team(
                        id=4,
                        slug="nasa-flight-control",
                        users=[],
                    )
                ],
            ),
        ],
    )

    # glitchtip_client.organization_users called twice (orgs:  ESA, NASA)
    gtc.organization_users.side_effect = (
        # ESA users
        [
            User(
                id=0,
                email="Samantha.Cristoforetti@esa.com",
                role="member",
                pending=False,
            ),
            User(
                id=1,
                email="global-flight-director@global-space-agency.com",
                role="owner",
                pending=False,
            ),
            User(id=2, email="Matthias.Maurer@esa.com", role="member", pending=False),
            User(id=3, email="Tim.Peake@esa.com", role="member", pending=False),
            User(
                id=4, email="please-ignore-me@foobat.com", role="member", pending=False
            ),
        ],
        # NASA users
        [
            User(id=10, email="Neil.Armstrong@nasa.com", role="member", pending=False),
            User(id=11, email="Buzz.Aldrin@nasa.com", role="member", pending=False),
            User(
                id=12,
                email="global-flight-director@global-space-agency.com",
                role="owner",
                pending=False,
            ),
            User(
                id=13,
                email="Michael.Collins@nasa.com",
                role="member",
                pending=False,
            ),
        ],
    )

    # glitchtip_client.users called 4x
    # for each team in all orgs
    # + ESA.esa-pilot
    # + ESA.esa-flight-control
    # + NASA.nasa-pilot
    # + NASA.nasa-flight-control
    gtc.team_users.side_effect = (
        # ESA esa-pilot team users
        [
            User(
                id=0,
                email="Samantha.Cristoforetti@esa.com",
                role="member",
                pending=False,
            )
        ],
        # ESA esa-flight-control team users
        [
            User(
                id=1,
                email="global-flight-director@global-space-agency.com",
                role="owner",
                pending=False,
            ),
            User(
                id=2,
                email="Matthias.Maurer@esa.com",
                role="member",
                pending=False,
            ),
            User(
                id=3,
                email="Tim.Peake@esa.com",
                role="member",
                pending=False,
            ),
            User(
                id=4, email="please-ignore-me@foobat.com", role="member", pending=False
            ),
        ],
        # NASA nasa-pilot team users
        [
            User(
                id=10,
                email="Neil.Armstrong@nasa.com",
                role="member",
                pending=False,
            ),
            User(
                id=11,
                email="Buzz.Aldrin@nasa.com",
                role="member",
                pending=False,
            ),
        ],
        # NASA nasa-flight-control team users
        [
            User(
                id=12,
                email="global-flight-director@global-space-agency.com",
                role="owner",
                pending=False,
            ),
            User(
                id=13,
                email="Michael.Collins@nasa.com",
                role="member",
                pending=False,
            ),
        ],
    )
    return gtc


"""
        projects=[
            Project(
                id=None,
                name="rosetta-spacecraft",
                slug="",
                platform="python",
                teams=[
                    Team(
                        pk=None,
                        slug="esa-pilots",
                        users=[
                            User(
                                pk=None,
                                email="Samantha.Cristoforetti@esa.com",
                                role="member",
                                pending=False,
                            )
                        ],
                    ),
                    Team(
                        pk=None,
                        slug="esa-flight-control",
                        users=[
                            User(
                                pk=None,
                                email="global-flight-director@global-space-agency.com",
                                role="owner",
                                pending=False,
                            ),
                            User(
                                pk=None,
                                email="Matthias.Maurer@esa.com",
                                role="member",
                                pending=False,
                            ),
                            User(
                                pk=None,
                                email="Tim.Peake@esa.com",
                                role="member",
                                pending=False,
                            ),
                        ],
                    ),
                ],
            ),
            Project(
                pk=None,
                name="rosetta-flight-control",
                slug="",
                platform="python",
                teams=[
                    Team(
                        pk=None,
                        slug="esa-flight-control",
                        users=[
                            User(
                                pk=None,
                                email="global-flight-director@global-space-agency.com",
                                role="owner",
                                pending=False,
                            ),
                            User(
                                pk=None,
                                email="Matthias.Maurer@esa.com",
                                role="member",
                                pending=False,
                            ),
                            User(
                                pk=None,
                                email="Tim.Peake@esa.com",
                                role="member",
                                pending=False,
                            ),
                        ],
                    )
                ],
            ),
        ],
        teams=[
            Team(
                pk=None,
                slug="esa-pilots",
                users=[
                    User(
                        pk=None, email="Samantha.Cristoforetti@esa.com", role="member", pending=False
                    )
                ],
            ),
            Team(
                pk=None,
                slug="esa-flight-control",
                users=[
                    User(
                        pk=None,
                        email="global-flight-director@global-space-agency.com",
                        role="owner",
                        pending=False,
                    ),
                    User(
                        pk=None,
                        email="Matthias.Maurer@esa.com",
                        role="member",
                        pending=False,
                    ),
                    User(
                        pk=None,
                        email="Tim.Peake@esa.com",
                        role="member",
                        pending=False,
                    ),
                ],
            ),
        ],
        users=[
            User(pk=None, email="Samantha.Cristoforetti@esa.com", role="member", pending=False),
            User(pk=None, email="global-flight-director@global-space-agency.com", role="owner", pending=False),
            User(pk=None, email="Matthias.Maurer@esa.com", role="member", pending=False),
            User(pk=None, email="Tim.Peake@esa.com", role="member", pending=False),
        ],
    ),
    Organization(
        pk=None,
        name="nasa",
        slug="",
        projects=[
            Project(
                pk=None,
                name="apollo-11-spacecraft",
                slug="",
                platform="python",
                teams=[
                    Team(
                        pk=None,
                        slug="nasa-pilots",
                        users=[
                            User(
                                pk=None,
                                email="Neil.Armstrong@nasa.com",
                                role="member",
                                pending=False,
                            ),
                            User(
                                pk=None,
                                email="Buzz.Aldrin@nasa.com",
                                role="member",
                                pending=False,
                            ),
                        ],
                    ),
                    Team(
                        pk=None,
                        slug="nasa-flight-control",
                        users=[
                            User(
                                pk=None,
                                email="global-flight-director@global-space-agency.com",
                                role="owner",
                                pending=False,
                            ),
                            User(
                                pk=None,
                                email="Michael.Collins@nasa.com",
                                role="member",
                                pending=False,
                            ),
                        ],
                    ),
                ],
            ),
            Project(
                pk=None,
                name="apollo-11-flight-control",
                slug="",
                platform="python",
                teams=[
                    Team(
                        pk=None,
                        slug="nasa-flight-control",
                        users=[
                            User(
                                pk=None,
                                email="global-flight-director@global-space-agency.com",
                                role="owner",
                                pending=False,
                            ),
                            User(
                                pk=None,
                                email="Michael.Collins@nasa.com",
                                role="member",
                                pending=False,
                            ),
                        ],
                    )
                ],
            ),
        ],
        teams=[
            Team(
                pk=None,
                slug="nasa-pilots",
                users=[
                    User(
                        pk=None,
                        email="Neil.Armstrong@nasa.com",
                        role="member",
                        pending=False,
                    ),
                    User(
                        pk=None,
                        email="Buzz.Aldrin@nasa.com",
                        role="member",
                        pending=False,
                    ),
                ],
            ),
            Team(
                pk=None,
                slug="nasa-flight-control",
                users=[
                    User(
                        pk=None,
                        email="global-flight-director@global-space-agency.com",
                        role="owner",
                        pending=False,
                    ),
                    User(
                        pk=None,
                        email="Michael.Collins@nasa.com",
                        role="member",
                        pending=False,
                    ),
                ],
            ),
        ],
        users=[
            User(pk=None, email="Neil.Armstrong@nasa.com", role="member", pending=False),
            User(pk=None, email="Buzz.Aldrin@nasa.com", role="member", pending=False),
            User(pk=None, email="global-flight-director@global-space-agency.com", role="owner", pending=False),
            User(
                pk=None,
                email="Michael.Collins@nasa.com",
                role="member",
                pending=False,
            ),
        ],
    ),
"""


def test_fetch_current_state(glitchtip_client: GlitchtipClient):
    assert fetch_current_state(
        glitchtip_client, ignore_users=["please-ignore-me@foobat.com"]
    ) == [
        Organization(
            id=1,
            name="ESA",
            slug="esa",
            projects=[
                Project(
                    id=1,
                    name="rosetta-spacecraft",
                    slug="",
                    platform="python",
                    teams=[
                        Team(id=1, slug="esa-pilots", users=[]),
                        Team(id=2, slug="esa-flight-control", users=[]),
                    ],
                ),
                Project(
                    id=2,
                    name="rosetta-flight-control",
                    slug="",
                    platform="python",
                    teams=[Team(id=2, slug="esa-flight-control", users=[])],
                ),
            ],
            teams=[
                Team(
                    id=1,
                    slug="esa-pilots",
                    users=[
                        User(
                            id=0,
                            email="Samantha.Cristoforetti@esa.com",
                            role="member",
                            pending=False,
                        )
                    ],
                ),
                Team(
                    id=2,
                    slug="esa-flight-control",
                    users=[
                        User(
                            id=1,
                            email="global-flight-director@global-space-agency.com",
                            role="owner",
                            pending=False,
                        ),
                        User(
                            id=2,
                            email="Matthias.Maurer@esa.com",
                            role="member",
                            pending=False,
                        ),
                        User(
                            id=3,
                            email="Tim.Peake@esa.com",
                            role="member",
                            pending=False,
                        ),
                    ],
                ),
            ],
            users=[
                User(
                    id=0,
                    email="Samantha.Cristoforetti@esa.com",
                    role="member",
                    pending=False,
                ),
                User(
                    id=1,
                    email="global-flight-director@global-space-agency.com",
                    role="owner",
                    pending=False,
                ),
                User(
                    id=2, email="Matthias.Maurer@esa.com", role="member", pending=False
                ),
                User(id=3, email="Tim.Peake@esa.com", role="member", pending=False),
            ],
        ),
        Organization(
            id=2,
            name="NASA",
            slug="nasa",
            projects=[
                Project(
                    id=3,
                    name="apollo-11-spacecraft",
                    slug="",
                    platform="python",
                    teams=[
                        Team(id=3, slug="nasa-pilots", users=[]),
                        Team(id=4, slug="nasa-flight-control", users=[]),
                    ],
                ),
                Project(
                    id=4,
                    name="apollo-11-flight-control",
                    slug="",
                    platform="python",
                    teams=[Team(id=4, slug="nasa-flight-control", users=[])],
                ),
            ],
            teams=[
                Team(
                    id=3,
                    slug="nasa-pilots",
                    users=[
                        User(
                            id=10,
                            email="Neil.Armstrong@nasa.com",
                            role="member",
                            pending=False,
                        ),
                        User(
                            id=11,
                            email="Buzz.Aldrin@nasa.com",
                            role="member",
                            pending=False,
                        ),
                    ],
                ),
                Team(
                    id=4,
                    slug="nasa-flight-control",
                    users=[
                        User(
                            id=12,
                            email="global-flight-director@global-space-agency.com",
                            role="owner",
                            pending=False,
                        ),
                        User(
                            id=13,
                            email="Michael.Collins@nasa.com",
                            role="member",
                            pending=False,
                        ),
                    ],
                ),
            ],
            users=[
                User(
                    id=10, email="Neil.Armstrong@nasa.com", role="member", pending=False
                ),
                User(id=11, email="Buzz.Aldrin@nasa.com", role="member", pending=False),
                User(
                    id=12,
                    email="global-flight-director@global-space-agency.com",
                    role="owner",
                    pending=False,
                ),
                User(
                    id=13,
                    email="Michael.Collins@nasa.com",
                    role="member",
                    pending=False,
                ),
            ],
        ),
    ]
