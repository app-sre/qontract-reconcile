import logging
import sys
import time

from textwrap import indent

import jinja2
from ruamel import yaml

from reconcile import openshift_base
from reconcile import openshift_resources_base as orb
from reconcile import queries
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.oc import OC_Map
from reconcile.utils.oc import StatusCodeError
from reconcile.utils.openshift_resource import OpenshiftResource
from reconcile.utils.smtp_client import SmtpClient
from reconcile.utils.state import State
from reconcile.status import ExitCodes
from reconcile.utils.terrascript_client import TerrascriptClient as Terrascript


QONTRACT_INTEGRATION = "sql-query"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 1, 0)

LOG = logging.getLogger(__name__)

JOB_TTL = 604800  # 7 days
POD_TTL = 3600  # 1 hour (used only when output is "filesystem")

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
      {% if GPG_KEY is defined %}
        volumeMounts:
        - name: gpg-key
          mountPath: /gpg
      volumes:
      - name: gpg-key
        configMap:
          name: {{ GPG_KEY }}
      {% endif %}
      restartPolicy: Never
"""


JOB_TEMPLATE = """
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ JOB_NAME }}
%s
""" % (
    JOB_SPEC
)


CRONJOB_TEMPLATE = """
apiVersion: batch/v1beta1
kind: CronJob
metadata:
  name: {{ JOB_NAME }}
spec:
  schedule: "{{ SCHEDULE }}"
  concurrencyPolicy: "Forbid"
  jobTemplate:
    %s
""" % (
    indent(JOB_SPEC, 4 * " ")
)


CONFIGMAP_TEMPLATE = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ GPG_KEY }}
data:
  gpg-key: {{ PUBLIC_GPG_KEY }}
"""


def get_tf_resource_info(terrascript: Terrascript, namespace, identifier):
    """
    Extracting the terraformResources information from the namespace
    for a given identifier

    :param namespace: the namespace dictionary
    :param identifier: the identifier we are looking for
    :return: the terraform resource information dictionary
    """
    tf_resources = namespace["terraformResources"]
    for tf_resource in tf_resources:
        if "identifier" not in tf_resource:
            continue

        if tf_resource["identifier"] != identifier:
            continue

        if tf_resource["provider"] != "rds":
            continue

        _, _, values, _, output_resource_name, _ = terrascript.init_values(
            tf_resource, namespace
        )

        return {
            "cluster": namespace["cluster"]["name"],
            "output_resource_name": output_resource_name,
            "engine": values.get("engine", "postgres"),
            "engine_version": values.get("engine_version", "latest"),
        }


def collect_queries(query_name=None, settings=None):
    """
    Consults the app-interface and constructs the list of queries
    to be executed.

    :param query_name: (optional) query to look for
    :param settings: App Interface settings

    :return: List of queries dictionaries
    """
    queries_list = []

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
        QONTRACT_INTEGRATION, "", 1, accounts=[], settings=settings
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

        # Extracting the terraformResources information from the namespace
        # fo the given identifier
        tf_resource_info = get_tf_resource_info(terrascript, namespace, identifier)
        if tf_resource_info is None:
            logging.error(
                ["Could not find rds identifier %s in namespace %s"],
                identifier,
                namespace["name"],
            )
            sys.exit(ExitCodes.ERROR)

        sql_queries = []
        if sql_query["query"] is not None:
            sql_queries.append(sql_query["query"])

        if sql_query["queries"] is not None:
            sql_queries.extend(sql_query["queries"])

        sql_queries = [item.replace("'", "''") for item in sql_queries]

        # building up the final query dictionary
        item = {
            "name": name,
            "namespace": namespace,
            "identifier": sql_query["identifier"],
            "db_conn": db_conn,
            "output": output,
            "queries": sql_queries,
            **tf_resource_info,
        }

        if output == "encrypted":
            smtp_client = SmtpClient(settings=settings)
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

        queries_list.append(item)

    return queries_list


def make_postgres_command(output, sqlqueries, recipient=None):
    command = []
    for query in sqlqueries:
        command.extend(
            [
                "(time PGPASSWORD=''$(db.password)''",
                "psql",
                "--host=$(db.host)",
                "--port=$(db.port)",
                "--username=$(db.user)",
                "--dbname=$(db.name)",
                f'--command "{query}")',
            ]
        )

        if output in ("filesystem", "encrypted"):
            command.extend(filesystem_redir_stdout())
        else:
            command.append(";")

    if output == "filesystem":
        command.extend(filesystem_closing_message())
    if output == "encrypted":
        command.extend(encrypted_closing_message(recipient=recipient))

    return " ".join(command)


def make_mysql_command(output, sqlqueries, recipient=None):
    command = []
    for query in sqlqueries:
        command.extend(
            [
                "(time mysql",
                "--host=$(db.host)",
                "--port=$(db.port)",
                "--database=$(db.name)",
                "--user=$(db.user)",
                "--password=''$(db.password)''",
                f'--execute="{query}")',
            ]
        )

        if output in ("filesystem", "encrypted"):
            command.extend(filesystem_redir_stdout())
        else:
            command.append(";")

    if output == "filesystem":
        command.extend(filesystem_closing_message())
    if output == "encrypted":
        command.extend(encrypted_closing_message(recipient=recipient))

    return " ".join(command)


def filesystem_redir_stdout():
    return [
        " &>> /tmp/query-result.txt;",
    ]


