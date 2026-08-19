from __future__ import annotations

import base64
import json
import logging
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.error import URLError

from pydantic import BaseModel
from sretoolbox.utils import retry

import reconcile.gql_definitions.openshift_cluster_bots.clusters as clusters_gql
from reconcile import mr_client_gateway, queries
from reconcile.gql_definitions.openshift_cluster_bots.clusters import (
    AutomationTokenEntryV1,
    ClusterV1_AutomationTokenEntryV1,
)

# qenerate emits separate classes when the same type appears under different parent
# fields in the same query. Both are structurally identical so all helpers accept either.
AnyTokenEntry = AutomationTokenEntryV1 | ClusterV1_AutomationTokenEntryV1
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.json import json_dumps
from reconcile.utils.mr import clusters_updates
from reconcile.utils.oc_connection_parameters import is_active_token_entry
from reconcile.utils.ocm import OCM, OCMMap
from reconcile.utils.openshift_resource import (
    QONTRACT_ANNOTATION_INTEGRATION,
    QONTRACT_ANNOTATION_INTEGRATION_VERSION,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import VaultClient

if TYPE_CHECKING:
    from collections.abc import Sequence

    from reconcile.gql_definitions.openshift_cluster_bots.clusters import ClusterV1

QONTRACT_INTEGRATION = "openshift-cluster-bots"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

# Label identifying a K8s secret as managed by this integration (value is the SA name).
MANAGED_LABEL_KEY = "qontract.integration/serviceaccount"
# Annotation recording the Vault path a managed secret has been written to.
VAULT_PATH_ANNOTATION_KEY = "qontract.integration/vault-path"


class Config(BaseModel):
    gitlab_project_id: str
    vault_creds_path: str
    dedicated_admin_ns: str
    dedicated_admin_sa: str
    cluster_admin_ns: str
    cluster_admin_sa: str
    dry_run: bool


def _has_active_token_with_secret(entries: Sequence[AnyTokenEntry] | None) -> bool:
    if not entries:
        return False
    return any(is_active_token_entry(e) for e in entries)


def cluster_misses_bot_tokens(cluster: ClusterV1) -> bool:
    # TODO(APPSRE-13941): simplify to just _has_active_token_with_secret() once all clusters migrated
    has_da_token = (
        cluster.automation_token is not None
        or _has_active_token_with_secret(cluster.automation_tokens)
    )
    if not has_da_token:
        return True
    if cluster.cluster_admin is True:
        # TODO(APPSRE-13941): simplify once clusterAdminAutomationToken singular field is removed
        return (
            cluster.cluster_admin_automation_token is None
            and not _has_active_token_with_secret(
                cluster.cluster_admin_automation_tokens
            )
        )
    return False


def cluster_is_reachable(cluster: ClusterV1) -> bool:
    if not cluster.server_url:
        return False
    # https://kubernetes.io/docs/reference/using-api/health-checks/
    url = f"{cluster.server_url}/readyz"
    try:
        res = urllib.request.urlopen(url, timeout=10)
        return res is not None and res.getcode() == 200
    except URLError as e:
        logging.debug(f"[{cluster.name}] API URL unreachable: {e.reason}")
        return False


def vault_secret(
    cluster: ClusterV1, config: Config, cluster_admin: bool = False
) -> dict[str, str]:
    secret_key = f"{config.vault_creds_path}/{cluster.name}"
    if cluster_admin:
        secret_key = f"{secret_key}-cluster-admin"
    return {
        "path": secret_key,
        "field": "token",
    }


def vault_data(
    cluster: ClusterV1, config: Config, token: str, cluster_admin: bool
) -> dict[str, str]:
    username = f"{config.dedicated_admin_ns}/{config.dedicated_admin_sa} # not used by automation"
    if cluster_admin:
        username = f"{config.cluster_admin_ns}/{config.cluster_admin_sa} # not used by automation"
    return {
        "server": cluster.server_url,
        "token": token,
        "username": username,
    }


def get_sa_name(config: Config, cluster_admin: bool) -> str:
    return config.cluster_admin_sa if cluster_admin else config.dedicated_admin_sa


def vault_secret_for_entry(
    cluster_name: str, config: Config, entry: AnyTokenEntry
) -> dict[str, str]:
    return {
        "path": f"{config.vault_creds_path}/{cluster_name}/{entry.namespace}/{entry.name}",
        "field": "token",
    }


def vault_data_for_entry(
    cluster: ClusterV1, token: str, sa_name: str, namespace: str
) -> dict[str, str]:
    return {
        "server": cluster.server_url,
        "token": token,
        "username": f"{namespace}/{sa_name} # not used by automation",
    }


# We're not using the generic OC classes here because we use a kubeconfig instead of a token
# Since that is very exceptional and should be done only in this context, it is preferable to
# not update the generic client implementations.
def oc(
    kubeconfig: str,
    namespace: str,
    command: list[str],
    stdin: bytes | None = None,
    output_json: bool = True,
) -> dict | None:
    output_flags = ["-o", "json"] if output_json else []
    ret = subprocess.run(
        ["oc", "--kubeconfig", kubeconfig, "-n", namespace, *output_flags, *command],
        input=stdin,
        check=True,
        capture_output=True,
    )
    if not ret.stdout or not output_json:
        return None
    return json.loads(ret.stdout.decode())


def oc_apply(kubeconfig: str, namespace: str, items: list[dict]) -> None:
    for item in items:
        stdin = json_dumps(item).encode()
        oc(kubeconfig, namespace, ["apply", "-f", "-"], stdin)


def oc_get_secret(kubeconfig: str, namespace: str, secret_name: str) -> dict | None:
    try:
        return oc(kubeconfig, namespace, ["get", "secret", secret_name])
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode(errors="replace")
        if "NotFound" in stderr or "not found" in stderr:
            return None
        raise


def oc_delete_secret(kubeconfig: str, namespace: str, secret_name: str) -> None:
    oc(kubeconfig, namespace, ["delete", "secret", secret_name], output_json=False)


def oc_annotate_secret(
    kubeconfig: str, namespace: str, secret_name: str, vault_path: str
) -> None:
    oc(
        kubeconfig,
        namespace,
        [
            "annotate",
            "secret",
            secret_name,
            f"{VAULT_PATH_ANNOTATION_KEY}={vault_path}",
            "--overwrite",
        ],
    )


def is_managed_secret(secret: dict, sa_name: str) -> bool:
    labels = secret.get("metadata", {}).get("labels") or {}
    if labels.get(MANAGED_LABEL_KEY) == sa_name:
        return True
    # Adopt legacy secrets that predate the managed label but belong to the SA.
    annotations = secret.get("metadata", {}).get("annotations") or {}
    return annotations.get("kubernetes.io/service-account.name") == sa_name


def secret_has_vault_annotation(secret: dict, vault_path: str) -> bool:
    annotations = secret.get("metadata", {}).get("annotations") or {}
    return annotations.get(VAULT_PATH_ANNOTATION_KEY) == vault_path


def sa_secret_name(sa: str) -> str:
    return f"{sa}-token"


class TokenNotReadyError(Exception):
    pass


# retry allows to let the kube API the time to generate the token and fill the secret
@retry()
def retrieve_token(
    kubeconfig: str, namespace: str, sa: str, secret_name: str | None = None
) -> str:
    actual_secret_name = secret_name or sa_secret_name(sa)
    secret = oc(kubeconfig, namespace, ["get", "secret", actual_secret_name])
    if not secret or "token" not in secret.get("data", {}):
        raise TokenNotReadyError()
    b64_token = secret["data"]["token"]
    return base64.b64decode(b64_token).decode()


def create_sa(
    kubeconfig: str,
    namespace: str,
    sa: str,
    secret_name: str | None = None,
    create_namespace: bool = False,
    cluster_admin: bool = False,
) -> str:
    actual_secret_name = secret_name or sa_secret_name(sa)
    items: list[dict] = []
    if create_namespace:
        items.append({
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": namespace},
        })
    items.extend([
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {
                "annotations": {
                    QONTRACT_ANNOTATION_INTEGRATION: QONTRACT_INTEGRATION,
                    QONTRACT_ANNOTATION_INTEGRATION_VERSION: QONTRACT_INTEGRATION_VERSION,
                },
                "name": sa,
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "annotations": {
                    "kubernetes.io/service-account.name": sa,
                    QONTRACT_ANNOTATION_INTEGRATION: QONTRACT_INTEGRATION,
                    QONTRACT_ANNOTATION_INTEGRATION_VERSION: QONTRACT_INTEGRATION_VERSION,
                },
                "labels": {
                    MANAGED_LABEL_KEY: sa,
                },
                "name": actual_secret_name,
            },
            "type": "kubernetes.io/service-account-token",
        },
    ])
    if cluster_admin:
        items.append({
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {
                "name": f"{namespace}-{sa}",
            },
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": "cluster-admin",
            },
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": sa,
                    "namespace": namespace,
                }
            ],
        })

    oc_apply(kubeconfig, namespace, items)
    token = retrieve_token(kubeconfig, namespace, sa, secret_name=actual_secret_name)
    return token


