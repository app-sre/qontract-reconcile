import os
import yaml
import json
import logging

from github import Github
from sretoolbox.container import Image

import utils.secret_reader as secret_reader

from utils.oc import OC
from utils.state import State
from utils.slack_api import SlackApi
from utils.openshift_resource import OpenshiftResource as OR
from reconcile.github_org import get_config


class SaasHerder():
    """Wrapper around SaaS deployment actions."""

    def __init__(self, saas_files,
                 gitlab,
                 integration,
                 integration_version,
                 settings):
        self.saas_files = saas_files
        self.gitlab = gitlab
        self.integration = integration
        self.integration_version = integration_version
        self.settings = settings
        self.namespaces = self._collect_namespaces()

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

    def _get_file_contents(self, url, path, ref):
        if 'github' in url:
            repo_name = url.rstrip("/").replace('https://github.com/', '')
            repo = self.github.get_repo(repo_name)
            f = repo.get_contents(path, ref)
            return f.decoded_content
        elif 'gitlab' in url:
            project = self.gitlab.get_project(url)
            f = project.files.get(file_path=path, ref=ref)
            return f.decode()

    def _get_commit_sha(self, url, ref, hash_length):
        commit_sha = ''
        if 'github' in url:
            repo_name = url.rstrip("/").replace('https://github.com/', '')
            repo = self.github.get_repo(repo_name)
            commit = repo.get_commit(sha=ref)
            commit_sha = commit.sha
        elif 'gitlab' in url:
            project = self.gitlab.get_project(url)
            commits = project.commits.list(ref_name=ref)
            commit_sha = commits[0].id
        return commit_sha[:hash_length]

    @staticmethod
    def _get_cluster_and_namespace(target):
        cluster = target['namespace']['cluster']['name']
        namespace = target['namespace']['name']
        return cluster, namespace

    def _process_template(self, url, path, hash_length, target, parameters):
        target_hash = target['hash']
        target_parameters = self._collect_parameters(target)
        target_parameters.update(parameters)
        content = self._get_file_contents(url, path, target_hash)
        template = yaml.safe_load(content)
        for template_parameter in template['parameters']:
            if template_parameter['name'] == 'IMAGE_TAG':
                # add IMAGE_TAG only if it is required
                image_tag = self._get_commit_sha(url, target_hash, hash_length)
                target_parameters['IMAGE_TAG'] = image_tag
        oc = OC('server', 'token')
        resources = oc.process(template, target_parameters)
        return resources

    def _collect_images(self, resource):
        images = set()
        try:
            for c in resource["spec"]["template"]["spec"]["containers"]:
                images.add(c["image"])
        except KeyError:
            pass

        return images

    def _check_images(self, resource):
        error = False
        images = self._collect_images(resource)
        if self.image_auth:
            username = self.image_auth['user']
            password = self.image_auth['token']
        else:
            username = None
            password = None
        for image in images:
            if not Image(image, username=username, password=password):
                error = True
                logging.error(f"Image does not exist: {image}")
        return error

    def _initiate_github(self, saas_file):
        auth = saas_file.get('authentication') or {}
        auth_code = auth.get('code') or {}
        if auth_code:
            token = secret_reader.read(auth_code, settings=self.settings)
        else:
            config = get_config()
            github_config = config['github']
            token = github_config['app-sre']['token']

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
        for saas_file in self.saas_files:
            self.github = self._initiate_github(saas_file)
            self.image_auth = self._initiate_image_auth(saas_file)
            managed_resource_types = saas_file['managedResourceTypes']
            resource_templates = saas_file['resourceTemplates']
            # iterate over resource templates (multiple per saas_file)
            for rt in resource_templates:
                url = rt['url']
                path = rt['path']
                hash_length = rt['hash_length']
                parameters = self._collect_parameters(rt)
                # iterate over targets (each target is a namespace)
                for target in rt['targets']:
                    cluster, namespace = \
                        self._get_cluster_and_namespace(target)
                    resources = self._process_template(url, path, hash_length,
                                                       target, parameters)
                    # add desired resources
                    for resource in resources:
                        resource_kind = resource['kind']
                        if resource_kind not in managed_resource_types:
                            continue
                        # check images
                        image_error = self._check_images(resource)
                        if image_error:
                            ri.register_error()
                            continue
                        resource_name = resource['metadata']['name']
                        oc_resource = OR(
                            resource,
                            self.integration,
                            self.integration_version,
                            error_details=resource_name)
                        ri.add_desired(
                            cluster,
                            namespace,
                            resource_kind,
                            resource_name,
                            oc_resource
                        )

    def _init_slack(self, slack_info):
        slack_integrations = slack_info['workspace']['integrations']
        saas_deploy_config = \
            [i for i in slack_integrations if i['name'] == self.integration]
        [saas_deploy_config] = saas_deploy_config

        token = saas_deploy_config['token']
        default_channel = saas_deploy_config['channel']
        icon_emoji = saas_deploy_config['icon_emoji']
        username = saas_deploy_config['username']
        channel = slack_info.get('channel') or default_channel

        slack = SlackApi(token,
                         settings=self.settings,
                         init_usergroups=False,
                         channel=channel,
                         icon_emoji=icon_emoji,
                         username=username)
        return slack

    @staticmethod
    def _get_deployment_result(dry_run, ri):
        if dry_run:
            return 'TBD'
        if ri.has_error_registered():
            return 'FAILED'

        return 'SUCCESS'

    def slack_notify(self, dry_run, aws_accounts, ri):
        result = self._get_deployment_result(dry_run, ri)
        state = State(
            integration=self.integration,
            accounts=aws_accounts,
            settings=self.settings
        )
        for saas_file in self.saas_files:
            self.github = self._initiate_github(saas_file)
            saas_file_name = saas_file['name']
            for resource_template in saas_file['resourceTemplates']:
                url = resource_template['url']
                hash_length = resource_template['hash_length']
                resource_template_name = resource_template['name']
                for target in resource_template['targets']:
                    if not target.get('notify'):
                        continue
                    cluster, namespace = \
                        self._get_cluster_and_namespace(target)
                    target_hash = target['hash']
                    desired_commit_sha = \
                        self._get_commit_sha(url, target_hash, hash_length)
                    state_key_format = "{}/{}/{}/{}"
                    state_key = state_key_format.format(
                        saas_file_name,
                        resource_template_name,
                        cluster,
                        namespace
                    )
                    current_commit_sha = state.get(state_key, None)
                    if current_commit_sha != desired_commit_sha:
                        slack_info = saas_file.get('slack')
                        if slack_info:
                            slack = self._init_slack(slack_info)
                            msg_format = "[{}] {} deployment to {}/{}: {}"
                            msg = msg_format.format(
                                saas_file_name,
                                resource_template_name,
                                cluster,
                                namespace,
                                result
                            )
                            channel = slack.chat_kwargs['channel']
                            logging.info(['slack_notify', channel, msg])
                            if not dry_run:
                                state[state_key] = desired_commit_sha
                                slack.chat_post_message(msg)
