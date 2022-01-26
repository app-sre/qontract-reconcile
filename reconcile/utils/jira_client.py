from jira import JIRA, Issue

from reconcile.utils.secret_reader import SecretReader

from typing import Iterable, Mapping, Optional


class JiraClient:
    """Wrapper around Jira client."""

    def __init__(self, jira_board: Mapping[str, str],
                 settings: Optional[Mapping] = None):
        self.secret_reader = SecretReader(settings=settings)
        self.project = jira_board['name']
        jira_server = jira_board['server']
        self.server = jira_server['serverUrl']
        token = jira_server['token']
        token_auth = self.secret_reader.read(token)
        self.jira = JIRA(self.server, token_auth=token_auth)

    def get_issues(self, fields: Optional[Mapping] = None):
        block_size = 100
        block_num = 0
        all_issues = []
        jql = 'project={}'.format(self.project)
        kwargs = {}
        if fields:
            kwargs['fields'] = ','.join(fields)
        while True:
            index = block_num * block_size
            issues = self.jira.search_issues(jql, index, block_size,
                                             **kwargs)
            all_issues.extend(issues)
            if len(issues) < block_size:
                break
            block_num += 1

        return all_issues

    def create_issue(self, summary: str, body: str,
                     labels: Optional[Iterable[str]] = None) -> Issue:
        """Create an issue in our project with the given labels."""
        return self.jira.create_issue(
            project=self.project,
            summary=summary,
            description=body,
            labels=labels,
            issuetype={'name': 'Task'}
        )