def create_cluster_bots(
    cluster: ClusterV1, ocm: OCM, config: Config
) -> tuple[str | None, str | None]:
    kubeconfig_content = ocm.get_kubeconfig(cluster.name)
    if not kubeconfig_content:
        logging.error(
            f"[{cluster.name}] Could not get cluster credentials from OCM (kubeconfig)"
        )
        return None, None

    token = None
    admin_token = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="locale", delete=True
        ) as kc:
            kc.write(kubeconfig_content)
            kc.flush()
            logging.info(
                f"[{cluster.name}] create {config.dedicated_admin_sa} service account"
            )
            if not config.dry_run:
                token = create_sa(
                    kc.name, config.dedicated_admin_ns, config.dedicated_admin_sa
                )
            if cluster.cluster_admin:
                logging.info(
                    f"[{cluster.name}] create {config.cluster_admin_sa} service account"
                )
                if not config.dry_run:
                    admin_token = create_sa(
                        kc.name,
                        config.cluster_admin_ns,
                        config.cluster_admin_sa,
                        create_namespace=True,
                        cluster_admin=True,
                    )
    except subprocess.CalledProcessError as e:
        logging.error(e.stderr)
        raise

    return token, admin_token


def update_vault(
    cluster: ClusterV1, config: Config, token: str, admin_token: str | None
) -> None:
    vault = VaultClient.get_instance()
    vault.write(
        {
            "path": vault_secret(cluster, config, cluster_admin=False)["path"],
            "data": vault_data(cluster, config, token, cluster_admin=False),
        },
        decode_base64=False,
    )
    if cluster.cluster_admin and admin_token:
        vault.write(
            {
                "path": vault_secret(cluster, config, cluster_admin=True)["path"],
                "data": vault_data(cluster, config, admin_token, cluster_admin=True),
            },
            decode_base64=False,
        )


