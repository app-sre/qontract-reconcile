import semver

import utils.gql as gql
import reconcile.openshift_base as ob
import utils.jsonnet as jsonnet
import utils.template as template_utils

from utils.defer import defer
from utils.openshift_resource import (OpenshiftResource as OR)
from utils.jb_client import JsonnetBundler


class Jinja2TemplateError(Exception):
    def __init__(self, msg):
        super(Jinja2TemplateError, self).__init__(
            "error processing jinja2 template: " + str(msg)
        )


PERFORMANCEPARAMETERS_QUERY = """
{
  performance_parameters_v1 {
    labels
    name
    component
    prometheusLabels
    namespaces {
      namespace {
        name
      }
    }
    app {
      name
      namespaces {
        name
        cluster {
          observabilityNamespace {
            name
            cluster {
              name
              serverUrl
              jumpHost {
                hostname
                knownHosts
                user
                port
                identity {
                  path
                  field
                  format
                }
              }
              automationToken {
                path
                field
                format
              }
              disable {
                integrations
              }
            }
          }
          name
          serverUrl
          jumpHost {
            hostname
            knownHosts
            user
            port
            identity {
              path
              field
              format
            }
          }
          automationToken {
            path
            field
            format
          }
          disable {
            integrations
          }
        }
      }
    }
    availability {
      kind
      metric
      errorBudget
      selectors
    }
    latency {
      kind
      metric
      threshold
      percentile
      selectors
    }
    rawRecording {
      record
      expr
      labels
    }
    rawAlerting {
      alert
      expr
      for
      labels
      annotations {
        message
        runbook
        dashboard
        link_url
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'openshift-prometheusrules'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)
JSONNET_TEMPLATE_FILE = "slo.jsonnet.j2"
LIBSONNET_TEMPLATE_FILE = "slo.libsonnet.j2"


def fetch_desired_state(performance_parameters, ri):
    jb_client = init_jb_client()
    defer(lambda: jb_client.cleanup())
    temp_dir_path = jb_client.get_dir_path()
    template_env = template_utils.get_package_environment()

    # Iterate over all available Performance Parameters
    for pp in performance_parameters['performance_parameters_v1']:
        for namespace in pp['app']['namespaces']:
            if namespace['cluster']['observabilityNamespace'] is not None:

                libsonnet_file_path = jsonnet.generate_libsonnet_file(
                  LIBSONNET_TEMPLATE_FILE,
                  pp,
                  namespace,
                  temp_dir_path,
                  template_env
                  )

                jsonnet_file_path = jsonnet.generate_jsonnet_file(
                  JSONNET_TEMPLATE_FILE,
                  pp,
                  namespace,
                  libsonnet_file_path,
                  temp_dir_path,
                  template_env
                  )

                # Generate the manifests
                output = jsonnet.generate(jsonnet_file_path, temp_dir_path)
                resource_name = output['metadata']['name']

                openshift_resource = OR(
                  output,
                  QONTRACT_INTEGRATION,
                  QONTRACT_INTEGRATION_VERSION,
                  error_details=resource_name
                  )

                cluster = namespace['cluster']
                cluster_observability_namespace = cluster.get(
                  'observabilityNamespace'
                  )

                ri.add_desired(
                    cluster_observability_namespace['cluster']['name'],
                    cluster_observability_namespace['name'],
                    'PrometheusRule',
                    resource_name,
                    openshift_resource
                )


def init_jb_client():
    jsonnetfile = """{
        "dependencies": [
            {
                "name": "slo-libsonnet",
                "source": {
                    "git": {
                        "remote":
                        "https://github.com/metalmatze/slo-libsonnet",
                        "subdir": "slo-libsonnet"
                    }
                },
                "version": "037525d64e7ffe3198acfbaa99482cffced8e9c0"
            }
        ]
    }
    """
    return JsonnetBundler(jsonnetfile)


def get_observability_namespaces(performance_parameters):
    for pp in performance_parameters['performance_parameters_v1']:
        observability_namespaces = [
            ns['cluster']['observabilityNamespace']
            for ns in pp['app']['namespaces']
            if ns['cluster']['observabilityNamespace'] is not None
          ]
    return observability_namespaces


@defer
def run(dry_run=False, thread_pool_size=10, defer=None):

    gqlapi = gql.get_api()

    performance_parameters = gqlapi.query(PERFORMANCEPARAMETERS_QUERY)

    observability_namespaces = get_observability_namespaces(
      performance_parameters
      )

    ri, oc_map = \
        ob.fetch_current_state(observability_namespaces, thread_pool_size,
                               QONTRACT_INTEGRATION,
                               QONTRACT_INTEGRATION_VERSION,
                               override_managed_types=['PrometheusRule'])
    defer(lambda: oc_map.cleanup())

    fetch_desired_state(performance_parameters, ri)

    ob.realize_data(dry_run, oc_map, ri)
