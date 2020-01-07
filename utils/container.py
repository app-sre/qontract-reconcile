import logging
import re
import requests


_LOG = logging.getLogger(__name__)


class Image:
    """
    Represents a container image.

    :param url: The image url. E.g. docker.io/fedora
    :param tag_override: (optional) A specific tag to use instead of
                         the tag provided in the url or the default one
    """
    def __init__(self, url, tag_override=None):
        image_data = self._parse_image_url(url)
        self.scheme = image_data['scheme']
        self.registry = image_data['registry']
        self.repository = image_data['repository']
        self.image = image_data['image']

        if tag_override is None:
            self.tag = image_data['tag']
        else:
            self.tag = tag_override

        if self.registry == 'docker.io':
            self.registry_config = {
                'auth_api': 'https://auth.docker.io/token',
                'registry_api': 'https://registry-1.docker.io',
                'service': 'registry.docker.io'
            }
        else:
            # Works for quay.io. Not sure about private registry.
            self.registry_config = {
                'auth_api': f'https://{self.registry}/v2/auth',
                'registry_api': f'https://{self.registry}',
                'service': self.registry.split(':')[0]  # Removing the port
            }

        self._tags = None

    @property
    def tags(self):
        if self._tags is None:
            self._tags = self._get_all_tags()
        return self._tags

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
        for tag in self.tags:
            yield tag

    def __len__(self):
        return len(self.tags)

    def __contains__(self, item):
        return item in self.tags

    def __str__(self):
        return (f'{self.scheme}'
                f'{self.registry}'
                f'/{self.repository}'
                f'/{self.image}'
                f':{self.tag}')

    def __repr__(self):
        return f'{self.__class__.__name__}(url={self})'

    def _get_auth_token(self):
        """
        Goes to the internet to retrieve the auth token.
        """
        auth_url = self.registry_config['auth_api']
        service = self.registry_config['service']
        url = (f'{auth_url}?service={service}&'
               f'scope=repository:{self.repository}/{self.image}:pull')
        response = requests.get(url)
        response.raise_for_status()
        return response.json()['token']

    def _get_all_tags(self):
        """
        Goes to the internet to retrieve all the image tags.
        """
        all_tags = []
        registry_url = self.registry_config['registry_api']

        tags_per_page = 50

        url = f'{registry_url}/v2/{self.repository}/{self.image}' \
              f'/tags/list?n={tags_per_page}'
        headers = {
            'Authorization': f'Bearer {self._get_auth_token()}',
            'Accept': 'application/vnd.docker.distribution.manifest.v1+json'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        tags = response.json()['tags']

        all_tags = tags

        # Tags are paginated
        while not len(tags) < tags_per_page:
            link_header = response.headers.get('Link')
            if link_header is None:
                break

            # Link is given between "<" and ">". Example:
            # '<v2/app-sre/aws-cli/tags/list?next_page=KkOw&n=50>; rel="next"'
            link = link_header.split('<', 1)[1].split('>', 1)[0]

            url = f'{registry_url}/{link}'
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            tags = response.json()['tags']

            all_tags.extend(tags)

        return all_tags

    def get_manifest(self):
        """
        Goes to the internet to retrieve the image manifest.
        """
        registry_url = self.registry_config['registry_api']
        url = (f'{registry_url}/v2/{self.repository}/'
               f'{self.image}/manifests/{self.tag}')
        headers = {
            'Authorization': f'Bearer {self._get_auth_token()}',
            'Accept': 'application/vnd.docker.distribution.manifest.v1+json'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
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