def submit_mr(clusters: list[ClusterV1], config: Config) -> None:
    cluster_updates: dict[str, dict] = {}
    for cluster in clusters:
        root = {"automationToken": vault_secret(cluster, config, cluster_admin=False)}
        if cluster.cluster_admin:
            root["clusterAdminAutomationToken"] = vault_secret(
                cluster, config, cluster_admin=True
            )
        cluster_updates[cluster.name] = {
            "path": "data" + cluster.path,
            "root": root,
            "spec": {},
        }
    mr = clusters_updates.CreateClustersUpdates(cluster_updates)
    with mr_client_gateway.init(gitlab_project_id=config.gitlab_project_id) as mr_cli:
        mr.submit(cli=mr_cli)


@dataclass
class EntryResult:
    entry: AnyTokenEntry
    cluster_admin: bool
    vault_secret: dict[str, str] | None
    action: str


def _read_token_from_secret(secret: dict) -> str:
    b64_token = secret.get("data", {}).get("token")
    if not b64_token:
        raise TokenNotReadyError()
    return base64.b64decode(b64_token).decode()


def _process_delete_entry(
    kubeconfig: str,
    cluster: ClusterV1,
    config: Config,
    entry: AnyTokenEntry,
    sa_name: str,
    cluster_admin: bool,
) -> EntryResult:
    existing_secret = oc_get_secret(kubeconfig, entry.namespace, entry.name)
    if existing_secret is not None:
        if not is_managed_secret(existing_secret, sa_name):
            logging.warning(
                f"[{cluster.name}] secret {entry.namespace}/{entry.name} is not managed "
                f"by this integration (missing label {MANAGED_LABEL_KEY}={sa_name}), "
                "skipping delete"
            )
            return EntryResult(
                entry=entry,
                cluster_admin=cluster_admin,
                vault_secret=None,
                action="skipped",
            )
        logging.info(f"[{cluster.name}] deleting secret {entry.namespace}/{entry.name}")
        if not config.dry_run:
            oc_delete_secret(kubeconfig, entry.namespace, entry.name)

    if entry.secret is not None:
        logging.info(f"[{cluster.name}] deleting vault secret {entry.secret.path}")
        if not config.dry_run:
            VaultClient.get_instance().delete(entry.secret.path)

    return EntryResult(
        entry=entry, cluster_admin=cluster_admin, vault_secret=None, action="deleted"
    )


