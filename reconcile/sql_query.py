import logging
import sys
import time
from collections.abc import (
    Iterable,
    Mapping,
)
from textwrap import indent
from typing import (
    Any,
    Optional,
    Union,
)

import jinja2
from ruamel import yaml

from reconcile import openshift_base
from reconcile import openshift_resources_base as orb
from reconcile import (
    queries,
    typed_queries,
)
from reconcile.status import ExitCodes
from reconcile.utils.external_resources import get_external_resource_specs
from reconcile.utils.oc import (
    OC_Map,
    StatusCodeError,
)
from reconcile.utils.openshift_resource import OpenshiftResource
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.smtp_client import (
    DEFAULT_SMTP_TIMEOUT,
    SmtpClient,
    get_smtp_server_connection,
)
from reconcile.utils.state import State
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript

QONTRACT_INTEGRATION = "sql-query"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 1, 0)

LOG = logging.getLogger(__name__)

JOB_TTL = 604800  # 7 days
POD_TTL = 3600  # 1 hour (used only when output is "filesystem")
QUERY_CONFIG_MAP_CHUNK_SIZE = 512 * 1024  # 512 KB

REQUESTS_MEM = "128Mi"
REQUESTS_CPU = "100m"
LIMITS_MEM = "512Mi"
LIMITS_CPU = "1"

CONFIG_MAPS_MOUNT_PATH = "/configs"
GPG_KEY_NAME = "gpg-key"
GPG_KEY_PATH = f"{CONFIG_MAPS_MOUNT_PATH}/{GPG_KEY_NAME}"

JOB_SPEC = """
spec:
  template:
    metadata:
      name: {{ JOB_NAME }}
    spec:
      {% if PULL_SECRET is not none %}
      imagePullSecrets:
      - name: {{ PULL_SECRET }}
      {% endif %}
      restartPolicy: Never
      serviceAccountName: {{ SVC_NAME }}
      containers:
      - name: {{ JOB_NAME }}
        image: {{ IMAGE_REPOSITORY }}/{{ ENGINE }}:{{ENGINE_VERSION}}
        command:
          - /bin/bash
        args:
          - '-c'
          - '{{ COMMAND }}'
        env:
          {% for key, value in DB_CONN.items() %}
          {% if value is none %}
          # When value is not provided, we get it from the secret
          - name: {{ key }}
            valueFrom:
              secretKeyRef:
                name: {{ SECRET_NAME }}
                key: {{ key }}
          {% else %}
          # When value is provided, we get just use it
          - name: {{ key }}
            value: {{ value }}
          {% endif %}
          {% endfor %}
        resources:
          requests:
            memory: "{{ REQUESTS_MEM }}"
            cpu: "{{ REQUESTS_CPU }}"
          limits:
            memory: "{{ LIMITS_MEM }}"
            cpu: "{{ LIMITS_CPU }}"
        volumeMounts:
        - name: configs
          mountPath: {{ CONFIG_MAPS_MOUNT_PATH }}
          readOnly: true
      volumes:
        - name: configs
          projected:
            sources:
            {% for cm in CONFIG_MAPS %}
            - configMap:
                name: {{ cm }}
          {% endfor %}
"""


JOB_TEMPLATE = """
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ JOB_NAME }}
  labels:
    app: qontract-reconcile
    integration: {{ QONTRACT_INTEGRATION }}
    query-name: {{ QUERY_NAME }}
%s
""" % (
    JOB_SPEC
)


CRONJOB_TEMPLATE = """
apiVersion: batch/v1beta1
kind: CronJob
metadata:
  name: {{ JOB_NAME }}
  labels:
    app: qontract-reconcile
    integration: {{ QONTRACT_INTEGRATION }}
    query-name: {{ QUERY_NAME }}
spec:
  schedule: "{{ SCHEDULE }}"
  concurrencyPolicy: "Forbid"
  jobTemplate:
    %s
""" % (
    indent(JOB_SPEC, 4 * " ")
)


