import logging
import semver
import yaml
import json

import reconcile.queries as queries
import reconcile.openshift_base as ob

from reconcile.github_users import init_github
from utils.gitlab_api import GitLabApi
from utils.openshift_resource import OpenshiftResource as OR
from utils.defer import defer


QONTRACT_INTEGRATION = 'openshift-saas-deploy'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def get_github_file_contents(url, path, ref, gh):
    repo_name = url.rstrip("/").replace('https://github.com/', '')
    repo = gh.get_repo(repo_name)
    f = repo.get_contents(path, ref)
    return f.decoded_content


def get_gitlab_file_contents(url, path, ReferenceError, gl):
    project = gl.get_project(url)
    f = project.files.get(file_path=path, ref=ref)
    return f.decode()


def get_file_contents(url, path, ref, gh, gl):
    if 'github' in url:
        return get_github_file_contents(url, path, ref, gh)
    elif 'gitlab' in url:
        return get_gitlab_file_contents(url, path, ref, gl)


def get_github_commit(url, ref, gh):
    repo_name = url.rstrip("/").replace('https://github.com/', '')
    repo = gh.get_repo(repo_name)
    commit = repo.get_commit(sha=ref)
    return commit.sha


def get_gitlab_commit(url, ref, gl):
    project = gl.get_project(url)
    commits = project.commits.list(ref_name=ref)
    return commits[0].id


def get_image_tag(url, ref, hash_length, gh, gl):
    if 'github' in url:
        commit = get_github_commit(url, ref, gh)
    elif 'gitlab' in url:
        commit = get_gitlab_commit(url, ref, gl)
    return commit[:hash_length]


def collect_parameters(container):
    parameters = container.get('parameters') or {}
    if isinstance(parameters, str):
        parameters = json.loads(parameters)
    return parameters


def collect_resources(url, path, hash_length, target, parameters,
                      gh, gl, oc_map):
    namespace_info = target['namespace']
    namespace_name = namespace_info['name']
    cluster_info = namespace_info['cluster']
    cluster_name = cluster_info['name']
    target_hash = target['hash']
    # take internal into consideration later
    content = get_file_contents(url, path, target_hash, gh, gl)
    template = yaml.safe_load(content)
    # collect parameters
    target_parameters = collect_parameters(target)
    target_parameters.update(parameters)
    # add IMAGE_TAG
    image_tag = get_image_tag(url, target_hash, hash_length, gh, gl)
    target_parameters['IMAGE_TAG'] = image_tag
    # process template
    oc = oc_map.get(cluster_name)
    resources = oc.process(template, target_parameters)
    return resources, cluster_name, namespace_name


def fetch_desired_state(saas_files, ri, oc_map):
    gh = init_github()
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)

    for saas_file in saas_files:
        managed_resource_types = saas_file['managedResourceTypes']
        resource_templates = saas_file['resourceTemplates']
        # iterate over resource templates (multiple per saas_file)
        for rt in resource_templates:
            url = rt['url']
            path = rt['path']
            hash_length = rt['hash_length']
            parameters = collect_parameters(rt)
            # iterate over targets (each target is a namespace)
            for target in rt['targets']:
                resources, cluster, namespace = \
                    collect_resources(url, path, hash_length,
                                      target, parameters,
                                      gh, gl, oc_map)
                # add desired resources
                for resource in resources:
                    resource_kind = resource['kind']
                    if resource_kind not in managed_resource_types:
                        continue
                    resource_name = resource['metadata']['name']
                    oc_resource = OR(resource,
                                     QONTRACT_INTEGRATION,
                                     QONTRACT_INTEGRATION_VERSION,
                                     error_details=resource_name)
                    ri.add_desired(
                        cluster,
                        namespace,
                        resource_kind,
                        resource_name,
                        oc_resource
                    )


def collect_namespaces(saas_files):
    # namespaces may appear more then once in the result
    # this will be handled by OC_Map
    namespaces = []
    for saas_file in saas_files:
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


@defer
def run(dry_run=False, thread_pool_size=10, internal=None, defer=None):
    saas_files = queries.get_saas_files()
    namespaces = collect_namespaces(saas_files)
    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        internal=internal)
    defer(lambda: oc_map.cleanup())
    fetch_desired_state(saas_files, ri, oc_map)
    ob.realize_data(dry_run, oc_map, ri)