def _process_create_entry(
    kubeconfig: str,
    cluster: ClusterV1,
    config: Config,
    entry: AnyTokenEntry,
    sa_name: str,
    cluster_admin: bool,
) -> EntryResult:
    vault_ref = vault_secret_for_entry(cluster.name, config, entry)
    vault_path = vault_ref["path"]
    existing_secret = oc_get_secret(kubeconfig, entry.namespace, entry.name)

    if existing_secret is None:
        logging.info(
            f"[{cluster.name}] creating {sa_name} service account and secret "
            f"{entry.namespace}/{entry.name}"
        )
        if config.dry_run:
            return EntryResult(
                entry=entry,
                cluster_admin=cluster_admin,
                vault_secret=None,
                action="skipped",
            )
        token = create_sa(
            kubeconfig,
            entry.namespace,
            sa_name,
            secret_name=entry.name,
            create_namespace=cluster_admin,
            cluster_admin=cluster_admin,
        )
        VaultClient.get_instance().write(
            {
                "path": vault_path,
                "data": vault_data_for_entry(cluster, token, sa_name, entry.namespace),
            },
            decode_base64=False,
        )
        oc_annotate_secret(kubeconfig, entry.namespace, entry.name, vault_path)
        return EntryResult(
            entry=entry,
            cluster_admin=cluster_admin,
            vault_secret=vault_ref,
            action="created",
        )

    if not is_managed_secret(existing_secret, sa_name):
        logging.warning(
            f"[{cluster.name}] secret {entry.namespace}/{entry.name} exists but is not "
            f"managed by this integration (missing label {MANAGED_LABEL_KEY}={sa_name}), "
            "skipping"
        )
        return EntryResult(
            entry=entry,
            cluster_admin=cluster_admin,
            vault_secret=None,
            action="skipped",
        )

    if entry.secret is not None and secret_has_vault_annotation(
        existing_secret, vault_path
    ):
        return EntryResult(
            entry=entry,
            cluster_admin=cluster_admin,
            vault_secret=None,
            action="skipped",
        )

    logging.info(
        f"[{cluster.name}] syncing existing secret {entry.namespace}/{entry.name} to vault"
    )
    if config.dry_run:
        return EntryResult(
            entry=entry,
            cluster_admin=cluster_admin,
            vault_secret=None,
            action="skipped",
        )

    token = _read_token_from_secret(existing_secret)
    VaultClient.get_instance().write(
        {
            "path": vault_path,
            "data": vault_data_for_entry(cluster, token, sa_name, entry.namespace),
        },
        decode_base64=False,
    )
    if not secret_has_vault_annotation(existing_secret, vault_path):
        oc_annotate_secret(kubeconfig, entry.namespace, entry.name, vault_path)

    return EntryResult(
        entry=entry,
        cluster_admin=cluster_admin,
        vault_secret=vault_ref,
        action="synced",
    )


