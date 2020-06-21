import os
import yaml
import json
import logging

from github import Github
from sretoolbox.container import Image
from sretoolbox.utils import retry

import utils.threaded as threaded
import utils.secret_reader as secret_reader

from utils.oc import OC, StatusCodeError
from utils.openshift_resource import OpenshiftResource as OR
from utils.state import State
from reconcile.github_org import get_config


class SaasHerder():
    """Wrapper around SaaS deployment actions."""

    def __init__(self, saas_files,
                 thread_pool_size,
                 gitlab,
                 integration,
                 integration_version,
                 settings,
                 accounts=None):
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
        if accounts:
            self._initiate_state(accounts)

    def _validate_saas_files(self):
        self.valid = True
        saas_file_name_path_map = {}
        for saas_file in self.saas_files:
            saas_file_name = saas_file['name']
            saas_file_path = saas_file['path']
            saas_file_name_path_map.setdefault(saas_file_name, [])
            saas_file_name_path_map[saas_file_name].append(saas_file_path)

            saas_file_owners = [u['org_username']
                                for r in saas_file['roles']
                                for u in r['users']]
            if not saas_file_owners:
                msg = 'saas file {} has no owners: {}'
                logging.warning(msg.format(saas_file_name, saas_file_path))

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
                    if target.get('disable'):
                        logging.warning(
                            f"[{saas_file['name']}/{rt['name']}] target " +
                            f"{namespace['cluster']['name']}/" +
                            f"{namespace['name']} is disabled.")
                        continue
                    # managedResourceTypes is defined per saas_file
                    # add it to each namespace in the current saas_file
                    namespace['managedResourceTypes'] = managed_resource_types
                    namespaces.append(namespace)
        return namespaces

    def _initiate_state(self, accounts):
        self.state = State(
            integration=self.integration,
            accounts=accounts,
            settings=self.settings
        )

    @staticmethod
    def _collect_parameters(container):
        parameters = container.get('parameters') or {}
        if isinstance(parameters, str):
            parameters = json.loads(parameters)
        # adjust Python's True/False
        for k, v in parameters.items():
            if v is True:
                parameters[k] = 'true'
            elif v is False:
                parameters[k] = 'false'
            elif any([isinstance(v, t) for t in [dict, list, tuple]]):
                parameters[k] = json.dumps(v)
        return parameters

    @retry()
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
            f = project.files.get(file_path=path.lstrip('/'), ref=ref)
            html_url = os.path.join(url, 'blob', ref, path)
            return f.decode(), html_url

    def _get_commit_sha(self, options):
        url = options['url']
        ref = options['ref']
        github = options['github']
        hash_length = options.get('hash_length')
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

        if hash_length:
            return commit_sha[:hash_length]

        return commit_sha

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
        target_ref = target['ref']
        environment = target['namespace']['environment']
        environment_parameters = self._collect_parameters(environment)
        target_parameters = self._collect_parameters(target)

        consolidated_parameters = {}
        consolidated_parameters.update(environment_parameters)
        consolidated_parameters.update(parameters)
        consolidated_parameters.update(target_parameters)

        try:
            get_file_contents_options = {
                'url': url,
                'path': path,
                'ref': target_ref,
                'github': github
            }
            content, html_url = \
                self._get_file_contents(get_file_contents_options)
        except Exception as e:
            logging.error(
                f"[{url}/{path}:{target_ref}] " +
                f"error fetching template: {str(e)}")
            return None, None

        template = yaml.safe_load(content)
        if "IMAGE_TAG" not in consolidated_parameters:
            for template_parameter in template['parameters']:
                if template_parameter['name'] == 'IMAGE_TAG':
                    # add IMAGE_TAG only if it is required
                    get_commit_sha_options = {
                        'url': url,
                        'ref': target_ref,
                        'hash_length': hash_length,
                        'github': github
                    }
                    image_tag = self._get_commit_sha(get_commit_sha_options)
                    consolidated_parameters['IMAGE_TAG'] = image_tag
        oc = OC('server', 'token')
        try:
            resources = oc.process(template, consolidated_parameters)
        except StatusCodeError as e:
            resources = None
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] {html_url}: " +
                f"error processing template: {str(e)}")
        return resources, html_url

    def _collect_images(self, resource):
        images = set()
        # resources with pod templates
        try:
            template = resource["spec"]["template"]
            for c in template["spec"]["containers"]:
                images.add(c["image"])
        except KeyError:
            pass
        # init containers
        try:
            template = resource["spec"]["template"]
            for c in template["spec"]["initContainers"]:
                images.add(c["image"])
        except KeyError:
            pass
        # CronJob
        try:
            template = resource["spec"]["jobTemplate"]["spec"]["template"]
            for c in template["spec"]["containers"]:
                images.add(c["image"])
        except KeyError:
            pass
        # CatalogSource templates
        try:
            images.add(resource["spec"]["image"])
        except KeyError:
            pass

        return images

    def _check_images(self, options):
        saas_file_name = options['saas_file_name']
        resource_template_name = options['resource_template_name']
        html_url = options['html_url']
        resource = options['resource']
        image_auth = options['image_auth']
        image_patterns = options['image_patterns']
        error_prefix = \
            f"[{saas_file_name}/{resource_template_name}] {html_url}:"
        error = False
        images = self._collect_images(resource)

        for image in images:
            if image_patterns and \
                    not any(image.startswith(p) for p in image_patterns):
                error = True
                logging.error(
                    f"{error_prefix} Image is not in imagePatterns: {image}")
            try:
                valid = Image(image, **image_auth)
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
        """
        This function initiates a dict required for image authentication.
        This dict will be used as kwargs for sertoolbox's Image.
        The image authentication secret specified in the saas file must
        contain the 'user' and 'token' keys, and may optionally contain
        a 'url' key specifying the image registry url to be passed to check
        if an image should be checked using these credentials.
        The function returns the keys extracted from the secret in the
        structure expected by sretoolbox's Image:
        'user' --> 'username'
        'token' --> 'password'
        'url' --> 'auth_server' (optional)
        """
        auth = saas_file.get('authentication')
        if not auth:
            return {}
        auth_image_secret = auth.get('image')
        if not auth_image_secret:
            return {}

        creds = \
            secret_reader.read_all(auth_image_secret, settings=self.settings)
        required_keys = ['user', 'token']
        ok = all(k in creds.keys() for k in required_keys)
        if not ok:
            logging.warning(
                "the specified image authentication secret " +
                f"found in path {auth_image_secret['path']} " +
                f"does not contain all required keys: {required_keys}"
            )
            return {}

        image_auth = {
            'username': creds['user'],
            'password': creds['token']
        }
        url = creds.get('url')
        if url:
            image_auth['auth_server']: url

        return image_auth

    def populate_desired_state(self, ri):
        results = threaded.run(self.init_populate_desired_state_specs,
                               self.saas_files,
                               self.thread_pool_size)
        desired_state_specs = \
            [item for sublist in results for item in sublist]
        threaded.run(self.populate_desired_state_saas_file,
                     desired_state_specs,
                     self.thread_pool_size,
                     ri=ri)

    def init_populate_desired_state_specs(self, saas_file):
        specs = []
        saas_file_name = saas_file['name']
        github = self._initiate_github(saas_file)
        image_auth = self._initiate_image_auth(saas_file)
        managed_resource_types = saas_file['managedResourceTypes']
        image_patterns = saas_file['imagePatterns']
        resource_templates = saas_file['resourceTemplates']
        saas_file_parameters = self._collect_parameters(saas_file)
        # iterate over resource templates (multiple per saas_file)
        for rt in resource_templates:
            rt_name = rt['name']
            url = rt['url']
            path = rt['path']
            hash_length = rt.get('hash_length') or self.settings['hashLength']
            parameters = self._collect_parameters(rt)

            consolidated_parameters = {}
            consolidated_parameters.update(saas_file_parameters)
            consolidated_parameters.update(parameters)

            # iterate over targets (each target is a namespace)
            for target in rt['targets']:
                if target.get('disable'):
                    # a warning is logged during SaasHerder initiation
                    continue
                cluster, namespace = \
                    self._get_cluster_and_namespace(target)
                process_template_options = {
                    'saas_file_name': saas_file_name,
                    'resource_template_name': rt_name,
                    'url': url,
                    'path': path,
                    'hash_length': hash_length,
                    'target': target,
                    'parameters': consolidated_parameters,
                    'github': github
                }
                check_images_options_base = {
                    'saas_file_name': saas_file_name,
                    'resource_template_name': rt_name,
                    'image_auth': image_auth,
                    'image_patterns': image_patterns
                }
                spec = {
                    'saas_file_name': saas_file_name,
                    'cluster': cluster,
                    'namespace': namespace,
                    'managed_resource_types': managed_resource_types,
                    'process_template_options': process_template_options,
                    'check_images_options_base': check_images_options_base
                }
                specs.append(spec)

        return specs

    def populate_desired_state_saas_file(self, spec, ri):
        saas_file_name = spec['saas_file_name']
        cluster = spec['cluster']
        namespace = spec['namespace']
        managed_resource_types = spec['managed_resource_types']
        process_template_options = spec['process_template_options']
        check_images_options_base = spec['check_images_options_base']

        resources, html_url = \
            self._process_template(process_template_options)
        if resources is None:
            ri.register_error()
            return
        # add desired resources
        for resource in resources:
            resource_kind = resource['kind']
            if resource_kind not in managed_resource_types:
                continue
            # check images
            check_images_options = {
                'html_url': html_url,
                'resource': resource
            }
            check_images_options.update(check_images_options_base)
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

    def get_moving_commits_diff(self, dry_run):
        results = threaded.run(self.get_moving_commits_diff_saas_file,
                               self.saas_files,
                               self.thread_pool_size,
                               dry_run=dry_run)
        return [item for sublist in results for item in sublist]

    def get_moving_commits_diff_saas_file(self, saas_file, dry_run):
        saas_file_name = saas_file['name']
        instace_name = saas_file['instance']['name']
        github = self._initiate_github(saas_file)
        trigger_specs = []
        for rt in saas_file['resourceTemplates']:
            rt_name = rt['name']
            url = rt['url']
            for target in rt['targets']:
                # don't trigger if there is a linked upstream job
                if target.get('upstream'):
                    continue
                ref = target['ref']
                get_commit_sha_options = {
                    'url': url,
                    'ref': ref,
                    'github': github
                }
                desired_commit_sha = \
                    self._get_commit_sha(get_commit_sha_options)
                # don't trigger on refs which are commit shas
                if ref == desired_commit_sha:
                    continue
                namespace = target['namespace']
                cluster_name = namespace['cluster']['name']
                namespace_name = namespace['name']
                env_name = namespace['environment']['name']
                key = f"{saas_file_name}/{rt_name}/{cluster_name}/" + \
                    f"{namespace_name}/{env_name}/{ref}"
                current_commit_sha = self.state.get(key, None)
                # skip if there is no change in commit sha
                if current_commit_sha == desired_commit_sha:
                    continue
                # don't trigger if this is the first time
                # this target is being deployed.
                # that will be taken care of by
                # openshift-saas-deploy-trigger-configs
                if current_commit_sha is None:
                    # store the value to take over from now on
                    if not dry_run:
                        self.state.add(key, value=desired_commit_sha)
                    continue
                # we finally found something we want to trigger on!
                job_spec = {
                    'saas_file_name': saas_file_name,
                    'env_name': env_name,
                    'instance_name': instace_name,
                    'rt_name': rt_name,
                    'cluster_name': cluster_name,
                    'namespace_name': namespace_name,
                    'ref': ref,
                    'commit_sha': desired_commit_sha
                }
                trigger_specs.append(job_spec)

        return trigger_specs

    def update_moving_commit(self, job_spec):
        saas_file_name = job_spec['saas_file_name']
        env_name = job_spec['env_name']
        rt_name = job_spec['rt_name']
        cluster_name = job_spec['cluster_name']
        namespace_name = job_spec['namespace_name']
        ref = job_spec['ref']
        commit_sha = job_spec['commit_sha']
        key = f"{saas_file_name}/{rt_name}/{cluster_name}/" + \
            f"{namespace_name}/{env_name}/{ref}"
        self.state.add(key, value=commit_sha, force=True)

    def get_configs_diff(self):
        results = threaded.run(self.get_configs_diff_saas_file,
                               self.saas_files,
                               self.thread_pool_size)
        return [item for sublist in results for item in sublist]

    def get_configs_diff_saas_file(self, saas_file):
        saas_file_name = saas_file['name']
        saas_file_parameters = saas_file.get('parameters')
        instace_name = saas_file['instance']['name']
        trigger_specs = []
        for rt in saas_file['resourceTemplates']:
            rt_name = rt['name']
            rt_parameters = rt.get('parameters')
            for desired_target_config in rt['targets']:
                namespace = desired_target_config['namespace']
                cluster_name = namespace['cluster']['name']
                namespace_name = namespace['name']
                env_name = namespace['environment']['name']
                desired_target_config['namespace'] = \
                    self.sanitize_namespace(namespace)
                # add parent parameters to target config
                desired_target_config['saas_file_parameters'] = \
                    saas_file_parameters
                desired_target_config['rt_parameters'] = rt_parameters
                # get current target config from state
                key = f"{saas_file_name}/{rt_name}/{cluster_name}/" + \
                    f"{namespace_name}/{env_name}"
                current_target_config = self.state.get(key, None)
                # skip if there is no change in target configuration
                if current_target_config == desired_target_config:
                    continue
                job_spec = {
                    'saas_file_name': saas_file_name,
                    'env_name': env_name,
                    'instance_name': instace_name,
                    'rt_name': rt_name,
                    'cluster_name': cluster_name,
                    'namespace_name': namespace_name,
                    'target_config': desired_target_config
                }
                trigger_specs.append(job_spec)

        return trigger_specs

    @staticmethod
    def sanitize_namespace(namespace):
        """Only keep fields that should trigger a new job."""
        new_job_fields = {
            'namespace': ['name', 'cluster', 'app'],
            'cluster':  ['name', 'serverUrl'],
            'app': ['name']
        }
        namespace = {k: v for k, v in namespace.items()
                     if k in new_job_fields['namespace']}
        cluster = namespace['cluster']
        namespace['cluster'] = {k: v for k, v in cluster.items()
                                if k in new_job_fields['cluster']}
        app = namespace['app']
        namespace['app'] = {k: v for k, v in app.items()
                            if k in new_job_fields['app']}
        return namespace

    def update_config(self, job_spec):
        saas_file_name = job_spec['saas_file_name']
        env_name = job_spec['env_name']
        rt_name = job_spec['rt_name']
        cluster_name = job_spec['cluster_name']
        namespace_name = job_spec['namespace_name']
        target_config = job_spec['target_config']
        key = f"{saas_file_name}/{rt_name}/{cluster_name}/" + \
            f"{namespace_name}/{env_name}"
        self.state.add(key, value=target_config, force=True)
