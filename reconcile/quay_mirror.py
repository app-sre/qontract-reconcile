import logging

from collections import defaultdict

from reconcile import queries
from utils.container import Image
from utils import gql
from utils import secret_reader
from utils import skopeo


_LOG = logging.getLogger(__name__)


class QuayMirror:

    QUAY_ORG_CATALOG_QUERY = """
    {
      quay_orgs: quay_orgs_v1 {
        name
        pushCredentials {
          path
          field
        }
      }
    }
    """

    QUAY_REPOS_QUERY = """
    {
      apps: apps_v1 {
        quayRepos {
          org {
            name
          }
          items {
            name
            mirror
          }
        }
      }
    }
    """

    def __init__(self, dry_run=False):
        self.gqlapi = gql.get_api()
        self.settings = queries.get_app_interface_settings()
        self.skopeo_cli = skopeo.Skopeo(dry_run)
        self.push_creds = self._get_push_creds()

    def run(self):
        sync_tasks = self.process_sync_tasks()
        for org, data in sync_tasks.items():
            for item in data:
                self.skopeo_cli.copy(src_image=item['mirror_url'],
                                     dst_image=item['image_url'],
                                     dest_creds=self.push_creds[org])

    def process_repos_query(self):
        result = self.gqlapi.query(self.QUAY_REPOS_QUERY)

        summary = defaultdict(list)

        for app in result['apps']:
            quay_repos = app.get('quayRepos')

            if quay_repos is None:
                continue

            for quay_repo in quay_repos:
                org = quay_repo['org']['name']
                for item in quay_repo['items']:
                    if item['mirror'] is None:
                        continue

                    summary[org].append({'name': item["name"],
                                         'mirror': item['mirror']})

        return summary

    def process_sync_tasks(self):
        summary = self.process_repos_query()

        sync_tasks = defaultdict(list)
        for org, data in summary.items():
            for item in data:
                image = Image(f'quay.io/{org}/{item["name"]}')
                image_mirror = Image(item['mirror'])

                for tag in image_mirror:
                    upstream = image_mirror[tag]
                    downstream = image[tag]
                    if upstream == downstream:
                        _LOG.debug('Image %s and mirror %s are in sync',
                                   downstream, upstream)
                        continue

                    _LOG.debug('Image %s and mirror %s are out of sync',
                               downstream, upstream)
                    sync_tasks[org].append({'mirror_url': str(upstream),
                                            'image_url': str(downstream)})
        return sync_tasks

    def _get_push_creds(self):
        result = self.gqlapi.query(self.QUAY_ORG_CATALOG_QUERY)

        creds = {}
        for org_data in result['quay_orgs']:
            push_secret = org_data['pushCredentials']
            if push_secret is None:
                continue

            raw_data = secret_reader.read_all(push_secret,
                                              settings=self.settings)
            org = org_data['name']
            creds[org] = f'{raw_data["user"]}:{raw_data["token"]}'

        return creds


def run(dry_run=False):
    quay_mirror = QuayMirror(dry_run)
    quay_mirror.run()