def process_entry(
    kubeconfig: str,
    cluster: ClusterV1,
    config: Config,
    entry: AnyTokenEntry,
    cluster_admin: bool,
) -> EntryResult:
    sa_name = get_sa_name(config, cluster_admin)
    if entry.delete:
        return _process_delete_entry(
            kubeconfig, cluster, config, entry, sa_name, cluster_admin
        )
    return _process_create_entry(
        kubeconfig, cluster, config, entry, sa_name, cluster_admin
    )


def process_cluster_entries(
    cluster: ClusterV1, ocm: OCM, config: Config
) -> list[EntryResult]:
    entries: list[tuple[AnyTokenEntry, bool]] = [
        (entry, False) for entry in (cluster.automation_tokens or [])
    ] + [(entry, True) for entry in (cluster.cluster_admin_automation_tokens or [])]
    if not entries:
        return []

    kubeconfig_content = ocm.get_kubeconfig(cluster.name)
    if not kubeconfig_content:
        logging.error(
            f"[{cluster.name}] Could not get cluster credentials from OCM (kubeconfig)"
        )
        return []

    results: list[EntryResult] = []
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="locale", delete=True
        ) as kc:
            kc.write(kubeconfig_content)
            kc.flush()
            for entry, cluster_admin in entries:
                results.append(
                    process_entry(kc.name, cluster, config, entry, cluster_admin)
                )
    except subprocess.CalledProcessError as e:
        logging.error(e.stderr)
        raise

    return results


def _entry_to_dict(entry: AnyTokenEntry) -> dict[str, object]:
    return entry.model_dump(by_alias=True, exclude_none=True)


def _merge_entry_updates(
    existing_entries: Sequence[AnyTokenEntry], results: list[EntryResult]
) -> list[dict[str, object]] | None:
    secret_updates = {
        (r.entry.name, r.entry.namespace): r.vault_secret
        for r in results
        if r.vault_secret is not None
    }
    deleted_keys = {
        (r.entry.name, r.entry.namespace) for r in results if r.action == "deleted"
    }
    if not secret_updates and not deleted_keys:
        return None

    merged: list[dict[str, object]] = []
    for entry in existing_entries:
        key = (entry.name, entry.namespace)
        if key in deleted_keys:
            continue
        entry_dict = _entry_to_dict(entry)
        if key in secret_updates:
            entry_dict["secret"] = secret_updates[key]
        merged.append(entry_dict)
    return merged


def submit_list_mr(
    cluster_results: dict[str, list[EntryResult]],
    clusters: list[ClusterV1],
    config: Config,
) -> None:
    cluster_updates: dict[str, dict] = {}
    for cluster in clusters:
        results = cluster_results.get(cluster.name, [])
        if not results:
            continue

        root: dict = {}
        da_results = [r for r in results if not r.cluster_admin]
        ca_results = [r for r in results if r.cluster_admin]

        if da_results:
            merged = _merge_entry_updates(cluster.automation_tokens or [], da_results)
            if merged is not None:
                root["automationTokens"] = merged
        if ca_results:
            merged = _merge_entry_updates(
                cluster.cluster_admin_automation_tokens or [], ca_results
            )
            if merged is not None:
                root["clusterAdminAutomationTokens"] = merged

        if root:
            cluster_updates[cluster.name] = {
                "path": "data" + cluster.path,
                "root": root,
                "spec": {},
            }

    if not cluster_updates:
        return

    mr = clusters_updates.CreateClustersUpdates(cluster_updates)
    with mr_client_gateway.init(gitlab_project_id=config.gitlab_project_id) as mr_cli:
        mr.submit(cli=mr_cli)


def process_all_list_entries(
    clusters: list[ClusterV1], ocm_map: OCMMap, config: Config
) -> None:
    cluster_results: dict[str, list[EntryResult]] = {}
    for cluster in clusters:
        ocm = ocm_map.get(cluster.name)
        results = process_cluster_entries(cluster, ocm, config)
        if results:
            cluster_results[cluster.name] = results

    if not config.dry_run:
        submit_list_mr(cluster_results, clusters, config)


