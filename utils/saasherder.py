import os
import yaml
import json
import logging

from github import Github
from sretoolbox.container import Image

import utils.threaded as threaded
import utils.secret_reader as secret_reader

from utils.oc import OC, StatusCodeError
from utils.openshift_resource import OpenshiftResource as OR
from reconcile.github_org import get_config


class SaasHerder():
    """Wrapper around SaaS deployment actions."""

    def __init__(self, saas_files,
                 thread_pool_size,
                 gitlab,
                 integration,
                 integration_version,
                 settings):
        self.saas_files = saas_files
        self._validate_saas_files()
        if not self.valid:
            return
        self.thread_pool_size = thread_pool_size
        self.gitlab = gitlab
        self.integration = integration
        self.integration_version = integration_version
        self.settings = settings
        self.namespaces = self._collect_namespaces()

    def _validate_saas_files(self):
        self.valid = True
        saas_file_name_path_map = {}
        for saas_file in self.saas_files:
            saas_file_name = saas_file['name']
            saas_file_path = saas_file['path']
            saas_file_name_path_map.setdefault(saas_file_name, [])
            saas_file_name_path_map[saas_file_name].append(saas_file_path)

        duplicates = {saas_file_name: saas_file_paths
                      for saas_file_name, saas_file_paths
                      in saas_file_name_path_map.items()
                      if len(saas_file_paths) > 1}
        if duplicates:
            self.valid = False
            msg = 'saas file name {} is not unique: {}'
            for saas_file_name, saas_file_paths in duplicates.items():
                logging.error(msg.format(saas_file_name, saas_file_paths))

    def _collect_namespaces(self):
        # namespaces may appear more then once in the result
        namespaces = []
        for saas_file in self.saas_files:
            managed_resource_types = saas_file['managedResourceTypes']
            resource_templates = saas_file['resourceTemplates']
            for rt in resource_templates:
                targets = rt['targets']
                for target in targets:
                    namespace = target['namespace']
                    # managedResourceTypes is defined per saas_file
                    # add it to each namespace in the current saas_file
                    namespace['managedResourceTypes'] = managed_resource_types
                    namespaces.append(namespace)
        return namespaces

    @staticmethod
    def _collect_parameters(container):
        parameters = container.get('parameters') or {}
        if isinstance(parameters, str):
            parameters = json.loads(parameters)
        # adjust Python's True/False
        for k, v in parameters.items():
            if v is True:
                parameters[k] = 'true'
            if v is False:
                parameters[k] = 'false'
        return parameters

    def _get_file_contents(self, options):
        url = options['url']
        path = options['path']
        ref = options['ref']
        github = options['github']
        if 'github' in url:
            repo_name = url.rstrip("/").replace('https://github.com/', '')
            repo = github.get_repo(repo_name)
            f = repo.get_contents(path, ref)
            return f.decoded_content, f.html_url
        elif 'gitlab' in url:
            if not self.gitlab:
                raise Exception('gitlab is not initialized')
            project = self.gitlab.get_project(url)
            f = project.files.get(file_path=path, ref=ref)
            html_url = os.path.join(url, 'blob', ref, path)
            return f.decode(), html_url

    def _get_commit_sha(self, options):
        url = options['url']
        ref = options['ref']
        hash_length = options['hash_length']
        github = options['github']
        commit_sha = ''
        if 'github' in url:
            repo_name = url.rstrip("/").replace('https://github.com/', '')
            repo = github.get_repo(repo_name)
            commit = repo.get_commit(sha=ref)
            commit_sha = commit.sha
        elif 'gitlab' in url:
            if not self.gitlab:
                raise Exception('gitlab is not initialized')
            project = self.gitlab.get_project(url)
            commits = project.commits.list(ref_name=ref)
            commit_sha = commits[0].id
        return commit_sha[:hash_length]

    @staticmethod
    def _get_cluster_and_namespace(target):
        cluster = target['namespace']['cluster']['name']
        namespace = target['namespace']['name']
        return cluster, namespace

    def _process_template(self, options):
        saas_file_name = options['saas_file_name']
        resource_template_name = options['resource_template_name']
        url = options['url']
        path = options['path']
        hash_length = options['hash_length']
        target = options['target']
        parameters = options['parameters']
        github = options['github']
        target_hash = target['hash']
        environment = target['namespace']['environment']
        environment_parameters = self._collect_parameters(environment)
        target_parameters = self._collect_parameters(target)
        target_parameters.update(environment_parameters)
        target_parameters.update(parameters)

        try:
            get_file_contents_options = {
                'url': url,
                'path': path,
                'ref': target_hash,
                'github': github
            }
            content, html_url = \
                self._get_file_contents(get_file_contents_options)
        except Exception as e:
            logging.error(
                f"[{url}/{path}:{target_hash}] " +
                f"error fetching template: {str(e)}")
            return None, None

        template = yaml.safe_load(content)
        if "IMAGE_TAG" not in target_parameters:
            for template_parameter in template['parameters']:
                if template_parameter['name'] == 'IMAGE_TAG':
                    # add IMAGE_TAG only if it is required
                    get_commit_sha_options = {
                        'url': url,
                        'ref': target_hash,
                        'hash_length': hash_length,
                        'github': github
                    }
                    image_tag = self._get_commit_sha(get_commit_sha_options)
                    target_parameters['IMAGE_TAG'] = image_tag
        oc = OC('server', 'token')
        try:
            resources = oc.process(template, target_parameters)
        except StatusCodeError as e:
            resources = None
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] {html_url}: " +
                f"error processing template: {str(e)}")
        return resources, html_url

    def _collect_images(self, resource):
        images = set()
        try:
            for c in resource["spec"]["template"]["spec"]["containers"]:
                images.add(c["image"])
        except KeyError:
            pass

        return images

    def _check_images(self, options):
        saas_file_name = options['saas_file_name']
        resource_template_name = options['resource_template_name']
        html_url = options['html_url']
        resource = options['resource']
        image_auth = options['image_auth']
        error_prefix = \
            f"[{saas_file_name}/{resource_template_name}] {html_url}:"
        error = False
        images = self._collect_images(resource)
        if image_auth:
            username = image_auth['user']
            password = image_auth['token']
        else:
            username = None
            password = None
        for image in images:
            try:
                valid = Image(image, username=username, password=password)
                if not valid:
                    error = True
                    logging.error(
                        f"{error_prefix} Image does not exist: {image}")
                    continue
            except Exception:
                error = True
                logging.error(f"{error_prefix} Image is invalid: {image}")
                continue
        return error

    def _initiate_github(self, saas_file):
        auth = saas_file.get('authentication') or {}
        auth_code = auth.get('code') or {}
        if auth_code:
            token = secret_reader.read(auth_code, settings=self.settings)
        else:
            # use the app-sre token by default
            default_org_name = 'app-sre'
            config = get_config(desired_org_name=default_org_name)
            token = config['github'][default_org_name]['token']

        base_url = os.environ.get('GITHUB_API', 'https://api.github.com')
        return Github(token, base_url=base_url)

    def _initiate_image_auth(self, saas_file):
        auth = saas_file.get('authentication') or {}
        auth_image = auth.get('image') or {}
        if auth_image:
            creds = \
                secret_reader.read_all(auth_image, settings=self.settings)
        else:
            creds = None
        return creds

    def populate_desired_state(self, ri):
        threaded.run(self.populate_desired_state_saas_file,
                     self.saas_files,
                     self.thread_pool_size,
                     ri=ri)

    def populate_desired_state_saas_file(self, saas_file, ri):
        saas_file_name = saas_file['name']
        logging.debug(f"populating desired state for {saas_file_name}")
        github = self._initiate_github(saas_file)
        image_auth = self._initiate_image_auth(saas_file)
        managed_resource_types = saas_file['managedResourceTypes']
        resource_templates = saas_file['resourceTemplates']
        saas_file_parameters = self._collect_parameters(saas_file)
        # iterate over resource templates (multiple per saas_file)
        for rt in resource_templates:
            rt_name = rt['name']
            url = rt['url']
            path = rt['path']
            hash_length = rt['hash_length']
            parameters = self._collect_parameters(rt)
            parameters.update(saas_file_parameters)
            # iterate over targets (each target is a namespace)
            for target in rt['targets']:
                cluster, namespace = \
                    self._get_cluster_and_namespace(target)
                process_template_options = {
                    'saas_file_name': saas_file_name,
                    'resource_template_name': rt_name,
                    'url': url,
                    'path': path,
                    'hash_length': hash_length,
                    'target': target,
                    'parameters': parameters,
                    'github': github
                }
                resources, html_url = \
                    self._process_template(process_template_options)
                if resources is None:
                    ri.register_error()
                    continue
                # add desired resources
                for resource in resources:
                    resource_kind = resource['kind']
                    if resource_kind not in managed_resource_types:
                        continue
                    # check images
                    check_images_options = {
                        'saas_file_name': saas_file_name,
                        'resource_template_name': rt_name,
                        'html_url': html_url,
                        'resource': resource,
                        'image_auth': image_auth
                    }
                    image_error = self._check_images(check_images_options)
                    if image_error:
                        ri.register_error()
                        continue
                    resource_name = resource['metadata']['name']
                    oc_resource = OR(
                        resource,
                        self.integration,
                        self.integration_version,
                        caller_name=saas_file_name,
                        error_details=html_url)
                    ri.add_desired(
                        cluster,
                        namespace,
                        resource_kind,
                        resource_name,
                        oc_resource
                    )
