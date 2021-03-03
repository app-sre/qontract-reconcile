from urllib.parse import urlparse

import requests


class QontractServerClient:
    """REST API for Qontract Server """

    def __init__(self, url, token=None,
                 sticky_session=False,
                 sha_url=False):
        self.base_url = url
        self.sha = None
        self.headers = {}

        if token:
            self.headers['Authorization'] = token

        if sticky_session:
            self.session = requests.Session()
        else:
            self.session = None

        if sha_url:
            self.sha = self.get_sha()
            self.query_url = self._base_url_path(
                path=f'/graphqlsha/{self.sha}')
        else:
            self.query_url = url

    def get_sha(self):
        """Get the sha of the last bundle.

        :return: sha of the last bundle
        :rtype: str
        """
        response = self._get(path='/sha256')
        return response.content.decode('utf-8')

    def get_git_commit_info(self, sha=None):
        """Get the commit information

        :param sha: sha, defaults to the active one
        :type sha: str
        :raises Exception: This method cannot be called if sha is not provided
            and sha_url is not enabled.
        :return: {'timestamp': '<ts>', 'commit': '<commit>'}
        :rtype: dict
        """
        if sha is None:
            sha = self.sha

        if sha is None:
            raise Exception('cannot get info if sha is None')

        response = self._get(path=f'/git-commit-info/{sha}')
        response.raise_for_status()
        return response.json()

    def query(self, query, variables=None):
        """Performs a GraphQL query

        :param query: the graphql query
        :type query: str
        :param variables: dictionary of variables, defaults to None
        :type variables: dict, optional
        :return: graphql response payload. keys: 'data' and '
        :rtype: dict
        """
        data = {'query': query, 'variables': variables}

        if self.session:
            post_method = self.session.post
        else:
            post_method = requests.post

        r = post_method(self.query_url, json=data,
                        headers=self._headers(json=True))
        r.raise_for_status()
        return r.json()

    def _headers(self, json=False):
        if json:
            return {'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    **self.headers}
        return self.headers

    def _base_url_path(self, path):
        return urlparse(self.base_url)._replace(path=path).geturl()

    def _get(self, path):
        url = self._base_url_path(path)
        response = requests.get(url, headers=self._headers())
        response.raise_for_status()
        return response
