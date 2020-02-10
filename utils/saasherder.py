import yaml
import json

from checks.registry_quay import CheckRegistryQuay

from utils.openshift_resource import OpenshiftResource as OR


class SaasHerder():
    """Wrapper around SaaS deployment actions."""

    def __init__(self, saas_files, github, gitlab=None, internal=None):
        self.saas_files = saas_files
        self.github = github
        self.gitlab = gitlab
        self._collect_namespaces()

    def _collect_namespaces(self, saas_files):
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
        self.namespaces = namespaces

    @staticmethod
    def _collect_parameters(container):
        parameters = container.get('parameters') or {}
        if isinstance(parameters, str):
            parameters = json.loads(parameters)
        return parameters

    def populate_desired_state(self, ri, oc_map):
        for saas_file in self.saas_files:
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




    def collect_resources(url, path, hash_length, target, parameters):
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
