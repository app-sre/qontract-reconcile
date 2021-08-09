import base64
import json
import logging
import os
import itertools
import yaml

from gitlab.exceptions import GitlabError
from github import Github, GithubException
from requests import exceptions as rqexc
from sretoolbox.container import Image
from sretoolbox.utils import retry

import reconcile.utils.threaded as threaded

from reconcile.github_org import get_config
from reconcile.utils.mr.auto_promoter import AutoPromoter
from reconcile.utils.oc import OC, StatusCodeError
from reconcile.utils.openshift_resource import (OpenshiftResource as OR,
                                                ResourceKeyExistsError)
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.state import State


class Providers:
    JENKINS = 'jenkins'
    TEKTON = 'tekton'


class TriggerTypes:
    CONFIGS = 0
    MOVING_COMMITS = 1
    UPSTREAM_JOBS = 2


UNIQUE_SAAS_FILE_ENV_COMBO_LEN = 50


class SaasHerder():
    """Wrapper around SaaS deployment actions."""

    def __init__(self, saas_files,
                 thread_pool_size,
                 gitlab,
                 integration,
                 integration_version,
                 settings,
                 jenkins_map=None,
                 accounts=None,
                 validate=False):
        self.saas_files = saas_files
        if validate:
            self._validate_saas_files()
            if not self.valid:
                return
        self.thread_pool_size = thread_pool_size
        self.gitlab = gitlab
        self.integration = integration
        self.integration_version = integration_version
        self.settings = settings
        self.secret_reader = SecretReader(settings=settings)
        self.namespaces = self._collect_namespaces()
        self.jenkins_map = jenkins_map
        # each namespace is in fact a target,
        # so we can use it to calculate.
        divisor = len(self.namespaces) or 1
        self.available_thread_pool_size = \
            threaded.estimate_available_thread_pool_size(
                self.thread_pool_size,
                divisor)
        # if called by a single saas file,it may
        # specify that it manages resources exclusively.
        self.take_over = self._get_saas_file_feature_enabled('takeover')
        self.compare = \
            self._get_saas_file_feature_enabled('compare', default=True)
        self.publish_job_logs = \
            self._get_saas_file_feature_enabled('publishJobLogs')
        self.cluster_admin = \
            self._get_saas_file_feature_enabled('clusterAdmin')
        if accounts:
            self._initiate_state(accounts)

    def _get_saas_file_feature_enabled(self, name, default=None):
        """Returns a bool indicating if a feature is enabled in a saas file,
        or a supplied default. Returns False if there are multiple
        saas files in the process.
        All features using this method should assume a single saas file.
        """
        sf_attribute = len(self.saas_files) == 1 and \
            self.saas_files[0].get(name)
        if sf_attribute is None and default is not None:
            return default
        return sf_attribute

    def _validate_saas_files(self):
        self.valid = True
        saas_file_name_path_map = {}
        saas_file_promotion_publish_channels = []
        self.tkn_unique_pipelineruns = {}
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
                logging.error(msg.format(saas_file_name, saas_file_path))
                self.valid = False

            for resource_template in saas_file['resourceTemplates']:
                resource_template_name = resource_template['name']
                for target in resource_template['targets']:
                    target_namespace = target['namespace']
                    namespace_name = target_namespace['name']
                    cluster_name = target_namespace['cluster']['name']
                    environment = target_namespace['environment']
                    environment_name = environment['name']
                    # unique saas file and env name combination
                    self._check_saas_file_env_combo_unique(
                        saas_file_name,
                        environment_name
                    )
                    # promotion publish channels
                    promotion = target.get('promotion')
                    if promotion:
                        publish = promotion.get('publish')
                        if publish:
                            saas_file_promotion_publish_channels.extend(
                                publish)
                    # validate target parameters
                    target_parameters = target['parameters']
                    if not target_parameters:
                        continue
                    target_parameters = json.loads(target_parameters)
                    environment_parameters = environment['parameters']
                    if not environment_parameters:
                        continue
                    environment_parameters = \
                        json.loads(environment_parameters)
                    msg = \
                        f'[{saas_file_name}/{resource_template_name}] ' + \
                        'parameter found in target ' + \
                        f'{cluster_name}/{namespace_name} ' + \
                        f'should be reused from env {environment_name}'
                    for t_key, t_value in target_parameters.items():
                        if not isinstance(t_value, str):
                            continue
                        # Check for recursivity. Ex: PARAM: "foo.${PARAM}"
                        replace_pattern = '${' + t_key + '}'
                        if replace_pattern in t_value:
                            logging.error(
                                f'[{saas_file_name}/{resource_template_name}] '
                                f'recursivity in parameter name and value '
                                f'found: {t_key}: "{t_value}" - this will '
                                f'likely not work as expected. Please consider'
                                f' changing the parameter name')
                            self.valid = False
                        for e_key, e_value in environment_parameters.items():
                            if not isinstance(e_value, str):
                                continue
                            if '.' not in e_value:
                                continue
                            if e_value not in t_value:
                                continue
                            if t_key == e_key and t_value == e_value:
                                details = \
                                    f'consider removing {t_key}'
                            else:
                                replacement = t_value.replace(
                                    e_value,
                                    '${' + e_key + '}'
                                )
                                details = \
                                    f'target: \"{t_key}: {t_value}\". ' + \
                                    f'env: \"{e_key}: {e_value}\". ' + \
                                    f'consider \"{t_key}: {replacement}\"'
                            logging.error(f'{msg}: {details}')
                            self.valid = False

        # saas file name duplicates
        duplicates = {saas_file_name: saas_file_paths
                      for saas_file_name, saas_file_paths
                      in saas_file_name_path_map.items()
                      if len(saas_file_paths) > 1}
        if duplicates:
            self.valid = False
            msg = 'saas file name {} is not unique: {}'
            for saas_file_name, saas_file_paths in duplicates.items():
                logging.error(msg.format(saas_file_name, saas_file_paths))

        # promotion publish channel duplicates
        duplicates = [p for p in saas_file_promotion_publish_channels
                      if saas_file_promotion_publish_channels.count(p) > 1]
        if duplicates:
            self.valid = False
            msg = 'saas file promotion publish channel is not unique: {}'
            for duplicate in duplicates:
                logging.error(msg.format(duplicate))

    def _check_saas_file_env_combo_unique(self, saas_file_name, env_name):
        # max tekton pipelinerun name length can be 63.
        # leaving 12 for the timestamp leaves us with 51
        # to create a unique pipelinerun name
        tkn_long_name = f"{saas_file_name}-{env_name}"
        tkn_name = tkn_long_name[:UNIQUE_SAAS_FILE_ENV_COMBO_LEN]
        if tkn_name in self.tkn_unique_pipelineruns.keys() and \
                self.tkn_unique_pipelineruns[tkn_name] != tkn_long_name:
            logging.error(
                f'[{saas_file_name}/{env_name}] '
                'saas file and env name combination must be '
                f'unique in first {UNIQUE_SAAS_FILE_ENV_COMBO_LEN} chars. '
                f'found not unique value: {tkn_name} '
                f'from this long name: {tkn_long_name}')
            self.valid = False
        else:
            self.tkn_unique_pipelineruns[tkn_name] = tkn_long_name

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
                        logging.debug(
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

    @staticmethod
    def _get_file_contents_github(repo, path, commit_sha):
        try:
            f = repo.get_contents(path, commit_sha)
            return f.decoded_content
        except GithubException as e:
            # slightly copied with love from
            # https://github.com/PyGithub/PyGithub/issues/661
            errors = e.data['errors']
            # example errors dict that we are looking for
            # {
            #    'message': '<text>',
            #    'errors': [{
            #                  'resource': 'Blob',
            #                  'field': 'data',
            #                  'code': 'too_large'
            #               }],
            #    'documentation_url': '<url>'
            # }
            for error in errors:
                if error['code'] == 'too_large':
                    # get large files
                    tree = repo.get_git_tree(
                        commit_sha, recursive='/' in path).tree
                    for x in tree:
                        if x.path != path.lstrip('/'):
                            continue
                        blob = repo.get_git_blob(x.sha)
                        return base64.b64decode(blob.content).decode("utf8")

            raise e

    @retry()
    def _get_file_contents(self, options):
        url = options['url']
        path = options['path']
        ref = options['ref']
        github = options['github']
        html_url = f"{url}/blob/{ref}{path}"
        commit_sha = self._get_commit_sha(options)
        content = None
        if 'github' in url:
            repo_name = url.rstrip("/").replace('https://github.com/', '')
            repo = github.get_repo(repo_name)
            content = self._get_file_contents_github(repo, path, commit_sha)
        elif 'gitlab' in url:
            if not self.gitlab:
                raise Exception('gitlab is not initialized')
            project = self.gitlab.get_project(url)
            f = project.files.get(file_path=path.lstrip('/'), ref=commit_sha)
            content = f.decode()

        return yaml.safe_load(content), html_url, commit_sha

    @retry()
    def _get_directory_contents(self, options):
        url = options['url']
        path = options['path']
        ref = options['ref']
        github = options['github']
        html_url = f"{url}/tree/{ref}{path}"
        commit_sha = self._get_commit_sha(options)
        resources = []
        if 'github' in url:
            repo_name = url.rstrip("/").replace('https://github.com/', '')
            repo = github.get_repo(repo_name)
            for f in repo.get_contents(path, commit_sha):
                file_path = os.path.join(path, f.name)
                file_contents_decoded = \
                    self._get_file_contents_github(
                        repo, file_path, commit_sha)
                resource = yaml.safe_load(file_contents_decoded)
                resources.append(resource)
        elif 'gitlab' in url:
            if not self.gitlab:
                raise Exception('gitlab is not initialized')
            project = self.gitlab.get_project(url)
            for f in project.repository_tree(path=path.lstrip('/'),
                                             ref=commit_sha, all=True):
                file_contents = \
                    project.files.get(file_path=f['path'], ref=commit_sha)
                resource = yaml.safe_load(file_contents.decode())
                resources.append(resource)

        return resources, html_url, commit_sha

    @retry()
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

    @staticmethod
    def _additional_resource_process(resources, html_url):
        for resource in resources:
            # add a definition annotation to each PrometheusRule rule
            if resource['kind'] == 'PrometheusRule':
                try:
                    groups = resource['spec']['groups']
                    for group in groups:
                        rules = group['rules']
                        for rule in rules:
                            annotations = rule.get('annotations')
                            if not annotations:
                                continue
                            rule['annotations']['html_url'] = html_url
                except Exception:
                    logging.warning(
                        'could not add html_url annotation to' +
                        resource['name'])

    @staticmethod
    def _parameter_value_needed(
            parameter_name, consolidated_parameters, template):
        """Is a parameter named in the template but unspecified?

        NOTE: This is currently "parameter *named* and absent" -- i.e. we
        don't care about `required: true`. This is for backward compatibility.

        :param parameter_name: The name (key) of the parameter.
        :param consolidated_parameters: Dict of parameters already specified/
                calculated.
        :param template: The template file in dict form.
        :return bool: True if the named parameter is named in the template,
                but not already present in consolidated_parameters.
        """
        if parameter_name in consolidated_parameters:
            return False
        for template_parameter in template.get("parameters", {}):
            if template_parameter["name"] == parameter_name:
                return True
        return False

    def _process_template(self, options):
        saas_file_name = options['saas_file_name']
        resource_template_name = options['resource_template_name']
        image_auth = options['image_auth']
        url = options['url']
        path = options['path']
        provider = options['provider']
        target = options['target']
        github = options['github']
        target_ref = target['ref']
        target_promotion = target.get('promotion') or {}

        resources = None
        html_url = None
        commit_sha = None

        if provider == 'openshift-template':
            hash_length = options['hash_length']
            parameters = options['parameters']
            environment = target['namespace']['environment']
            environment_parameters = self._collect_parameters(environment)
            target_parameters = self._collect_parameters(target)

            consolidated_parameters = {}
            consolidated_parameters.update(environment_parameters)
            consolidated_parameters.update(parameters)
            consolidated_parameters.update(target_parameters)

            for replace_key, replace_value in consolidated_parameters.items():
                if not isinstance(replace_value, str):
                    continue
                replace_pattern = '${' + replace_key + '}'
                for k, v in consolidated_parameters.items():
                    if not isinstance(v, str):
                        continue
                    if replace_pattern in v:
                        consolidated_parameters[k] = \
                            v.replace(replace_pattern, replace_value)

            get_file_contents_options = {
                'url': url,
                'path': path,
                'ref': target_ref,
                'github': github
            }

            try:
                template, html_url, commit_sha = \
                    self._get_file_contents(get_file_contents_options)
            except Exception as e:
                logging.error(
                    f"[{url}/{path}:{target_ref}] " +
                    f"error fetching template: {str(e)}")
                return None, None, None

            # add IMAGE_TAG only if it is unspecified
            image_tag = consolidated_parameters.get('IMAGE_TAG')
            if not image_tag:
                sha_substring = commit_sha[:hash_length]
                # IMAGE_TAG takes one of two forms:
                # - If saas file attribute 'use_channel_in_image_tag' is true,
                #   it is {CHANNEL}-{SHA}
                # - Otherwise it is just {SHA}
                if self._get_saas_file_feature_enabled(
                        "use_channel_in_image_tag"):
                    try:
                        channel = consolidated_parameters["CHANNEL"]
                    except KeyError:
                        logging.error(
                            f"[{saas_file_name}/{resource_template_name}] "
                            + f"{html_url}: CHANNEL is required when "
                            + "'use_channel_in_image_tag' is true."
                        )
                        return None, None, None
                    image_tag = f"{channel}-{sha_substring}"
                else:
                    image_tag = sha_substring
                consolidated_parameters['IMAGE_TAG'] = image_tag

            # This relies on IMAGE_TAG already being calculated.
            need_repo_digest = self._parameter_value_needed(
                "REPO_DIGEST", consolidated_parameters, template)
            need_image_digest = self._parameter_value_needed(
                "IMAGE_DIGEST", consolidated_parameters, template)
            if need_repo_digest or need_image_digest:
                try:
                    logging.debug("Generating REPO_DIGEST.")
                    registry_image = consolidated_parameters["REGISTRY_IMG"]
                except KeyError as e:
                    logging.error(
                        f"[{saas_file_name}/{resource_template_name}] "
                        + f"{html_url}: error generating REPO_DIGEST. "
                        + "Is REGISTRY_IMG missing? "
                        + f"{str(e)}")
                    return None, None, None
                try:
                    image_uri = f"{registry_image}:{image_tag}"
                    img = Image(image_uri, **image_auth)
                    if need_repo_digest:
                        consolidated_parameters[
                            "REPO_DIGEST"] = img.url_digest
                    if need_image_digest:
                        consolidated_parameters["IMAGE_DIGEST"] = img.digest
                except (rqexc.ConnectionError, rqexc.HTTPError) as e:
                    logging.error(
                        f"[{saas_file_name}/{resource_template_name}] "
                        + f"{html_url}: error generating REPO_DIGEST for "
                        + f"{image_uri}: {str(e)}")
                    return None, None, None

            oc = OC('cluster', None, None, local=True)
            try:
                resources = oc.process(template, consolidated_parameters)
            except StatusCodeError as e:
                logging.error(
                    f"[{saas_file_name}/{resource_template_name}] " +
                    f"{html_url}: error processing template: {str(e)}")

        elif provider == 'directory':
            get_directory_contents_options = {
                'url': url,
                'path': path,
                'ref': target_ref,
                'github': github
            }
            try:
                resources, html_url, commit_sha = \
                    self._get_directory_contents(
                        get_directory_contents_options)
            except Exception as e:
                logging.error(
                    f"[{url}/{path}:{target_ref}] " +
                    f"error fetching directory: {str(e)}")
                return None, None, None

        else:
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] " +
                f"unknown provider: {provider}")

        target_promotion['commit_sha'] = commit_sha
        return resources, html_url, target_promotion

    @staticmethod
    def _collect_images(resource):
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

    @staticmethod
    def _check_image(image, image_patterns, image_auth, error_prefix):
        error = False
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
        except Exception as e:
            error = True
            logging.error(f"{error_prefix} Image is invalid: {image}. " +
                          f"details: {str(e)}")

        return error

    def _check_images(self, options):
        saas_file_name = options['saas_file_name']
        resource_template_name = options['resource_template_name']
        html_url = options['html_url']
        resources = options['resources']
        image_auth = options['image_auth']
        image_patterns = options['image_patterns']
        error_prefix = \
            f"[{saas_file_name}/{resource_template_name}] {html_url}:"

        images_list = threaded.run(self._collect_images, resources,
                                   self.available_thread_pool_size)
        images = set(itertools.chain.from_iterable(images_list))
        if not images:
            return False  # no errors
        errors = threaded.run(self._check_image, images,
                              self.available_thread_pool_size,
                              image_patterns=image_patterns,
                              image_auth=image_auth,
                              error_prefix=error_prefix)
        return any(errors)

    def _initiate_github(self, saas_file):
        auth = saas_file.get('authentication') or {}
        auth_code = auth.get('code') or {}
        if auth_code:
            token = self.secret_reader.read(auth_code)
        else:
            # use the app-sre token by default
            default_org_name = 'app-sre'
            config = get_config(desired_org_name=default_org_name)
            token = config['github'][default_org_name]['token']

        base_url = os.environ.get('GITHUB_API', 'https://api.github.com')
        # This is a threaded world. Let's define a big
        # connections pool to live in that world
        # (this avoids the warning "Connection pool is
        # full, discarding connection: api.github.com")
        pool_size = 100
        return Github(token, base_url=base_url, pool_size=pool_size)

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

        creds = self.secret_reader.read_all(auth_image_secret)
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
        desired_state_specs = list(itertools.chain.from_iterable(results))
        promotions = threaded.run(self.populate_desired_state_saas_file,
                                  desired_state_specs,
                                  self.thread_pool_size,
                                  ri=ri)
        self.promotions = promotions

    def init_populate_desired_state_specs(self, saas_file):
        specs = []
        saas_file_name = saas_file['name']
        github = self._initiate_github(saas_file)
        image_auth = self._initiate_image_auth(saas_file)
        instance = saas_file.get('instance')
        # instance exists in v1 saas files only
        instance_name = instance['name'] if instance else None
        managed_resource_types = saas_file['managedResourceTypes']
        image_patterns = saas_file['imagePatterns']
        resource_templates = saas_file['resourceTemplates']
        saas_file_parameters = self._collect_parameters(saas_file)
        # iterate over resource templates (multiple per saas_file)
        for rt in resource_templates:
            rt_name = rt['name']
            url = rt['url']
            path = rt['path']
            provider = rt.get('provider') or 'openshift-template'
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
                    'image_auth': image_auth,
                    'url': url,
                    'path': path,
                    'provider': provider,
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
                    'check_images_options_base': check_images_options_base,
                    'instance_name': instance_name,
                    'upstream': target.get('upstream'),
                    'delete': target.get('delete'),
                }
                specs.append(spec)

        return specs

    def populate_desired_state_saas_file(self, spec, ri):
        if spec['delete']:
            # to delete resources, we avoid adding them to the desired state
            return

        saas_file_name = spec['saas_file_name']
        cluster = spec['cluster']
        namespace = spec['namespace']
        managed_resource_types = spec['managed_resource_types']
        process_template_options = spec['process_template_options']
        check_images_options_base = spec['check_images_options_base']
        instance_name = spec['instance_name']
        upstream = spec['upstream']

        resources, html_url, promotion = \
            self._process_template(process_template_options)
        if resources is None:
            ri.register_error()
            return
        # filter resources
        resources = [resource for resource in resources
                     if isinstance(resource, dict)
                     and resource.get('kind') in managed_resource_types]
        # additional processing of resources
        self._additional_resource_process(resources, html_url)
        # check images
        skip_check_images = upstream and self.jenkins_map and instance_name \
            and self.jenkins_map[instance_name].is_job_running(upstream)
        if skip_check_images:
            logging.warning(
                "skipping check_image since " +
                f"upstream job {upstream} is running"
            )
        else:
            check_images_options = {
                'html_url': html_url,
                'resources': resources
            }
            check_images_options.update(check_images_options_base)
            image_error = self._check_images(check_images_options)
            if image_error:
                ri.register_error()
                return
        # add desired resources
        for resource in resources:
            resource_kind = resource['kind']
            resource_name = resource['metadata']['name']
            oc_resource = OR(
                resource,
                self.integration,
                self.integration_version,
                caller_name=saas_file_name,
                error_details=html_url)
            try:
                ri.add_desired(
                    cluster,
                    namespace,
                    resource_kind,
                    resource_name,
                    oc_resource
                )
            except ResourceKeyExistsError:
                ri.register_error()
                msg = \
                    f"[{cluster}/{namespace}] desired item " + \
                    f"already exists: {resource_kind}/{resource_name}. " + \
                    f"saas file name: {saas_file_name}, " + \
                    "resource template name: " + \
                    f"{process_template_options['resource_template_name']}."
                logging.error(msg)

        return promotion

    def get_diff(self, trigger_type, dry_run):
        if trigger_type == TriggerTypes.MOVING_COMMITS:
            # TODO: replace error with actual error handling when needed
            error = False
            return self.get_moving_commits_diff(dry_run), error
        elif trigger_type == TriggerTypes.UPSTREAM_JOBS:
            # error is being returned from the called function
            return self.get_upstream_jobs_diff(dry_run)
        elif trigger_type == TriggerTypes.CONFIGS:
            # TODO: replace error with actual error handling when needed
            error = False
            return self.get_configs_diff(), error
        else:
            raise NotImplementedError(
                f'saasherder get_diff for trigger type: {trigger_type}')

    def update_state(self, trigger_type, job_spec):
        if trigger_type == TriggerTypes.MOVING_COMMITS:
            self.update_moving_commit(job_spec)
        elif trigger_type == TriggerTypes.UPSTREAM_JOBS:
            self.update_upstream_job(job_spec)
        elif trigger_type == TriggerTypes.CONFIGS:
            self.update_config(job_spec)
        else:
            raise NotImplementedError(
                f'saasherder update_state for trigger type: {trigger_type}')

    def get_moving_commits_diff(self, dry_run):
        results = threaded.run(self.get_moving_commits_diff_saas_file,
                               self.saas_files,
                               self.thread_pool_size,
                               dry_run=dry_run)
        return list(itertools.chain.from_iterable(results))

    def get_moving_commits_diff_saas_file(self, saas_file, dry_run):
        saas_file_name = saas_file['name']
        timeout = saas_file.get('timeout') or None
        pipelines_provider = self._get_pipelines_provider(saas_file)
        github = self._initiate_github(saas_file)
        trigger_specs = []
        for rt in saas_file['resourceTemplates']:
            rt_name = rt['name']
            url = rt['url']
            for target in rt['targets']:
                try:
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
                        'timeout': timeout,
                        'pipelines_provider': pipelines_provider,
                        'rt_name': rt_name,
                        'cluster_name': cluster_name,
                        'namespace_name': namespace_name,
                        'ref': ref,
                        'commit_sha': desired_commit_sha
                    }
                    trigger_specs.append(job_spec)
                except (GithubException, GitlabError):
                    logging.exception(
                        f"Skipping target {saas_file_name}:{rt_name}"
                        f" - repo: {url} - ref: {ref}"
                    )

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

    def get_upstream_jobs_diff(self, dry_run):
        current_state, error = self._get_upstream_jobs_current_state()
        results = threaded.run(self.get_upstream_jobs_diff_saas_file,
                               self.saas_files,
                               self.thread_pool_size,
                               dry_run=dry_run,
                               current_state=current_state)
        return list(itertools.chain.from_iterable(results)), error

    def _get_upstream_jobs_current_state(self):
        current_state = {}
        error = False
        for instance_name, jenkins in self.jenkins_map.items():
            try:
                current_state[instance_name] = jenkins.get_jobs_state()
            except (rqexc.ConnectionError, rqexc.HTTPError):
                error = True
                logging.error(f"instance unreachable: {instance_name}")
                current_state[instance_name] = {}

        return current_state, error

    def get_upstream_jobs_diff_saas_file(self, saas_file, dry_run,
                                         current_state):
        saas_file_name = saas_file['name']
        timeout = saas_file.get('timeout') or None
        pipelines_provider = self._get_pipelines_provider(saas_file)
        trigger_specs = []
        for rt in saas_file['resourceTemplates']:
            rt_name = rt['name']
            for target in rt['targets']:
                upstream = target.get('upstream')
                if not upstream:
                    continue
                instance_name = upstream['instance']['name']
                job_name = upstream['name']
                job_history = current_state[instance_name].get(job_name, [])
                if not job_history:
                    continue
                last_build_result = job_history[0]
                namespace = target['namespace']
                cluster_name = namespace['cluster']['name']
                namespace_name = namespace['name']
                env_name = namespace['environment']['name']
                key = f"{saas_file_name}/{rt_name}/{cluster_name}/" + \
                    f"{namespace_name}/{env_name}/{instance_name}/{job_name}"
                state_build_result = self.state.get(key, None)
                # skip if last_build_result is incomplete or
                # there is no change in job state
                if last_build_result['result'] is None or \
                        last_build_result == state_build_result:
                    continue
                # don't trigger if this is the first time
                # this target is being deployed.
                # that will be taken care of by
                # openshift-saas-deploy-trigger-configs
                if state_build_result is None:
                    # store the value to take over from now on
                    if not dry_run:
                        self.state.add(key, value=last_build_result)
                    continue

                state_build_result_number = state_build_result['number']
                for build_result in job_history:
                    # this is the most important condition
                    # if there is a successful newer build -
                    # trigger the deployment ONCE.
                    if build_result['number'] > state_build_result_number \
                            and build_result['result'] == 'SUCCESS':
                        # we finally found something we want to trigger on!
                        job_spec = {
                            'saas_file_name': saas_file_name,
                            'env_name': env_name,
                            'timeout': timeout,
                            'pipelines_provider': pipelines_provider,
                            'rt_name': rt_name,
                            'cluster_name': cluster_name,
                            'namespace_name': namespace_name,
                            'instance_name': instance_name,
                            'job_name': job_name,
                            'last_build_result': last_build_result,
                        }
                        trigger_specs.append(job_spec)
                        # only trigger once, even if multiple builds happened
                        break

        return trigger_specs

    def update_upstream_job(self, job_spec):
        saas_file_name = job_spec['saas_file_name']
        env_name = job_spec['env_name']
        rt_name = job_spec['rt_name']
        cluster_name = job_spec['cluster_name']
        namespace_name = job_spec['namespace_name']
        instance_name = job_spec['instance_name']
        job_name = job_spec['job_name']
        last_build_result = job_spec['last_build_result']
        key = f"{saas_file_name}/{rt_name}/{cluster_name}/" + \
            f"{namespace_name}/{env_name}/{instance_name}/{job_name}"
        self.state.add(key, value=last_build_result, force=True)

    def get_configs_diff(self):
        results = threaded.run(self.get_configs_diff_saas_file,
                               self.saas_files,
                               self.thread_pool_size)
        return list(itertools.chain.from_iterable(results))

    def get_configs_diff_saas_file(self, saas_file):
        saas_file_name = saas_file['name']
        saas_file_parameters = saas_file.get('parameters')
        saas_file_managed_resource_types = saas_file['managedResourceTypes']
        timeout = saas_file.get('timeout') or None
        pipelines_provider = self._get_pipelines_provider(saas_file)
        trigger_specs = []
        for rt in saas_file['resourceTemplates']:
            rt_name = rt['name']
            url = rt['url']
            path = rt['path']
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
                # add managed resource types to target config
                desired_target_config['saas_file_managed_resource_types'] = \
                    saas_file_managed_resource_types
                desired_target_config['url'] = url
                desired_target_config['path'] = path
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
                    'timeout': timeout,
                    'pipelines_provider': pipelines_provider,
                    'rt_name': rt_name,
                    'cluster_name': cluster_name,
                    'namespace_name': namespace_name,
                    'target_config': desired_target_config
                }
                trigger_specs.append(job_spec)

        return trigger_specs

    @staticmethod
    def _get_pipelines_provider(saas_file):
        """Returns the Pipelines Provider for a SaaS file.

        Args:
            saas_file (dict): SaaS file GQL query result with apiVersion key

        Returns:
            dict: Pipelines Provider details
        """
        saas_file_api_version = saas_file['apiVersion']
        if saas_file_api_version == 'v1':
            # wrapping the instance in a pipelines provider structure
            # for backwards compatibility
            pipelines_provider = {
                'provider': Providers.JENKINS,
                'instance': saas_file['instance'],
            }
        if saas_file_api_version == 'v2':
            pipelines_provider = saas_file['pipelinesProvider']

        return pipelines_provider

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

    def validate_promotions(self):
        """
        If there were promotion sections in the participating saas files
        validate that the conditions are met. """
        for item in self.promotions:
            if item is None:
                continue
            # validate that the commit sha being promoted
            # was succesfully published to the subscribed channel(s)
            commit_sha = item['commit_sha']
            subscribe = item.get('subscribe')
            if subscribe:
                for channel in subscribe:
                    state_key = f"promotions/{channel}/{commit_sha}"
                    value = self.state.get(state_key, {})
                    success = value.get('success')
                    if not success:
                        logging.error(
                            f'Commit {commit_sha} was not ' +
                            f'published with success to channel {channel}'
                        )
                        return False

        return True

    def publish_promotions(self, success, saas_files, mr_cli):
        """
        If there were promotion sections in the participating saas files
        publish the results for future promotion validations. """
        subscribe_saas_file_path_map = \
            self._get_subscribe_saas_file_path_map(saas_files, auto_only=True)
        trigger_promotion = False
        for item in self.promotions:
            if item is None:
                continue
            commit_sha = item['commit_sha']
            publish = item.get('publish')
            if publish:
                all_subscribed_saas_file_paths = set()
                for channel in publish:
                    # publish to state to pass promotion gate
                    state_key = f"promotions/{channel}/{commit_sha}"
                    value = {
                        'success': success
                    }
                    self.state.add(state_key, value, force=True)
                    logging.info(
                        f'Commit {commit_sha} was published ' +
                        f'with success {success} to channel {channel}'
                    )
                    # collect data to trigger promotion
                    subscribed_saas_file_paths = \
                        subscribe_saas_file_path_map.get(channel)
                    if subscribed_saas_file_paths:
                        all_subscribed_saas_file_paths.update(
                            subscribed_saas_file_paths)
                item['saas_file_paths'] = list(all_subscribed_saas_file_paths)
                if all_subscribed_saas_file_paths:
                    trigger_promotion = True

        if success and trigger_promotion:
            mr = AutoPromoter(self.promotions)
            mr.submit(cli=mr_cli)

    @staticmethod
    def _get_subscribe_saas_file_path_map(saas_files, auto_only=False):
        """
        Returns a dict with subscribe channels as keys and a
        list of paths of saas files containing these channels.
        """
        subscribe_saas_file_path_map = {}
        for saas_file in saas_files:
            saas_file_path = 'data' + saas_file['path']
            for rt in saas_file['resourceTemplates']:
                for target in rt['targets']:
                    target_promotion = target.get('promotion')
                    if not target_promotion:
                        continue
                    target_auto = target_promotion.get('auto')
                    if auto_only and not target_auto:
                        continue
                    subscribe = target_promotion.get('subscribe')
                    if not subscribe:
                        continue
                    for channel in subscribe:
                        subscribe_saas_file_path_map.setdefault(
                            channel, set())
                        subscribe_saas_file_path_map[channel].add(
                            saas_file_path)

        return subscribe_saas_file_path_map