def get_tf_resource_info(
    terrascript: Terrascript, namespace: Mapping[str, Any], identifier: str
) -> Union[dict[str, str], None]:
    """
    Extracting the external resources information from the namespace
    for a given identifier

    :param namespace: the namespace dictionary
    :param identifier: the identifier we are looking for
    :return: the terraform resource information dictionary
    """
    specs = get_external_resource_specs(namespace)
    for spec in specs:
        if spec.provider != "rds":
            continue

        if spec.identifier != identifier:
            continue

        values = terrascript.init_values(spec)

        return {
            "cluster": spec.cluster_name,
            "output_resource_name": spec.output_resource_name,
            "engine": values.get("engine", "postgres"),
            "engine_version": values.get("engine_version", "latest"),
        }
    return None


def collect_queries(
    settings: dict[str, Any], smtp_client: SmtpClient, query_name: Optional[str] = None
) -> list[dict[str, Any]]:
    """
    Consults the app-interface and constructs the list of queries
    to be executed.

    :param query_name: (optional) query to look for
    :param settings: App Interface settings

    :return: List of queries dictionaries
    """
    queries_list: list[dict[str, Any]] = []

    # Items to be either overridden ot taken from the k8s secret
    db_conn_items = {
        "db.host": None,
        "db.name": None,
        "db.password": None,
        "db.port": None,
        "db.user": None,
    }

    sql_queries = queries.get_app_interface_sql_queries()
    # initiating terrascript with an empty list of accounts,
    # as we are not really initiating terraform configuration
    # but only using inner functions.
    terrascript = Terrascript(
        QONTRACT_INTEGRATION,
        "",
        1,
        accounts=[],
        settings=settings,
        prefetch_resources_by_schemas=["/aws/rds-defaults-1.yml"],
    )

    for sql_query in sql_queries:
        name = sql_query["name"]

        for existing in queries_list:
            if existing["name"] == name:
                logging.error(["SQL-Query %s defined more than once"], name)
                sys.exit(ExitCodes.ERROR)

        # Looking for a specific query
        if query_name is not None:
            if name != query_name:
                continue

        namespace = sql_query["namespace"]
        identifier = sql_query["identifier"]

        # Due to an API limitation, the keys are coming with underscore
        # instead of period, so we are using this unpacking routine
        # to also replace "_" by "." in the keys
        if sql_query["overrides"] is not None:
            overrides = {
                key.replace("_", "."): value
                for key, value in sql_query["overrides"].items()
                if value is not None
            }
        else:
            overrides = {}

        # Merging the overrides. Values that are still None after this
        # will be taken from the k8s secret on template rendering
        db_conn = {**db_conn_items, **overrides}

        # Output can be:
        # - stdout
        # - filesystem
        # - encrypted
        output = sql_query["output"]
        if output is None:
            output = "stdout"
        elif output == "encrypted":
            requestor = sql_query.get("requestor")
            if requestor is None:
                logging.error("a requestor is required to get encrypted output")
                sys.exit(ExitCodes.ERROR)
            public_gpg_key = requestor.get("public_gpg_key")
            user_name = requestor.get("org_username")
            if public_gpg_key is None:
                logging.error(["user %s does not have a public gpg key"], user_name)
                sys.exit(ExitCodes.ERROR)

        # Extracting the external resources information from the namespace
        # for the given identifier
        tf_resource_info = get_tf_resource_info(terrascript, namespace, identifier)
        if tf_resource_info is None:
            logging.error(
                ["Could not find rds identifier %s in namespace %s"],
                identifier,
                namespace["name"],
            )
            sys.exit(ExitCodes.ERROR)

        _queries = []
        if sql_query["query"] is not None:
            _queries.append(sql_query["query"])

        if sql_query["queries"] is not None:
            _queries.extend(sql_query["queries"])

        # building up the final query dictionary
        item = {
            "name": name,
            "namespace": namespace,
            "identifier": sql_query["identifier"],
            "db_conn": db_conn,
            "output": output,
            "queries": _queries,
            **tf_resource_info,
        }

        if output == "encrypted":
            item["recipient"] = smtp_client.get_recipient(
                sql_query["requestor"]["org_username"]
            )
            item["public_gpg_key"] = sql_query["requestor"]["public_gpg_key"].replace(
                "\n", ""
            )

        # If schedule is defined
        # this should be a CronJob
        schedule = sql_query.get("schedule")
        if schedule:
            item["schedule"] = schedule

        # Logic to allow users to delete cronjobs
        delete = sql_query.get("delete")
        if delete:
            item["delete"] = delete

        queries_list.append(item)

    return queries_list