def filesystem_closing_message():
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


def encrypted_closing_message(recipient):
    return [
        "cat /gpg/gpg-key | base64 --decode | ",
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


def process_template(query, image_repository, use_pull_secret=False):
    """
    Renders the Jinja2 Job Template.

    :param query: the query dictionary containing the parameters
                  to be used in the Template
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

    make_command = engine_cmd_map[engine]

    command = make_command(
        output=output, sqlqueries=query["queries"], recipient=query.get("recipient")
    )

    template_to_render = JOB_TEMPLATE
    render_kwargs = {
        "JOB_NAME": query["name"],
        "IMAGE_REPOSITORY": image_repository,
        "SECRET_NAME": query["output_resource_name"],
        "ENGINE": engine,
        "ENGINE_VERSION": query["engine_version"],
        "DB_CONN": query["db_conn"],
        "COMMAND": command,
    }
    if use_pull_secret:
        render_kwargs["PULL_SECRET"] = query["name"]
    if output == "encrypted":
        render_kwargs["GPG_KEY"] = query["name"]
    schedule = query.get("schedule")
    if schedule:
        template_to_render = CRONJOB_TEMPLATE
        render_kwargs["SCHEDULE"] = schedule

    template = jinja2.Template(template_to_render)
    job_yaml = template.render(**render_kwargs)
    return job_yaml


def openshift_apply(dry_run, oc_map, query, resource):
    openshift_base.apply(
        dry_run=dry_run,
        oc_map=oc_map,
        cluster=query["cluster"],
        namespace=query["namespace"]["name"],
        resource_type=resource.kind,
        resource=resource,
        wait_for_namespace=False,
    )


def openshift_delete(dry_run, oc_map, query, resource_type, enable_deletion):
    try:
        openshift_base.delete(
            dry_run=dry_run,
            oc_map=oc_map,
            cluster=query["cluster"],
            namespace=query["namespace"]["name"],
            resource_type=resource_type,
            name=query["name"],
            enable_deletion=enable_deletion,
        )
    except StatusCodeError:
        LOG.exception(
            "Error removing ['%s' '%s' '%s' '%s']",
            query["cluster"],
            query["namespace"]["name"],
            resource_type,
            query["name"],
        )


def run(dry_run, enable_deletion=False):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )

    queries_list = collect_queries(settings=settings)
    remove_candidates = []
    for query in queries_list:
        query_name = query["name"]

        # Checking the sql-query state:
        # - No state: up for execution.
        # - State is a timestamp: executed and up for removal
        #   after the JOB_TTL
        # - State is 'DONE': executed and removed.
        try:
            query_state = state[query_name]
            is_cronjob = query.get("schedule")
            if query_state != "DONE" and not is_cronjob:
                remove_candidates.append(
                    {
                        "name": query_name,
                        "timestamp": query_state,
                        "output": query["output"],
                    }
                )
            continue
        except KeyError:
            pass

        image_repository = "quay.io/app-sre"
        use_pull_secret = False
        sql_query_settings = settings.get("sqlQuery")
        if sql_query_settings:
            use_pull_secret = True
            image_repository = sql_query_settings["imageRepository"]
            pull_secret = sql_query_settings["pullSecret"]
            secret_resource = orb.fetch_provider_vault_secret(
                path=pull_secret["path"],
                version=pull_secret["version"],
                name=query_name,
                labels=pull_secret["labels"] or {},
                annotations=pull_secret["annotations"] or {},
                type=pull_secret["type"],
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )

        job_yaml = process_template(
            query, image_repository=image_repository, use_pull_secret=use_pull_secret
        )
        job = yaml.safe_load(job_yaml)
        job_resource = OpenshiftResource(
            job, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )
        oc_map = OC_Map(
            namespaces=[query["namespace"]],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            internal=None,
        )

        if use_pull_secret:
            openshift_apply(dry_run, oc_map, query, secret_resource)

        if query["output"] == "encrypted":
            render_kwargs = {
                "GPG_KEY": query["name"],
                "PUBLIC_GPG_KEY": query["public_gpg_key"],
            }
            template = jinja2.Template(CONFIGMAP_TEMPLATE)
            configmap_yaml = template.render(**render_kwargs)
            configmap = yaml.safe_load(configmap_yaml)
            configmap_resource = OpenshiftResource(
                configmap, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
            )
            openshift_apply(dry_run, oc_map, query, configmap_resource)

        openshift_apply(dry_run, oc_map, query, job_resource)

        if not dry_run:
            state[query_name] = time.time()

    for candidate in remove_candidates:
        if time.time() < candidate["timestamp"] + JOB_TTL:
            continue

        try:
            query = collect_queries(query_name=candidate["name"], settings=settings)[0]
        except IndexError:
            raise RuntimeError(
                f'sql-query {candidate["name"]} not present'
                f"in the app-interface while its Job is still "
                f"not removed from the cluster. Manual clean "
                f"up is needed."
            )

        oc_map = OC_Map(
            namespaces=[query["namespace"]],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            internal=None,
        )

        resource_types = ["Job", "Secret"]
        if candidate["output"] == "encrypted":
            resource_types.append("ConfigMap")
        for resource_type in resource_types:
            openshift_delete(dry_run, oc_map, query, resource_type, enable_deletion)

        if not dry_run:
            state[candidate["name"]] = "DONE"
