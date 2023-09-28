import logging
from collections.abc import (
    Iterable,
    Sequence,
)

from reconcile.utils.differ import diff_iterables
from reconcile.utils.glitchtip import (
    GlitchtipClient,
    Organization,
    Project,
    Team,
    User,
)


class GlitchtipReconciler:
    def __init__(self, client: GlitchtipClient, dry_run: bool):
        self.client = client
        self.dry_run = dry_run

    def _reconcile_projects(
        self,
        organization_slug: str,
        organization_teams: Sequence[Team],
        current_projects: Iterable[Project],
        desired_projects: Iterable[Project],
    ) -> list[Project]:
        """Reconcile organization projects."""
        organization_projects = list(current_projects)
        project_diff = diff_iterables(
            current=current_projects,
            desired=desired_projects,
            key=lambda p: p.slug,
            equal=lambda p1, p2: not p1.diff(p2),
        )
        for project in project_diff.delete.values():
            logging.info(
                ["delete_project", organization_slug, project.name, self.client.host]
            )
            del organization_projects[organization_projects.index(project)]
            if not self.dry_run:
                self.client.delete_project(
                    organization_slug=organization_slug,
                    slug=project.slug,
                )

        for project in project_diff.add.values():
            logging.info(
                ["create_project", organization_slug, project.name, self.client.host]
            )
            if not self.dry_run:
                new_project = self.client.create_project(
                    organization_slug=organization_slug,
                    # there is at least one team. GQL schema enforces it
                    team_slug=project.teams[0].slug,
                    name=project.name,
                    platform=project.platform,
                )
            else:
                new_project = Project(name=project.name, platform=project.platform)
            organization_projects.append(new_project)

        for project in (p.desired for p in project_diff.change.values()):
            logging.info(
                ["update_project", organization_slug, project.name, self.client.host]
            )
            if not self.dry_run:
                updated_project = self.client.update_project(
                    organization_slug=organization_slug,
                    slug=project.slug,
                    name=project.name,
                    platform=project.platform,
                )
                organization_projects[
                    organization_projects.index(project)
                ] = updated_project

        for desired_project in desired_projects:
            current_project = organization_projects[
                organization_projects.index(desired_project)
            ]

            for team in set(current_project.teams).difference(desired_project.teams):
                logging.info(
                    [
                        "remove_project_from_team",
                        organization_slug,
                        team.slug,
                        desired_project.slug,
                        self.client.host,
                    ]
                )
                del current_project.teams[current_project.teams.index(team)]
                if not self.dry_run:
                    self.client.remove_project_from_team(
                        organization_slug=organization_slug,
                        team_slug=team.slug,
                        slug=desired_project.slug,
                    )
            for team in set(desired_project.teams).difference(current_project.teams):
                try:
                    org_team = organization_teams[organization_teams.index(team)]
                except ValueError:
                    logging.error(
                        f"Cannot find team {team.slug} in organization. This shouldn't happen!"
                    )
                    continue

                logging.info(
                    [
                        "add_project_to_team",
                        organization_slug,
                        org_team.slug,
                        current_project.slug,
                        self.client.host,
                    ]
                )
                current_project.teams.append(team)
                if not self.dry_run:
                    self.client.add_project_to_team(
                        organization_slug=organization_slug,
                        team_slug=org_team.slug,
                        slug=current_project.slug,
                    )
        return organization_projects

    def _reconcile_teams(
        self,
        organization_slug: str,
        organization_users: Sequence[User],
        current_teams: Sequence[Team],
        desired_teams: Iterable[Team],
    ) -> list[Team]:
        """Reconcile organization teams.

        Return all organization teams (merge of current_teams & desired_teams including pk's, users, ...).
        """
        organization_teams = list(current_teams)
        for team in set(current_teams).difference(desired_teams):
            logging.info(
                ["delete_team", organization_slug, team.slug, self.client.host]
            )
            del organization_teams[organization_teams.index(team)]
            if not self.dry_run:
                self.client.delete_team(
                    organization_slug=organization_slug, slug=team.slug
                )
        for team in set(desired_teams).difference(current_teams):
            logging.info(
                ["create_team", organization_slug, team.slug, self.client.host]
            )
            if not self.dry_run:
                new_team = self.client.create_team(
                    organization_slug=organization_slug, slug=team.slug
                )
            else:
                new_team = Team(slug=team.slug)
            organization_teams.append(new_team)

        for desired_team in desired_teams:
            current_team = organization_teams[organization_teams.index(desired_team)]

            for user in set(current_team.users).difference(desired_team.users):
                logging.info(
                    [
                        "remove_user_from_team",
                        organization_slug,
                        user.email,
                        desired_team.slug,
                        self.client.host,
                    ]
                )
                del current_team.users[current_team.users.index(user)]
                if not self.dry_run:
                    if user.pk is None:
                        continue
                    self.client.remove_user_from_team(
                        organization_slug=organization_slug,
                        team_slug=current_team.slug,
                        user_pk=user.pk,
                    )
            for user in set(desired_team.users).difference(current_team.users):
                logging.info(
                    [
                        "add_user_to_team",
                        organization_slug,
                        user.email,
                        current_team.slug,
                        self.client.host,
                    ]
                )
                current_team.users.append(user)
                if not self.dry_run:
                    try:
                        org_user = organization_users[organization_users.index(user)]
                    except ValueError:
                        logging.info(f"{user.email} isn't organization member yet.")
                        continue

                    if org_user.pk is None:
                        continue
                    self.client.add_user_to_team(
                        organization_slug=organization_slug,
                        team_slug=current_team.slug,
                        user_pk=org_user.pk,
                    )
        return organization_teams

    def _reconcile_users(
        self,
        organization_slug: str,
        current_users: Iterable[User],
        desired_users: Iterable[User],
    ) -> list[User]:
        """Reconcile organization users.

        Return all organization users (merge of current_users & desired_users including pk's).
        """
        organization_users = list(current_users)
        for user in set(current_users).difference(desired_users):
            logging.info(
                ["delete_user", organization_slug, user.email, self.client.host]
            )
            del organization_users[organization_users.index(user)]
            if not self.dry_run:
                if user.pk is None:
                    continue
                self.client.delete_user(organization_slug=organization_slug, pk=user.pk)
        for user in set(desired_users).difference(current_users):
            logging.info(["add_user", organization_slug, user.email, self.client.host])
            if not self.dry_run:
                new_user = self.client.invite_user(
                    organization_slug=organization_slug,
                    email=user.email,
                    role=user.role,
                )
            else:
                new_user = User(email=user.email, role=user.role, pending=True)
            organization_users.append(new_user)

        for desired_user in desired_users:
            org_user = organization_users[organization_users.index(desired_user)]
            if desired_user.role != org_user.role:
                logging.info(
                    [
                        "update_user_role",
                        organization_slug,
                        desired_user.email,
                        desired_user.role,
                        self.client.host,
                    ]
                )
                if not self.dry_run:
                    if org_user.pk is None:
                        continue
                    self.client.update_user_role(
                        organization_slug=organization_slug,
                        role=desired_user.role,
                        pk=org_user.pk,
                    )

        return organization_users

    def reconcile(
        self,
        current: Sequence[Organization],
        desired: Iterable[Organization],
    ) -> None:
        for desired_org in desired:
            if desired_org not in current:
                logging.info(
                    ["create_organization", desired_org.name, self.client.host]
                )
                if not self.dry_run:
                    current_org = self.client.create_organization(name=desired_org.name)
                else:
                    # dry-run mode - use empty Org and go ahead
                    current_org = Organization(name=desired_org.name)
            else:
                current_org = current[current.index(desired_org)]

            organization_slug = current_org.slug
            organization_users = self._reconcile_users(
                organization_slug=organization_slug,
                current_users=current_org.users,
                desired_users=desired_org.users,
            )
            organization_teams = self._reconcile_teams(
                organization_slug=organization_slug,
                organization_users=organization_users,
                current_teams=current_org.teams,
                desired_teams=desired_org.teams,
            )
            self._reconcile_projects(
                organization_slug=organization_slug,
                organization_teams=organization_teams,
                current_projects=current_org.projects,
                desired_projects=desired_org.projects,
            )

        # remove obsolete organizations after creating/updating other ones. this avoids a chicken-egg problem when onboarding a new glitchtip instance.
        # the automation user must have the owner role in an existing organization (bootstrap organization) but this one is maybe not app-interface managed
        for org in set(current).difference(desired):
            logging.info(["delete_organization", org.name, self.client.host])
            if not self.dry_run:
                self.client.delete_organization(slug=org.slug)