def make_postgres_command(sqlqueries_file: str) -> str:
    command = [
        "(time PGPASSWORD=''$(db.password)''",
        "psql",
        "--host=$(db.host)",
        "--port=$(db.port)",
        "--username=$(db.user)",
        "--dbname=$(db.name)",
        f'--file="{sqlqueries_file}")',
    ]
    return " ".join(command)


def make_mysql_command(sqlqueries_file: str) -> str:
    command = [
        "(time mysql",
        "--host=$(db.host)",
        "--port=$(db.port)",
        "--database=$(db.name)",
        "--user=$(db.user)",
        "--password=''$(db.password)''",
        f' < "{sqlqueries_file}")',
    ]
    return " ".join(command)


def make_output_cmd(output: str, recipient: str) -> str:
    if output in ("filesystem", "encrypted"):
        command = filesystem_redir_stdout()
    else:
        # stdout
        command = [";"]

    if output == "filesystem":
        command += filesystem_closing_message()
    if output == "encrypted":
        command += encrypted_closing_message(recipient=recipient)

    return " ".join(command)


def filesystem_redir_stdout() -> list[str]:
    return [
        " &>> /tmp/query-result.txt;",
    ]


def filesystem_closing_message() -> list[str]:
    return [
        "echo;",
        "echo Get the sql-query results with:;",
        "echo;",
        "echo  oc cp ${HOSTNAME}:tmp/query-result.txt ",
        "${HOSTNAME}-query-result.txt;",
        "echo;",
        f"echo Sleeping {POD_TTL}s...;",
        f"sleep {POD_TTL};",
    ]


def encrypted_closing_message(recipient: str) -> list[str]:
    return [
        f"cat {GPG_KEY_PATH} | base64 --decode | ",
        "gpg --homedir /tmp/.gnupg --import;",
        "gpg --trust-model always --homedir /tmp/.gnupg --armor -r ",
        recipient,
        " --encrypt /tmp/query-result.txt;",
        "rm /tmp/query-result.txt;",
        "echo;",
        "echo Get the sql-query results with:;",
        "echo;",
        r"echo cat \<\<EOF \> ${HOSTNAME}-query-result.txt;",
        "cat /tmp/query-result.txt.asc;",
        "echo EOF;",
        "echo gpg -d ${HOSTNAME}-query-result.txt;",
    ]


