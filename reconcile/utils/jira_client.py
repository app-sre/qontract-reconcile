from jira import JIRA

from reconcile.utils.secret_reader import SecretReader


class JiraClient:
    """Wrapper around Jira client"""

    def __init__(self, jira_board, settings=None):
        self.secret_reader = SecretReader(settings=settings)
        self.project = jira_board['name']
        jira_server = jira_board['server']
        self.server = jira_server['serverUrl']
        token = jira_server['token']
        basic_auth = self.get_basic_auth(token)
        self.jira = JIRA(self.server, basic_auth=basic_auth)

    def get_basic_auth(self, token):
        required_keys = ['username', 'password']
        secret = self.secret_reader.read_all(token)
        ok = all(elem in secret.keys() for elem in required_keys)
        if not ok:
            raise KeyError(
                '[{}] secret is missing required keys'.format(self.project))

        return (secret['username'], secret['password'])

    def get_issues(self, fields=None):
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
