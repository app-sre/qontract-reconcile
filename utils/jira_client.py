import utils.secret_reader as secret_reader

from jira import JIRA


class JiraClient(object):
    """Wrapper around Jira client"""

    def __init__(self, jira_board, settings=None):
        self.project = jira_board['name']
        self.server = jira_board['serverUrl']
        token = jira_board['token']
        oauth = self.get_oauth_secret(token, settings)
        self.jira = JIRA(self.server, oauth=oauth)

    def get_oauth_secret(self, token, settings):
        required_keys = ['access_token', 'access_token_secret',
                         'consumer_key', 'key_cert']
        secret = secret_reader.read_all(token, settings)
        oauth = {k: v for k, v in secret.items() if k in required_keys}
        ok = all(elem in oauth.keys() for elem in required_keys)
        if not ok:
            raise KeyError(
                '[{}] secret is missing required keys'.format(self.project))

        return oauth

    def get_issues(self):
        block_size = 100
        block_num = 0
        all_issues = []
        jql = 'project={}'.format(self.project)
        while True:
            index = block_num * block_size
            issues = self.jira.search_issues(jql, index, block_size)
            all_issues.extend(issues)
            if len(issues) < block_size:
                break
            block_num += 1

        return all_issues
