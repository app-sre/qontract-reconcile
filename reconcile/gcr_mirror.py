import base64
import logging
import os
import tempfile
import time

from collections import defaultdict

from sretoolbox.container import Image
from sretoolbox.container.image import ImageComparisonError
from sretoolbox.container import Skopeo
from sretoolbox.container.skopeo import SkopeoCmdError

from reconcile import queries
from utils import gql
from utils import secret_reader


_LOG = logging.getLogger(__name__)

QONTRACT_INTEGRATION = 'gcr-mirror'


class QuayMirror:

    GCR_PROJECT_CATALOG_QUERY = """
    {
      projects: gcp_projects_v1 {
        name
        pushCredentials {
          path
          field
        }
      }
    }
    """

    GCR_REPOS_QUERY = """
    {
      apps: apps_v1 {
        gcrRepos {
          project {
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
        self.dry_run = dry_run
        self.gqlapi = gql.get_api()
        self.settings = queries.get_app_interface_settings()
        self.skopeo_cli = Skopeo(dry_run)
        self.push_creds = self._get_push_creds()

    def run(self):
        sync_tasks = self.process_sync_tasks()
        for org, data in sync_tasks.items():
            for item in data:
                try:
                    self.skopeo_cli.copy(src_image=item['mirror_url'],
                                         dst_image=item['image_url'],
                                         dest_creds=self.push_creds[org])
                except SkopeoCmdError as details:
                    _LOG.error('[%s]', details)

    def process_repos_query(self):
        result = self.gqlapi.query(self.GCR_REPOS_QUERY)

        summary = defaultdict(list)

        for app in result['apps']:
            gcr_repos = app.get('gcrRepos')

            if gcr_repos is None:
                continue

            for gcr_repo in gcr_repos:
                project = gcr_repo['project']['name']
                server_url = gcr_repo['project'].get('serverUrl') or 'gcr.io'
                for item in gcr_repo['items']:
                    if item['mirror'] is None:
                        continue

                    summary[project].append({'name': item["name"],
                                             'mirror': item['mirror'],
                                             'server_url': server_url})

        return summary

    def process_sync_tasks(self):
        eight_hours = 28800  # 60 * 60 * 8
        is_deep_sync = self._is_deep_sync(interval=eight_hours)

        summary = self.process_repos_query()

        sync_tasks = defaultdict(list)
        for org, data in summary.items():
            for item in data:
                image = Image(f'{item["server_url"]}/{org}/{item["name"]}')
                image_mirror = Image(item['mirror'])

                for tag in image_mirror:
                    upstream = image_mirror[tag]
                    downstream = image[tag]
                    if tag not in image:
                        _LOG.debug('Image %s and mirror %s are out off sync',
                                   downstream, upstream)
                        sync_tasks[org].append({'mirror_url': str(upstream),
                                                'image_url': str(downstream)})
                        continue

                    # Deep (slow) check only in non dry-run mode
                    if self.dry_run:
                        _LOG.debug('Image %s and mirror %s are in sync',
                                   downstream, upstream)
                        continue

                    # Deep (slow) check only from time to time
                    if not is_deep_sync:
                        _LOG.debug('Image %s and mirror %s are in sync',
                                   downstream, upstream)
                        continue

                    try:
                        if downstream == upstream:
                            _LOG.debug('Image %s and mirror %s are in sync',
                                       downstream, upstream)
                            continue
                    except ImageComparisonError as details:
                        _LOG.error('[%s]', details)
                        continue

                    _LOG.debug('Image %s and mirror %s are out of sync',
                               downstream, upstream)
                    sync_tasks[org].append({'mirror_url': str(upstream),
                                            'image_url': str(downstream)})

        return sync_tasks

    def _is_deep_sync(self, interval):
        control_file_name = 'qontract-reconcile-gcr-mirror.timestamp'
        control_file_path = os.path.join(tempfile.gettempdir(),
                                         control_file_name)
        try:
            with open(control_file_path, 'r') as file_obj:
                last_deep_sync = float(file_obj.read())
        except FileNotFoundError:
            self._record_timestamp(control_file_path)
            return True

        next_deep_sync = last_deep_sync + interval
        if time.time() >= next_deep_sync:
            self._record_timestamp(control_file_path)
            return True

        return False

    @staticmethod
    def _record_timestamp(path):
        with open(path, 'w') as file_object:
            file_object.write(str(time.time()))

    def _get_push_creds(self):
        result = self.gqlapi.query(self.GCR_PROJECT_CATALOG_QUERY)

        creds = {}
        for project_data in result['projects']:
            push_secret = project_data['pushCredentials']
            if push_secret is None:
                continue

            raw_data = secret_reader.read_all(push_secret,
                                              settings=self.settings)
            project = project_data['name']
            token = base64.b64decode(raw_data["token"]).decode()
            creds[project] = f'{raw_data["user"]}:{token}'
        return creds


def run(dry_run):
    gcr_mirror = QuayMirror(dry_run)
    gcr_mirror.run()