def process_template(
    query: dict[str, Any],
    image_repository: str,
    use_pull_secret: bool,
    config_map_names: list[str],
    service_account_name: str,
) -> str:
    """
    Renders the Jinja2 Job Template.

    :param query: the query dictionary containing the parameters
                  to be used in the Template
    :param image_repository: docker image repo url
    :param use_pull_secret: add imagePullSecrets to Job
    :param config_map_names: ConfigMap names to mount in Job

    :return: rendered Job YAML
    """
    engine_cmd_map = {"postgres": make_postgres_command, "mysql": make_mysql_command}

    engine = query["engine"]
    if engine not in engine_cmd_map:
        raise RuntimeError(f"Engine {engine} not supported")

    supported_outputs = ["stdout", "filesystem", "encrypted"]
    output = query["output"]
    if output not in supported_outputs:
        raise RuntimeError(f"Output {output} not supported")

    # concatenate all query files into a single one
    command = (
        merge_files_command(
            directory=CONFIG_MAPS_MOUNT_PATH,
            file_glob="q*",
            output_file="/tmp/queries",
        )
        + ";"
    )
    command += engine_cmd_map[engine](sqlqueries_file="/tmp/queries")
    command += make_output_cmd(output=output, recipient=query.get("recipient", ""))

    template_to_render = JOB_TEMPLATE
    render_kwargs = {
        "JOB_NAME": query["name"],
        "CONFIG_MAPS_MOUNT_PATH": CONFIG_MAPS_MOUNT_PATH,
        "QUERY_NAME": query["name"],
        "QONTRACT_INTEGRATION": QONTRACT_INTEGRATION,
        "IMAGE_REPOSITORY": image_repository,
        "SECRET_NAME": query["output_resource_name"],
        "ENGINE": engine,
        "ENGINE_VERSION": query["engine_version"],
        "DB_CONN": query["db_conn"],
        "CONFIG_MAPS": config_map_names,
        "COMMAND": command,
        "SVC_NAME": service_account_name,
        "REQUESTS_MEM": REQUESTS_MEM,
        "REQUESTS_CPU": REQUESTS_CPU,
        "LIMITS_MEM": LIMITS_MEM,
        "LIMITS_CPU": LIMITS_CPU,
    }
    if use_pull_secret:
        render_kwargs["PULL_SECRET"] = query["name"]

    schedule = query.get("schedule")
    if schedule:
        template_to_render = CRONJOB_TEMPLATE
        render_kwargs["SCHEDULE"] = schedule

    template = jinja2.Template(template_to_render)
    job_yaml = template.render(render_kwargs)
    return job_yaml


def get_config_map(name: str, data: dict, labels: dict) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "labels": labels,
        },
        "data": data,
    }


def get_service_account(name: str, labels: dict) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": name,
            "labels": labels,
        },
        "automountServiceAccountToken": False,
    }


def split_long_query(q, size) -> list[str]:
    return [q[i : i + size] for i in range(0, len(q), size)]


def merge_files_command(directory, file_glob, output_file):
    return f"cat ''{directory}''/{file_glob} > ''{output_file}''"


def openshift_apply(
    dry_run: bool,
    oc_map: OC_Map,
    cluster: str,
    namespace: str,
    resources: Iterable[OpenshiftResource],
) -> None:
    for resource in resources:
        openshift_base.apply(
            dry_run=dry_run,
            oc_map=oc_map,
            cluster=cluster,
            namespace=namespace,
            resource_type=resource.kind,
            resource=resource,
            wait_for_namespace=False,
        )


def openshift_delete_by_label(
    dry_run: bool,
    oc_map: OC_Map,
    cluster: str,
    namespace: str,
    kinds: list[str],
    labels: dict[str, str],
    enable_deletion: bool,
) -> None:
    oc = oc_map.get_cluster(cluster)
    resources: list[OpenshiftResource] = [
        OpenshiftResource(
            body=item,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
        )
        for kind in kinds
        for item in oc.get_items(kind=kind, namespace=namespace, labels=labels)
    ]

    for resource in resources:
        try:
            openshift_base.delete(
                dry_run=dry_run,
                oc_map=oc_map,
                cluster=cluster,
                namespace=namespace,
                resource_type=resource.kind,
                name=resource.name,
                enable_deletion=enable_deletion,
            )
        except StatusCodeError:
            LOG.exception(
                f"Error removing ['{cluster}' '{namespace}' '{resource.kind}' '{resource.name}']"
            )


