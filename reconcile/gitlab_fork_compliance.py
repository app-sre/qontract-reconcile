import logging
from gitlab import MAINTAINER_ACCESS

from reconcile import queries
from utils.gitlab_api import GitLabApi


_LOG = logging.getLogger(__name__)

QONTRACT_INTEGRATION = 'gitlab-fork-compliance'

BLOCKED_LABEL = 'blocked/bot-access'

MSG_BRANCH = ('@{user}, this Merge Request is using the "master" '
              'source branch. Please submit a new Merge Request from another '
              'branch.')

MSG_ACCESS = ('@{user}, this fork of {project_name} is not shared with '
              '[{bot}](/{bot}) as "Maintainer". !!Please '
              '[add the user to the project]'
              '({source_project_url}/project_members) '
              'and retest by commenting "[test]" on the merge request.')


def run(project_id, mr_id, maintainers_group, dry_run=False):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()

    gitlab_cli = GitLabApi(instance, project_id=project_id,
                           settings=settings)

    mr = gitlab_cli.get_merge_request(mr_id)

    # If the Merge Request is using the 'master' source branch, we
    # just add an error note to the merge request
    if mr.source_branch == 'master':
        _LOG.error(['source branch can not be master'])
        if not dry_run:
            mr.notes.create(
                {'body': MSG_BRANCH.format(user=mr.author['username'])}
            )
        return

    source_project = GitLabApi(instance, project_id=mr.source_project_id,
                               settings=settings)

    # If the bot is not a maintainer on the fork,
    # add the blocked label and the error note to the
    # merge request
    project_bot = source_project.project.members.get(gitlab_cli.user.id)
    if not project_bot or project_bot.access_level != MAINTAINER_ACCESS:
        _LOG.error([f'{gitlab_cli.user.username} is not a fork maintainer'])
        if not dry_run:
            gitlab_cli.add_label_to_merge_request(mr.iid, BLOCKED_LABEL)
            url = source_project.project.web_url
            mr.notes.create(
                {'body': MSG_ACCESS.format(user=mr.author['username'],
                                           bot=gitlab_cli.user.username,
                                           source_project_url=url)}
            )
        return

    # At this point, we know that the bot is a maintainer, so
    # we check if all the maintainers are in the fork, adding those
    # who are not
    group = gitlab_cli.gl.groups.get(maintainers_group)
    maintainers = group.members.list()
    for member in maintainers:
        if member in source_project.project.members.list():
            continue

        _LOG.info([f'adding {member.username} as maintainer'])
        if not dry_run:
            user_payload = {'user_id': member.id,
                            'access_level': MAINTAINER_ACCESS}
            member = source_project.project.members.create(user_payload)
            member.save()

    # Last but not least, we remove the blocked label, in case
    # it is set
    blocked = BLOCKED_LABEL in gitlab_cli.get_merge_request_labels(mr.iid)
    if not dry_run and blocked:
        gitlab_cli.remove_label_from_merge_request(mr.iid, BLOCKED_LABEL)
