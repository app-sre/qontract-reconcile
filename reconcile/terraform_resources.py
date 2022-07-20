import logging
import shutil
import sys

from textwrap import indent
from typing import Any, Iterable, Optional, Mapping, Tuple, cast

from sretoolbox.utils import threaded
from reconcile.utils.external_resources import (
    get_external_resource_specs,
    managed_external_resources,
)


import reconcile.openshift_base as ob

from reconcile import queries
from reconcile.utils.external_resource_spec import ExternalResourceSpecInventory
from reconcile.utils import gql
from reconcile.aws_iam_keys import run as disable_keys
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.defer import defer
from reconcile.utils.oc import OC_Map
from reconcile.utils.ocm import OCMMap
from reconcile.utils.oc import StatusCodeError
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript
from reconcile.utils.terraform_client import TerraformClient as Terraform
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.vault import _VaultClient, VaultClient


TF_RESOURCE_AWS = """
output_format {
  provider
  ... on NamespaceTerraformResourceGenericSecretOutputFormat_v1 {
    data
  }
}
provider
... on NamespaceTerraformResourceRDS_v1 {
  region
  identifier
  defaults
  availability_zone
  parameter_group
  overrides
  output_resource_name
  enhanced_monitoring
  replica_source
  output_resource_db_name
  reset_password
  ca_cert {
    path
    field
    version
    format
  }
  annotations
}
... on NamespaceTerraformResourceS3_v1 {
  region
  identifier
  defaults
  overrides
  sqs_identifier
  s3_events
  event_notifications {
    destination_type
    destination
    event_type
    filter_prefix
    filter_suffix
  }
  bucket_policy
  output_resource_name
  storage_class
  annotations
}
... on NamespaceTerraformResourceElastiCache_v1 {
  identifier
  defaults
  parameter_group
  region
  overrides
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceServiceAccount_v1 {
  identifier
  variables
  policies
  user_policy
  output_resource_name
  annotations
  aws_infrastructure_access {
    cluster {
      name
    }
    access_level
    assume_role
  }
}
... on NamespaceTerraformResourceSecretsManagerServiceAccount_v1 {
  identifier
  secrets_prefix
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceRole_v1 {
  identifier
  assume_role {
    AWS
    Service
  }
  assume_condition
  inline_policy
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceSQS_v1 {
  region
  identifier
  output_resource_name
  annotations
  specs {
    defaults
    queues {
      key
      value
    }
  }
}
... on NamespaceTerraformResourceDynamoDB_v1 {
  region
  identifier
  output_resource_name
  annotations
  specs {
    defaults
    tables {
      key
      value
    }
  }
}
... on NamespaceTerraformResourceECR_v1 {
  identifier
  region
  output_resource_name
  public
  annotations
}
... on NamespaceTerraformResourceS3CloudFront_v1 {
  region
  identifier
  defaults
  output_resource_name
  storage_class
  annotations
}
... on NamespaceTerraformResourceS3SQS_v1 {
  region
  identifier
  defaults
  kms_encryption
  output_resource_name
  storage_class
  annotations
}
... on NamespaceTerraformResourceCloudWatch_v1 {
  region
  identifier
  defaults
  es_identifier
  filter_pattern
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceKMS_v1 {
  region
  identifier
  defaults
  overrides
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceElasticSearch_v1 {
  region
  identifier
  defaults
  output_resource_name
  annotations
  publish_log_types
}
... on NamespaceTerraformResourceACM_v1 {
  region
  identifier
  secret {
    path
    field
    version
    format
  }
  domain {
    domain_name
    alternate_names
  }
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceKinesis_v1 {
  region
  identifier
  defaults
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceS3CloudFrontPublicKey_v1 {
  region
  identifier
  secret {
    path
    field
    version
    format
  }
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceALB_v1 {
  region
  identifier
  vpc {
    vpc_id
    cidr_block
    subnets {
      id
    }
  }
  certificate_arn
  idle_timeout
  targets {
    name
    default
    ips
    openshift_service
  }
  rules {
    condition {
      path
      methods
    }
    action {
      target
      weight
    }
  }
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceSecretsManager_v1 {
  region
  identifier
  secret {
    path
    field
    version
    format
  }
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceASG_v1 {
  region
  identifier
  defaults
  cloudinit_configs {
    filename
    content_type
    content
  }
  variables
  image {
    tag_name
    url
    ref
    upstream {
      instance {
        token {
          path
          field
          version
          format
        }
      }
      name
    }
  }
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceRoute53Zone_v1 {
  region
  identifier
  name
  output_resource_name
  annotations
}
... on NamespaceTerraformResourceRosaAuthenticator_V1 {
  region
  identifier
  api_proxy_uri
  cognito_callback_bucket_name
  certificate_arn
  domain_name
  network_interface_ids
  openshift_ingress_load_balancer_arn
  output_resource_name
  annotations
  defaults
}
... on NamespaceTerraformResourceRosaAuthenticatorVPCE_V1 {
  region
  identifier
  subnet_ids,
  vpc_id,
  output_resource_name
  annotations
  defaults
}
"""