# TODO(APPSRE-13941): remove create_all_bots and all call sites once all clusters migrated to automationTokens
def create_all_bots(
    clusters: list[ClusterV1],
    ocm_map: OCMMap,
    config: Config,
) -> None:
    for cluster in clusters:
        ocm = ocm_map.get(cluster.name)
        token, admin_token = create_cluster_bots(cluster, ocm, config)
        if token and not config.dry_run:
            update_vault(cluster, config, token, admin_token)
    if not config.dry_run:
        submit_mr(clusters, config)


def _entry_needs_processing(entry: AnyTokenEntry) -> bool:
    return bool(entry.delete) or entry.secret is None


def cluster_needs_list_processing(cluster: ClusterV1) -> bool:
    entries = list(cluster.automation_tokens or []) + list(
        cluster.cluster_admin_automation_tokens or []
    )
    return any(_entry_needs_processing(entry) for entry in entries)


def filter_clusters(
    clusters: list[ClusterV1],
) -> tuple[list[ClusterV1], list[ClusterV1]]:
    """Split clusters into (legacy, list_based) clusters needing work.

    Legacy clusters use the singular automationToken/clusterAdminAutomationToken
    fields. List-based clusters declare automationTokens/clusterAdminAutomationTokens
    entries and take precedence when both are present, since the entries are the
    declared source of truth for rotation.
    """
    legacy: list[ClusterV1] = []
    list_based: list[ClusterV1] = []
    for cluster in clusters:
        if not integration_is_enabled(QONTRACT_INTEGRATION, cluster):
            continue
        if cluster.ocm is None:
            continue
        if not cluster_is_reachable(cluster):
            continue

        has_list_entries = bool(cluster.automation_tokens) or bool(
            cluster.cluster_admin_automation_tokens
        )
        if has_list_entries:
            if cluster_needs_list_processing(cluster):
                list_based.append(cluster)
            elif (
                not _has_active_token_with_secret(cluster.automation_tokens)
                and not _has_active_token_with_secret(
                    cluster.cluster_admin_automation_tokens
                )
                and cluster.automation_token is None
                and cluster.cluster_admin_automation_token is None
            ):
                logging.warning(
                    f"[{cluster.name}] has list entries but none are active with a "
                    "secret, and no singular token fallback exists — cluster has no "
                    "usable connection token"
                )
        elif cluster_misses_bot_tokens(
            cluster
        ):  # TODO(APPSRE-13941): remove elif branch once all clusters migrated; filter_clusters returns only list_based
            legacy.append(cluster)

    return legacy, list_based


def get_ocm_map(clusters: list[ClusterV1]) -> OCMMap:
    settings = queries.get_app_interface_settings()
    clusters_info = [c.model_dump(by_alias=True) for c in clusters]
    return OCMMap(
        settings=settings,
        clusters=clusters_info,
        integration=QONTRACT_INTEGRATION,
    )


def run(
    dry_run: bool,
    gitlab_project_id: str,
    vault_creds_path: str,
    dedicated_admin_ns: str,
    dedicated_admin_sa: str,
    cluster_admin_ns: str,
    cluster_admin_sa: str,
) -> None:
    config = Config(
        gitlab_project_id=gitlab_project_id,
        vault_creds_path=vault_creds_path,
        dedicated_admin_ns=dedicated_admin_ns,
        dedicated_admin_sa=dedicated_admin_sa,
        cluster_admin_ns=cluster_admin_ns,
        cluster_admin_sa=cluster_admin_sa,
        dry_run=dry_run,
    )

    query_func = gql.get_api().query
    clusters = clusters_gql.query(query_func=query_func).clusters
    if not clusters:
        logging.debug("No cluster definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    legacy_clusters, list_clusters = filter_clusters(clusters)
    if not legacy_clusters and not list_clusters:
        logging.debug("Nothing to do")
        sys.exit(ExitCodes.SUCCESS)

    ocm_map = get_ocm_map(legacy_clusters + list_clusters)

    if legacy_clusters:  # TODO(APPSRE-13941): remove block once all clusters migrated to automationTokens
        create_all_bots(legacy_clusters, ocm_map, config)

    if list_clusters:
        process_all_list_entries(list_clusters, ocm_map, config)
