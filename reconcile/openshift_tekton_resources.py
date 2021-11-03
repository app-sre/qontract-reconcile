import sys
import logging
import copy
import json
from typing import Any, Dict, Iterable, List, Optional, Union
from pathlib import Path

# TODO: remove!
from pprint import pp

import yaml
import jinja2

from reconcile import queries
from reconcile import openshift_base as ob
from reconcile import openshift_resources_base as orb
from reconcile.status import ExitCodes
from reconcile.utils import threaded, gql
from reconcile.utils.oc import OC_Map, StatusCodeError
from reconcile.utils.defer import defer
from reconcile.utils.openshift_resource import OpenshiftResource
from reconcile.utils.semver_helper import make_semver

LOG = logging.getLogger(__name__)
QONTRACT_INTEGRATION = 'openshift-tekton-resources'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

OBJECTS_PREFIX = 'otr'
RESOURCE_MAX_LENGTH = 63

# Defaults
DEFAULT_DEPLOY_RESOURCES = {'requests': {'cpu': '50m',
                                         'memory': '200Mi'},
                            'limits': {'cpu': '200m',
                                       'memory': '300Mi'}}
# Type alias
SaasFile = Dict[str, Any]
TektonNamespace = Dict[str, Any]
LoadedYamlResource = Dict[str, Any]

SAAS_FILES_QUERY = """
{
  saas_files: saas_files_v2 {
    path
    name
    configurableResources
    pipelinesProvider {
      name
      provider
    }
    deployResources {
      requests {
        cpu
        memory
      }
      limits {
        cpu
        memory
      }
    }
  }
}
"""


class OpenshiftTektonResourcesNameTooLong(Exception):
    pass