TF_NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    clusterAdmin
    managedExternalResources
    externalResources {
      provider
      provisioner {
        name
      }
      ... on NamespaceTerraformProviderResourceAWS_v1 {
        resources {
          %s
        }
      }
    }
    environment {
      name
    }
    app {
      name
    }
    cluster {
      name
      serverUrl
      insecureSkipTLSVerify
      jumpHost {
        hostname
        knownHosts
        user
        port
        identity {
          path
          field
          version
          format
        }
      }
      automationToken {
        path
        field
        version
        format
      }
      clusterAdminAutomationToken {
        path
        field
        version
        format
      }
      spec {
        region
      }
      internal
      disable {
        integrations
      }
    }
  }
}
""" % (
    indent(TF_RESOURCE_AWS, 6 * " "),
)

QONTRACT_INTEGRATION = "terraform_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 5, 2)
QONTRACT_TF_PREFIX = "qrtf"


def populate_oc_resources(
    spec: ob.CurrentStateSpec, ri: ResourceInventory, account_name: Optional[str]
):
    if spec.oc is None:
        return
    logging.debug(
        "[populate_oc_resources] cluster: "
        + spec.cluster
        + " namespace: "
        + spec.namespace
        + " resource: "
        + spec.kind
    )

    try:
        for item in spec.oc.get_items(spec.kind, namespace=spec.namespace):
            openshift_resource = OR(
                item, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
            )
            if account_name:
                caller = openshift_resource.caller
                if caller and caller != account_name:
                    continue

            ri.add_current(
                spec.cluster,
                spec.namespace,
                spec.kind,
                openshift_resource.name,
                openshift_resource,
            )
    except StatusCodeError as e:
        ri.register_error(cluster=spec.cluster)
        msg = "cluster: {},"
        msg += "namespace: {},"
        msg += "resource: {},"
        msg += "exception: {}"
        msg = msg.format(spec.cluster, spec.namespace, spec.kind, str(e))
        logging.error(msg)


def fetch_current_state(
    dry_run, namespaces, thread_pool_size, internal, use_jump_host, account_name
):
    ri = ResourceInventory()
    if dry_run:
        return ri, None
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(
        namespaces=namespaces,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )
    state_specs = ob.init_specs_to_fetch(
        ri, oc_map, namespaces=namespaces, override_managed_types=["Secret"]
    )
    current_state_specs: list[ob.CurrentStateSpec] = [
        s for s in state_specs if isinstance(s, ob.CurrentStateSpec)
    ]
    threaded.run(
        populate_oc_resources,
        current_state_specs,
        thread_pool_size,
        ri=ri,
        account_name=account_name,
    )

    return ri, oc_map


def init_working_dirs(
    accounts: list[dict[str, Any]],
    thread_pool_size: int,
    settings: Optional[Mapping[str, Any]] = None,
) -> tuple[Terrascript, dict[str, str]]:
    ts = Terrascript(
        QONTRACT_INTEGRATION,
        QONTRACT_TF_PREFIX,
        thread_pool_size,
        accounts,
        settings=settings,
    )
    working_dirs = ts.dump()
    return ts, working_dirs


def setup(
    dry_run: bool,
    print_to_file: str,
    thread_pool_size: int,
    internal: str,
    use_jump_host: bool,
    account_name: Optional[str],
) -> Tuple[ResourceInventory, OC_Map, Terraform, ExternalResourceSpecInventory]:
    gqlapi = gql.get_api()
    accounts = queries.get_aws_accounts(terraform_state=True)
    if account_name:
        accounts = [n for n in accounts if n["name"] == account_name]
        if not accounts:
            raise ValueError(f"aws account {account_name} is not found")
    settings = queries.get_app_interface_settings()

    # build a resource inventory for all the kube secrets managed by the
    # app-interface managed terraform resources
    namespaces = gqlapi.query(TF_NAMESPACES_QUERY)["namespaces"]
    tf_namespaces = filter_tf_namespaces(namespaces, account_name)
    ri, oc_map = fetch_current_state(
        dry_run, tf_namespaces, thread_pool_size, internal, use_jump_host, account_name
    )

    # initialize terrascript (scripting engine to generate terraform manifests)
    ts, working_dirs = init_working_dirs(accounts, thread_pool_size, settings=settings)

    # initialize terraform client
    # it is used to plan and apply according to the output of terrascript
    aws_api = AWSApi(1, accounts, settings=settings, init_users=False)
    tf = Terraform(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        QONTRACT_TF_PREFIX,
        accounts,
        working_dirs,
        thread_pool_size,
        aws_api,
    )
    clusters = [c for c in queries.get_clusters() if c.get("ocm") is not None]
    if clusters:
        ocm_map = OCMMap(
            clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
        )
    else:
        ocm_map = None
    ts.init_populate_specs(tf_namespaces, account_name)
    tf.populate_terraform_output_secrets(
        resource_specs=ts.resource_spec_inventory, init_rds_replica_source=True
    )
    ts.populate_resources(ocm_map=ocm_map)
    ts.dump(print_to_file, existing_dirs=working_dirs)

    return ri, oc_map, tf, ts.resource_spec_inventory


def filter_tf_namespaces(
    namespaces: Iterable[Mapping[str, Any]], account_name: Optional[str]
) -> list[Mapping[str, Any]]:
    tf_namespaces = []
    for namespace_info in namespaces:
        if not managed_external_resources(namespace_info):
            continue

        if not account_name:
            tf_namespaces.append(namespace_info)
            continue

        specs = get_external_resource_specs(namespace_info)
        if not specs:
            tf_namespaces.append(namespace_info)
            continue

        for spec in specs:
            if spec.provisioner_name == account_name:
                tf_namespaces.append(namespace_info)
                break

    return tf_namespaces


def cleanup_and_exit(tf=None, status=False, working_dirs=None):
    if working_dirs is None:
        working_dirs = {}
    if tf is None:
        for wd in working_dirs.values():
            shutil.rmtree(wd)
    else:
        tf.cleanup()
    sys.exit(status)


def write_outputs_to_vault(
    vault_path: str, resource_specs: ExternalResourceSpecInventory
) -> None:
    integration_name = QONTRACT_INTEGRATION.replace("_", "-")
    vault_client = cast(_VaultClient, VaultClient())
    for spec in resource_specs.values():
        # a secret can be empty if the terraform-integration is not enabled on the cluster
        # the resource is defined on - lets skip vault writes for those right now and
        # give this more thought - e.g. not processing such specs at all when the integration
        # is disabled
        if spec.secret:
            secret_path = f"{vault_path}/{integration_name}/{spec.cluster_name}/{spec.namespace_name}/{spec.output_resource_name}"
            # vault only stores strings as values - by converting to str upfront, we can compare current to desired
            stringified_secret = {k: str(v) for k, v in spec.secret.items()}
            desired_secret = {"path": secret_path, "data": stringified_secret}
            vault_client.write(desired_secret, decode_base64=False)


def populate_desired_state(
    ri: ResourceInventory, resource_specs: ExternalResourceSpecInventory
) -> None:
    for spec in resource_specs.values():
        if ri.is_cluster_present(spec.cluster_name):
            oc_resource = spec.build_oc_secret(
                QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
            )
            ri.add_desired(
                cluster=spec.cluster_name,
                namespace=spec.namespace_name,
                resource_type=oc_resource.kind,
                name=spec.output_resource_name,
                value=oc_resource,
                privileged=spec.namespace.get("clusterAdmin") or False,
            )


@defer
def run(
    dry_run,
    print_to_file=None,
    enable_deletion=False,
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    light=False,
    vault_output_path="",
    account_name=None,
    defer=None,
):

    ri, oc_map, tf, resource_specs = setup(
        dry_run,
        print_to_file,
        thread_pool_size,
        internal,
        use_jump_host,
        account_name,
    )

    if not dry_run:
        defer(oc_map.cleanup)

    if print_to_file:
        cleanup_and_exit(tf)
    if tf is None:
        err = True
        cleanup_and_exit(tf, err)

    if not light:
        disabled_deletions_detected, err = tf.plan(enable_deletion)
        if err:
            cleanup_and_exit(tf, err)
        if disabled_deletions_detected:
            cleanup_and_exit(tf, disabled_deletions_detected)

    if dry_run:
        cleanup_and_exit(tf)

    if not light and tf.should_apply:
        err = tf.apply()
        if err:
            cleanup_and_exit(tf, err)

    # refresh output data after terraform apply
    tf.populate_terraform_output_secrets(
        resource_specs=resource_specs, init_rds_replica_source=True
    )
    # populate the resource inventory with latest output data
    populate_desired_state(ri, resource_specs)

    actions = ob.realize_data(
        dry_run, oc_map, ri, thread_pool_size, caller=account_name
    )

    if not light and tf.should_apply:
        disable_keys(
            dry_run,
            thread_pool_size,
            disable_service_account_keys=True,
            account_name=account_name,
        )

    if actions and vault_output_path:
        write_outputs_to_vault(vault_output_path, resource_specs)

    if ri.has_error_registered():
        err = True
        cleanup_and_exit(tf, err)

    cleanup_and_exit(tf)
