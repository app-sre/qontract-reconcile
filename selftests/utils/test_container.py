import pytest

from utils import container

PARSER_DATA = [
    ('memcached',
     {'scheme': 'docker://',
      'registry': 'docker.io',
      'repository': 'library',
      'image': 'memcached',
      'tag': 'latest'}),
    ('docker.io/memcached',
     {'scheme': 'docker://',
      'registry': 'docker.io',
      'repository': 'library',
      'image': 'memcached',
      'tag': 'latest'}),
    ('library/memcached',
     {'scheme': 'docker://',
      'registry': 'docker.io',
      'repository': 'library',
      'image': 'memcached',
      'tag': 'latest'}),
    ('quay.io/app-sre/qontract-reconcile',
     {'scheme': 'docker://',
      'registry': 'quay.io',
      'repository': 'app-sre',
      'image': 'qontract-reconcile',
      'tag': 'latest'}),
    ('docker://docker.io/fedora:28',
     {'scheme': 'docker://',
      'repository': 'library',
      'registry': 'docker.io',
      'image': 'fedora',
      'tag': '28'}),
    ('example-local.com:5000/my-repo/my-image:build',
     {'scheme': 'docker://',
      'registry': 'example-local.com:5000',
      'port': '5000',
      'repository': 'my-repo',
      'image': 'my-image',
      'tag': 'build'}),
    ('docker://docker.io/tnozicka/openshift-acme:v0.8.0-pre-alpha',
     {'scheme': 'docker://',
      'registry': 'docker.io',
      'repository': 'tnozicka',
      'image': 'openshift-acme',
      'tag': 'v0.8.0-pre-alpha'})
]

STR_DATA = [
    ('memcached',
     'docker://docker.io/library/memcached:latest'),
    ('docker.io/fedora',
     'docker://docker.io/library/fedora:latest'),
    ('docker://docker.io/app-sre/fedora',
     'docker://docker.io/app-sre/fedora:latest'),
    ('docker.io:8080/app-sre/fedora:30',
     'docker://docker.io:8080/app-sre/fedora:30'),
    ('quay.io/app-sre/qontract-reconcile:build',
     'docker://quay.io/app-sre/qontract-reconcile:build')
]


TAG_OVERRIDE_DATA = [
    ('memcached:20',
     'latest',
     'docker://docker.io/library/memcached:latest'),
    ('docker.io/fedora:31',
     '30',
     'docker://docker.io/library/fedora:30'),
    ('docker://docker.io/app-sre/fedora',
     '25',
     'docker://docker.io/app-sre/fedora:25'),
    ('docker.io:443/app-sre/fedora:30',
     '31',
     'docker://docker.io:443/app-sre/fedora:31'),
    ('quay.io/app-sre/qontract-reconcile:build',
     'latest',
     'docker://quay.io/app-sre/qontract-reconcile:latest')
]


class TestContainer:

    @pytest.mark.parametrize('image, expected_struct', PARSER_DATA)
    def test_parser(self, image, expected_struct):
        image = container.Image(image)
        assert image.scheme == expected_struct['scheme']
        assert image.registry == expected_struct['registry']
        assert image.repository == expected_struct['repository']
        assert image.image == expected_struct['image']
        assert image.tag == expected_struct['tag']

    @pytest.mark.parametrize('image, expected_image_url', STR_DATA)
    def test_str(self, image, expected_image_url):
        image = container.Image(image)
        assert str(image) == expected_image_url

    @pytest.mark.parametrize('image, tag, expected_image_url',
                             TAG_OVERRIDE_DATA)
    def test_tag_override(self, image, tag, expected_image_url):
        image = container.Image(image, tag)
        assert str(image) == expected_image_url