class OpenshiftTektonResources:
    """Integration runner class"""
    def __init__(self,
                 dry_run: bool,
                 thread_pool_size: int,
                 internal: Optional[bool],
                 use_jump_host: bool,
                 saas_file_name: Optional[str]) -> None:
        self.dry_run = dry_run
        self.thread_pool_size = thread_pool_size
        self.internal = internal
        self.use_jump_host = use_jump_host
        self.saas_file_name = saas_file_name
        self.gqlapi = gql.get_api()

    def run(self) -> bool:
        """Runs the integration"""
        saas_files = self._get_saas_files()
        if not saas_files:
            LOG.info("No saas files found to be processed")
            return False

        tkn_providers = self._get_tkn_providers(saas_files)

        # desired state
        # add the saas files
        for sf in saas_files:
            tkn_provider_name = sf['pipelinesProvider']['name']
            if 'saas_files' not in tkn_providers[tkn_provider_name]:
                tkn_providers[tkn_provider_name]['saas_files'] = []

            tkn_providers[tkn_provider_name]['saas_files'].append(sf)

        desired_resources = []
        for tkn_provider in tkn_providers.values():
            namespace = tkn_provider['namespace']['name']
            cluster = tkn_provider['namespace']['cluster']['name']
            deploy_resources = tkn_provider.get('deployResources',
                                                DEFAULT_DEPLOY_RESOURCES)

            # a dict with task template names as keys and types as values
            task_templates_types = {}
            task_names = []
            for task_template in tkn_provider['taskTemplates']:
                task_templates_types[task_template['name']] = \
                    task_template['type']

                if task_template['type'] == 'onePerNamespace':
                    task = self._build_one_per_namespace_task(task_template)
                    task_names.append(task['metadata']['name'])
                    desired_resources.append(self._build_desired_resource(
                        task, task_template['path'], cluster, namespace))
                elif task_template['type'] == 'onePerSaasFile':
                    for saas_file in tkn_provider['saas_files']:
                        task = self._build_one_per_saas_file_task(
                            task_template, saas_file, deploy_resources)
                        task_names.append(task['metadata']['name'])
                        desired_resources.append(self._build_desired_resource(
                            task, task_template['path'], cluster, namespace))
                else:
                    # TODO: Raise Custom Exception
                    raise Exception("unknown type")

            # This is a hack, but we will need it while we have the old
            # resources being created from app-interface via
            # openshift-resources. If not, this integration will try to take
            # over those resources
            tkn_provider['namespace']['managedResourceNames'] = [{
                'resource': 'Task',
                'resourceNames': task_names
            }]

            # We only support pipelines from OpenshiftSaasDeploy
            pipeline_template = \
                tkn_provider['pipelineTemplates']['openshiftSaasDeploy']
            pipeline_names = []
            for saas_file in tkn_provider['saas_files']:
                pipeline = self._build_one_per_saas_file_pipeline(
                    pipeline_template, saas_file, task_templates_types)
                pipeline_names.append(pipeline['metadata']['name'])
                desired_resources.append(self._build_desired_resource(
                    pipeline, pipeline_template['path'], cluster, namespace))

            tkn_provider['namespace']['managedResourceNames'].append({
                'resource': 'Pipeline',
                'resourceNames': pipeline_names
            })

        tkn_namespaces = [tknp['namespace'] for tknp in tkn_providers.values()]
        ri, oc_map = ob.fetch_current_state(
            namespaces=tkn_namespaces,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            override_managed_types=['Pipeline', 'Task'],
            internal=self.internal,
            use_jump_host=self.use_jump_host,
            thread_pool_size=self.thread_pool_size)

        for desired_resource in desired_resources:
            ri.add_desired(**desired_resource)

        ob.realize_data(self.dry_run, oc_map, ri, self.thread_pool_size)

        if ri.has_error_registered():
            return False

        return True

    def _build_desired_resource(self, tkn_object, path, cluster, namespace):
        # TODO: exception handling
        openshift_resource = OpenshiftResource(tkn_object,
                                               QONTRACT_INTEGRATION,
                                               QONTRACT_INTEGRATION_VERSION,
                                               error_details=path)

        return {'cluster': cluster,
                'namespace': namespace,
                'resource_type': openshift_resource.kind,
                'name': openshift_resource.name,
                'value': openshift_resource}

    def _build_one_per_namespace_task(self, task_template):
        variables = json.loads(task_template.get('variables', {}))
        task = self._load_tkn_template(task_template['path'], variables)
        task['metadata']['name'] = \
            self.build_one_per_namespace_tkn_object_name(task_template['name'])
        return task

    def _build_one_per_saas_file_task(self, task_template, saas_file,
                                      deploy_resources):
        variables = json.loads(task_template.get('variables')) \
            if task_template.get('variables') else {}
        task = self._load_tkn_template(task_template['path'], variables)
        task['metadata']['name'] = \
            self.build_one_per_saas_file_tkn_object_name(
                task_template['name'], saas_file['name'])
        step_name = task_template.get('deployResourcesStepName',
                                      'qontract-reconcile')

        resources_configured = False
        for step in task['spec']['steps']:
            if step['name'] == step_name:
                step['resources'] = saas_file.get('deployResources',
                                                  deploy_resources)
                resources_configured = True
                break

        if not resources_configured:
            # TODO: raise proper exception
            raise Exception(
                f"Cannot find a step named {step_name} to set resources")

        return task

    def _build_one_per_saas_file_pipeline(self, pipeline_template, saas_file,
                                          task_templates_types):
        variables = json.loads(pipeline_template.get('variables')) \
            if pipeline_template.get('variables') else {}
        pipeline = self._load_tkn_template(pipeline_template['path'],
                                           variables)
        pipeline['metadata']['name'] = \
            self.build_one_per_saas_file_tkn_object_name(
                pipeline_template['name'], saas_file['name'])

        for section in ['tasks', 'finally']:
            for task in pipeline['spec'][section]:
                if task['name'] not in task_templates_types:
                    # TODO: More info in text and custom exception
                    raise Exception(f"Unknown task {task['name']}")

                if task_templates_types[task['name']] == "onePerNamespace":
                    task['taskRef']['name'] = \
                        self.build_one_per_namespace_tkn_object_name(
                            task['name'])
                else:
                    task['taskRef']['name'] = \
                        self.build_one_per_saas_file_tkn_object_name(
                            task['name'], saas_file['name'])

        return pipeline

    def _load_tkn_template(self, path, variables):
        resource = self.gqlapi.get_resource(path)
        body = jinja2.Template(
            resource['content'], undefined=jinja2.StrictUndefined). \
                render(variables)

        return yaml.safe_load(body)

    # Builds a list of v2 saas files from qontract-server
    def _get_saas_files(self) -> List[SaasFile]:
        saas_files = [
            s for s in self.gqlapi.query(SAAS_FILES_QUERY)['saas_files']
            if s.get('configurableResources')]

        if self.saas_file_name:
            saas_file = None
            for s in saas_files:
                if s['name'] == self.saas_file_name:
                    saas_file = s
                    break

            return [saas_file] if saas_file else []

        return saas_files

    def _get_tkn_providers(self, saas_files):
        errors = 0
        tkn_providers = {}
        for pp in queries.get_pipelines_providers():
            if pp['provider'] != 'tekton':
                continue

            if pp['name'] in tkn_providers:
                logger.error("Duplicated name {pp['name']} from {pp['path']}")
                errors += 1
            else:
                tkn_providers[pp['name']] = pp

        if errors > 0:
            # TODO: raise proper exception
            raise Exception("duplicates")

        # Only get the providers that are used by the saas files
        tkn_providers_names = set()
        for saas_file in saas_files:
            tkn_providers_names.add(saas_file['pipelinesProvider']['name'])

        return {key: tkn_providers[key] for key in tkn_providers_names}

    @staticmethod
    def _check_resource_max_length(name: str) -> None:
        if len(name) > RESOURCE_MAX_LENGTH:
            raise OpenshiftTektonResourcesNameTooLong(
                f"name {name} is longer than {RESOURCE_MAX_LENGTH} characters")

    @staticmethod
    def build_one_per_namespace_tkn_object_name(name: str) -> str:
        """Returns the PushGateway Task name created by this integration"""
        name = f'{OBJECTS_PREFIX}-{name}'
        OpenshiftTektonResources._check_resource_max_length(name)
        return name

    @staticmethod
    def build_one_per_saas_file_tkn_object_name(template_name: str,
                                                saas_file_name: str) -> str:
        """Given a saas file name, return the openshift-saas-deploy names used
        by Tasks and Pipelines created by this integration"""
        name = f"{OBJECTS_PREFIX}-{saas_file_name}-{template_name}"
        OpenshiftTektonResources._check_resource_max_length(name)
        return name


def run(dry_run: bool,
        thread_pool_size: int = 10,
        internal: Optional[bool] = None,
        use_jump_host: bool = True,
        saas_file_name: Optional[str] = None) -> None:
    """Runner function as expected by reconcile.cli"""
    otr = OpenshiftTektonResources(dry_run=dry_run,
                                   thread_pool_size=thread_pool_size,
                                   internal=internal,
                                   use_jump_host=use_jump_host,
                                   saas_file_name=saas_file_name)

    if not otr.run():
        sys.exit(ExitCodes.ERROR)
