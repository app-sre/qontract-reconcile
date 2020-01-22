import json
import logging
import re
import requests


from utils.retry import retry


_LOG = logging.getLogger(__name__)


class Image:
    """
    Represents a container image.

    :param url: The image url. E.g. docker.io/fedora
    :param tag_override: (optional) A specific tag to use instead of
                         the tag provided in the url or the default one
    :param username: (optional) The private registry username
    :param password: (optional) The private registry password
    """
    def __init__(self, url, tag_override=None, username=None, password=None):
        image_data = self._parse_image_url(url)
        self.scheme = image_data['scheme']
        self.registry = image_data['registry']
        self.repository = image_data['repository']
        self.image = image_data['image']

        if tag_override is None:
            self.tag = image_data['tag']
        else:
            self.tag = tag_override

        self.username = username
        self.password = password

        if self.registry == 'docker.io':
            self.registry_api = 'https://registry-1.docker.io'
        else:
            self.registry_api = f'https://{self.registry}'

        self._cache_tags = None

    @property
    def _tags(self):
        if self._cache_tags is None:
            try:
                self._cache_tags = self.get_tags()
            except requests.exceptions.HTTPError:
                self._cache_tags = []

        return self._cache_tags

    def __eq__(self, other):
        # Two instances are considered equal if both of their
        # manifests are accessible and first item of the 'history'
        # (the most recent) is the same.
        try:
            manifest = self.get_manifest()
            other_manifest = other.get_manifest()
        except requests.exceptions.HTTPError:
            return False

        if (manifest['history'][0]['v1Compatibility'] ==
                other_manifest['history'][0]['v1Compatibility']):
            return True

        return False

    def __getitem__(self, item):
        return Image(url=str(self), tag_override=str(item))

    def __iter__(self):
        for tag in self._tags:
            yield tag

    def __len__(self):
        return len(self._tags)

    def __contains__(self, item):
        return item in self._tags

    def __str__(self):
        return (f'{self.scheme}'
                f'{self.registry}'
                f'/{self.repository}'
                f'/{self.image}'
                f':{self.tag}')

    def __repr__(self):
        return f"{self.__class__.__name__}(url='{self}')"

    def __bool__(self):
        try:
            self.get_manifest()
            return True
        except requests.exceptions.HTTPError:
            return False

    def _raise_for_status(self, response, error_msg=None):
        """
        Includes the error messages, important for a registry
        """
        if response.status_code < 400:
            return None

        msg = ''
        if error_msg is not None:
            msg += f'{error_msg}: '

        msg += f'({response.status_code}) {response.reason}'
        content = json.loads(response.content)
        for error in content['errors']:
            msg += f', {error["message"]}'
        _LOG.error('[%s, %s]', str(self), msg)
        raise requests.exceptions.HTTPError(msg)

    def _get_auth(self, www_auth):
        """
        Generates the authorization string.
        """
        scheme = www_auth.pop("scheme")

        url = f'{www_auth.pop("realm")}?'
        for key, value in www_auth.items():
            url += f'{key}={value}&'

        if all([self.username is not None,
                self.password is not None]):
            auth = (self.username, self.password)
        else:
            auth = None

        response = requests.get(url, auth=auth)
        self._raise_for_status(response, error_msg=f'unable to retrieve auth '
                                                   f'token from {url}')

        data = response.json()["token"]
        return f'{scheme} {data}'

    @staticmethod
    def _parse_www_auth(value):
        www_authenticate = dict()
        www_authenticate['scheme'], params = value.split(' ', 1)

        # According to the RFC6750, the scheme MUST be followed by
        # one or more auth-param values.
        # This regex gets the extra auth-params and adds them to
        # the www_authenticate dictionary
        for item in re.finditer('(?P<key>[^ ,]+)="(?P<value>[^"]+)"', params):
            www_authenticate[item.group('key')] = item.group('value')

        return www_authenticate

    def _request_get(self, url):
        # Try first without 'Authorization' header
        headers = {
            'Accept': 'application/vnd.docker.distribution.manifest.v1+json'
        }
        response = requests.get(url, headers=headers)

        # Unauthorized, meaning we have to acquire a token
        if response.status_code == 401:
            auth_specs = response.headers.get('Www-Authenticate')
            if auth_specs is None:
                self._raise_for_status(response)
            www_auth = self._parse_www_auth(auth_specs)

            # Try again, this time with the Authorization header
            headers['Authorization'] = self._get_auth(www_auth)
            response = requests.get(url, headers=headers)

        self._raise_for_status(response)
        return response

    def get_tags(self):
        """
        Goes to the internet to retrieve all the image tags.
        """
        tags_per_page = 50
        url = f'{self.registry_api}/v2/{self.repository}/{self.image}' \
              f'/tags/list?n={tags_per_page}'
        response = self._request_get(url)

        tags = all_tags = response.json()['tags']

        # Tags are paginated
        while not len(tags) < tags_per_page:
            link_header = response.headers.get('Link')
            if link_header is None:
                break

            # Link is given between "<" and ">". Example:
            # '</v2/app-sre/aws-cli/tags/list?next_page=KkOw&n=50>; rel="next"'
            link = link_header.split('<', 1)[1].split('>', 1)[0]
            url = f'{self.registry_api}{link}'
            response = self._request_get(url)

            tags = response.json()['tags']
            all_tags.extend(tags)

        return all_tags

    @retry(exceptions=json.decoder.JSONDecodeError, max_attempts=3)
    def get_manifest(self):
        """
        Goes to the internet to retrieve the image manifest.
        """
        url = (f'{self.registry_api}/v2/{self.repository}/'
               f'{self.image}/manifests/{self.tag}')
        response = self._request_get(url)
        return response.json()

    @staticmethod
    def _parse_image_url(image_url):
        """
        Parser to split the image urls in its multiple components.

        Images are provided as URLs. E.g.:
            - docker.io/fedora
            - docker.io/fedora:31
            - docker://docker.io/user/fedora
            - docker://registry.example.com:5000/repo01/centos:latest

        Regardless the components provided in the URL, we have to make
        sure that we can properly split each of them and, for those
        not provided, assume safe defaults.

        Example:
            Considering the image URL "quay.io/app-sre/qontract-reconcile"

        The data structure returned will be:
            {'scheme': 'docker://',
             'registry': 'quay.io',
             'repository': 'app-sre',
             'image': 'qontract-reconcile',
             'tag': 'latest'}

        :param image_url: The image url to be parsed.
        :type image_url: str
        :return: A data structure with all the parsed components of
                 the image URL, already filled with the defaults for
                 those not provided.
        :rtype: dict
        """

        default_scheme = 'docker://'
        default_registry = 'docker.io'
        default_repo = 'library'
        default_tag = 'latest'

        parsed_image_url = re.search(
            r'(?P<scheme>\w+://)?'  # Scheme (optional) e.g. docker://
            r'(?P<registry>[\w\-]+[.][\w\-.]+)?'  # Registry domain (optional)
            r'(?(registry)(?P<port_colon>[:]))?'  # Port colon (optional)
            r'(?(port_colon)(?P<port>[0-9]+))'  # Port (optional)
            r'(?(registry)(?P<registry_slash>/))'  # Slash after domain:port
            r'(?P<repository>[\w\-]+)?'  # Repository (optional)
            r'(?(repository)(?P<repo_slash>/))'  # Slash, if repo is present
            r'(?P<image>[\w\-]+)'  # Image path (mandatory)
            r'(?P<tag_colon>:)?'  # Tag colon (optional)
            r'(?(tag_colon)(?P<tag>[\w\-.]+))'  # Tag (if tag colon is present)
            '$', image_url)

        if parsed_image_url is None:
            raise AttributeError(f'Not able to parse "{image_url}"')

        image_url_struct = parsed_image_url.groupdict()

        if image_url_struct.get('scheme') is None:
            image_url_struct['scheme'] = default_scheme

        if image_url_struct.get('registry') is None:
            image_url_struct['registry'] = default_registry

        port = image_url_struct.get('port')
        if port is not None:
            image_url_struct['registry'] += f':{port}'

        if image_url_struct.get('repository') is None:
            image_url_struct['repository'] = default_repo

        if image_url_struct.get('tag') is None:
            image_url_struct['tag'] = default_tag

        return image_url_struct
