import requests


class RawGithubApi(object):
    """
    REST based GH interface

    Unfortunately this needs to be used because PyGithub does not yet support
    checking pending invitations
    """

    BASE_URL = "https://api.github.com"
    BASE_HEADERS = {
        'Accept': 'application/vnd.github.v3+json,'
        'application/vnd.github.dazzler-preview+json'
    }

    def __init__(self, password):
        self.password = password

    def headers(self, headers={}):
        new_headers = headers.copy()
        new_headers.update(self.BASE_HEADERS)
        new_headers['Authorization'] = "token %s" % (self.password,)
        return new_headers

    def query(self, url, headers={}):
        h = self.headers(headers)

        res = requests.get(self.BASE_URL + url, headers=h)
        try:
            res.raise_for_status()
        except Exception as e:
            raise Exception("query: %s %s\n%s" %
                            (self.BASE_URL + url, h, e.message))

        result = res.json()

        if isinstance(result, list):
            elements = []

            for element in result:
                elements.append(element)

            while 'last' in res.links and 'next' in res.links:
                if res.links['last']['url'] == res.links['next']['url']:
                    req_url = res.links['next']['url']
                    res = requests.get(req_url, headers=h)

                    try:
                        res.raise_for_status()
                    except Exception as e:
                        raise Exception("query: %s %s\n%s" %
                                        (req_url, h, e.message))

                    for element in res.json():
                        elements.append(element)

                    return elements
                else:
                    req_url = res.links['next']['url']
                    res = requests.get(req_url, headers=h)

                    try:
                        res.raise_for_status()
                    except Exception as e:
                        raise Exception("query: %s %s\n%s" %
                                        (req_url, h, e.message))

                    for element in res.json():
                        elements.append(element)

            return elements

        return result

    def org_invitations(self, org):
        invitations = self.query('/orgs/{}/invitations'.format(org))

        return [
            login for login in (
                invitation.get('login') for invitation in invitations
            ) if login is not None
        ]

    def team_invitations(self, team_id):
        invitations = self.query('/teams/{}/invitations'.format(team_id))

        return [
            login for login in (
                invitation.get('login') for invitation in invitations
            ) if login is not None
        ]