def run(dry_run: bool, enable_deletion: bool = False) -> None:
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )
    smtp_settings = typed_queries.smtp.settings()
    smtp_client = SmtpClient(
        server=get_smtp_server_connection(
            secret_reader=SecretReader(settings=queries.get_secret_reader_settings()),
            secret=smtp_settings.credentials,
        ),
        mail_address=smtp_settings.mail_address,
        timeout=smtp_settings.timeout or DEFAULT_SMTP_TIMEOUT,
    )
    image_repository = "quay.io/app-sre"

    sql_query_settings = settings.get("sqlQuery")
    pull_secret: dict[str, Any] = {}
    if sql_query_settings:
        image_repository = sql_query_settings["imageRepository"]
        pull_secret = sql_query_settings["pullSecret"]
    use_pull_secret = True if pull_secret else False

    queries_list = collect_queries(settings=settings, smtp_client=smtp_client)
    query_states = [s.lstrip("/") for s in state.ls()]
    for query in queries_list:
        openshift_resources: list[OpenshiftResource] = []
        query_name = query["name"]
        common_resource_labels = {
            "app": "qontract-reconcile",
            "integration": QONTRACT_INTEGRATION,
            "query-name": query_name,
        }
        if query_name in query_states:
            # Query already executed. Now check current state:
            # - State is a timestamp: executed and up for removal after the JOB_TTL
            # - State is not 'DONE' but 'delete:true' and is a cronjob: up for removal
            # - State is 'DONE': executed and removed. Nothing to do here.
            cleanup = False
            query_state = state[query_name]
            if query_state == "DONE":
                # nothing to do anymore
                continue

            if query.get("schedule"):
                # CronJob
                if query.get("delete"):
                    cleanup = True
            else:
                # Job
                if time.time() >= query_state + JOB_TTL:
                    cleanup = True

            if cleanup:
                oc_map = OC_Map(
                    namespaces=[query["namespace"]],
                    integration=QONTRACT_INTEGRATION,
                    settings=settings,
                )
                openshift_delete_by_label(
                    dry_run=dry_run,
                    oc_map=oc_map,
                    cluster=query["cluster"],
                    namespace=query["namespace"]["name"],
                    kinds=["Job", "CronJob", "ConfigMap", "Secret", "ServiceAccount"],
                    labels=common_resource_labels,
                    enable_deletion=enable_deletion,
                )
                if not dry_run and enable_deletion:
                    state[query_name] = "DONE"

            # continue with next query
            continue

        # New query
        if use_pull_secret:
            labels = pull_secret["labels"] or {}
            labels.update(common_resource_labels)
            secret_resource = orb.fetch_provider_vault_secret(
                path=pull_secret["path"],
                version=pull_secret["version"],
                name=query_name,
                labels=labels,
                annotations=pull_secret["annotations"] or {},
                type=pull_secret["type"],
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
                settings=settings,
            )
            openshift_resources.append(secret_resource)

        # ConfigMap gpg
        config_map_resources = [
            get_config_map(
                name=f"{query_name}-{GPG_KEY_NAME}",
                data={GPG_KEY_NAME: query.get("public_gpg_key", "")},
                labels=common_resource_labels,
            )
        ]
        # ConfigMaps with SQL queries chunked into smaller pieces
        config_map_resources += [
            get_config_map(
                name=f"{query_name}-q{i:05d}c{j:05d}",
                data={f"q{i:05d}c{j:05d}": chunk},
                labels=common_resource_labels,
            )
            for i, q in enumerate(query["queries"])
            for j, chunk in enumerate(
                split_long_query(q, size=QUERY_CONFIG_MAP_CHUNK_SIZE)
            )
        ]
        openshift_resources += [
            OpenshiftResource(
                body=cm,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
            for cm in config_map_resources
        ]

        # ServiceAccount
        svc = get_service_account(query_name, labels=common_resource_labels)
        openshift_resources.append(
            OpenshiftResource(
                body=svc,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
        )

        # Job (sql executer)
        job_yaml = process_template(
            query,
            image_repository=image_repository,
            use_pull_secret=use_pull_secret,
            config_map_names=[cm["metadata"]["name"] for cm in config_map_resources],
            service_account_name=svc["metadata"]["name"],
        )
        openshift_resources.append(
            OpenshiftResource(
                body=yaml.safe_load(job_yaml),
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
        )

        oc_map = OC_Map(
            namespaces=[query["namespace"]],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
        )

        openshift_apply(
            dry_run=dry_run,
            oc_map=oc_map,
            cluster=query["cluster"],
            namespace=query["namespace"]["name"],
            resources=openshift_resources,
        )

        if not dry_run:
            state[query_name] = time.time()
