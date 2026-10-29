from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
import yaml
from qontract_utils.differ import DiffResult

from reconcile import openshift_base as ob
from reconcile import openshift_vault_secrets as sut
from reconcile.utils.oc import OCCli
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

MR_215615_BASE_SHA = "f61443f7bc33331624205356f2e7ddf98bf2b754"
MR_215615_HEAD_SHA = "ebcc96f4ad7a0e0af5a810e1dad6ec2aabe17412"
MR_215615_FIXTURES = Path(__file__).parent / "fixtures/openshift_vault_secrets"


def _pod(name: str, secret_name: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": "playbook-dispatcher-prod"},
        "spec": {
            "volumes": [
                {"name": "config-manager-psk", "secret": {"secretName": secret_name}}
            ],
            "containers": [
                {
                    "name": "playbook-dispatcher",
                    "volumeMounts": [
                        {
                            "name": "config-manager-psk",
                            "mountPath": "/etc/config-manager-psk",
                        }
                    ],
                }
            ],
        },
    }


def test_secret_in_use_gate_blocks_mr_215615_deletion(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Replay the Secret deletion caused by app-interface MR 215615."""
    secret_name = "auth-psk-config-manager"
    pod = _pod("playbook-dispatcher-api-abc123", secret_name)
    oc_client = MagicMock()
    oc_client.get_items.return_value = [pod]
    oc_client.is_resource_used_in_pod.side_effect = lambda name, kind, candidate: (
        name in OCCli.get_resources_used_in_pod_spec(candidate["spec"], kind)
    )
    oc_map = MagicMock()
    oc_map.get_cluster.return_value = oc_client

    gate = sut.SecretInUseDeletionGate(oc_map)

    assert not gate.is_delete_allowed(
        cluster="crcp01ue1",
        namespace="playbook-dispatcher-prod",
        resource_type="Secret",
        resource_name=secret_name,
    )
    oc_client.get_items.assert_called_once_with(
        "Pod", namespace="playbook-dispatcher-prod"
    )
    assert "Deletion blocked: Secret auth-psk-config-manager" in caplog.text
    assert "Pod/playbook-dispatcher-api-abc123" in caplog.text


def test_mr_215615_base_to_head_replay_blocks_unsafe_deletion(
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
) -> None:
    """Replay MR 215615's desired-state delta through the deletion boundary."""
    caplog.set_level(logging.INFO)
    base = yaml.safe_load((MR_215615_FIXTURES / "mr_215615_base.yml").read_text())
    head = yaml.safe_load((MR_215615_FIXTURES / "mr_215615_head.yml").read_text())
    base_vault_secrets = {
        item["path"]: item
        for item in base["openshiftResources"]
        if item["provider"] == "vault-secret"
    }
    head_vault_secret_paths = {
        item["path"]
        for item in head["openshiftResources"]
        if item["provider"] == "vault-secret"
    }
    removed_paths = set(base_vault_secrets) - head_vault_secret_paths

    expected_removed_path = (
        "insights/secrets/insights-prod/playbook-dispatcher-prod/"
        "auth-psk-config-manager"
    )
    assert removed_paths == {expected_removed_path}
    removed_path = removed_paths.pop()
    removed_secret_name = removed_path.rsplit("/", maxsplit=1)[-1]
    assert removed_secret_name == "auth-psk-config-manager"

    current_secret = OpenshiftResource(
        body={
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": removed_secret_name},
        },
        integration=sut.QONTRACT_INTEGRATION,
        integration_version=sut.QONTRACT_INTEGRATION_VERSION,
        validate_k8s_object=False,
    ).annotate(canonicalize=False)
    deleted_resources = DiffResult(
        add={},
        change={},
        delete={removed_secret_name: current_secret},
        identical={},
    ).delete
    data = {"use_admin_token": {removed_secret_name: False}}
    options = ob.ApplyOptions(
        dry_run=True,
        no_dry_run_skip_compare=False,
        wait_for_namespace=False,
        recycle_pods=True,
        take_over=False,
        override_enable_deletion=False,
        caller=None,
        all_callers=None,
        privileged=False,
        enable_deletion=True,
    )
    delete = mocker.patch.object(ob, "delete", autospec=True)

    baseline_inventory = ResourceInventory()
    baseline_actions = ob.handle_deleted_resources(
        oc_map=MagicMock(),
        ri=baseline_inventory,
        deleted_resources=deleted_resources,
        cluster=base["cluster"],
        namespace=base["name"],
        resource_type="Secret",
        data=data,
        options=options,
    )
    assert [action["name"] for action in baseline_actions] == [removed_secret_name]
    delete.assert_called_once()

    pod = _pod("playbook-dispatcher-api-abc123", removed_secret_name)
    oc_client = MagicMock()
    oc_client.get_items.return_value = [pod]
    oc_client.is_resource_used_in_pod.side_effect = lambda name, kind, candidate: (
        name in OCCli.get_resources_used_in_pod_spec(candidate["spec"], kind)
    )
    oc_map = MagicMock()
    oc_map.get_cluster.return_value = oc_client
    options.deletion_gate = sut.SecretInUseDeletionGate(oc_map)
    protected_inventory = ResourceInventory()
    delete.reset_mock()

    protected_actions = ob.handle_deleted_resources(
        oc_map=oc_map,
        ri=protected_inventory,
        deleted_resources=deleted_resources,
        cluster=base["cluster"],
        namespace=base["name"],
        resource_type="Secret",
        data=data,
        options=options,
    )

    assert protected_actions == []
    assert protected_inventory.has_error_registered(cluster=base["cluster"])
    delete.assert_not_called()
    logging.info(
        "MR 215615 replay: base=%s head=%s removed=%s baseline=delete "
        "protected=blocked consumer=Pod/playbook-dispatcher-api-abc123",
        MR_215615_BASE_SHA,
        MR_215615_HEAD_SHA,
        removed_path,
    )


def test_secret_in_use_gate_allows_verified_unreferenced_secret() -> None:
    oc_client = MagicMock()
    oc_client.get_items.return_value = []
    oc_map = MagicMock()
    oc_map.get_cluster.return_value = oc_client

    assert sut.SecretInUseDeletionGate(oc_map).is_delete_allowed(
        cluster="crcp01ue1",
        namespace="playbook-dispatcher-prod",
        resource_type="Secret",
        resource_name="unused-secret",
    )


def test_secret_in_use_gate_fails_closed_when_pod_inventory_fails() -> None:
    oc_client = MagicMock()
    oc_client.get_items.side_effect = RuntimeError("pod inventory unavailable")
    oc_map = MagicMock()
    oc_map.get_cluster.return_value = oc_client

    with pytest.raises(RuntimeError, match="pod inventory unavailable"):
        sut.SecretInUseDeletionGate(oc_map).is_delete_allowed(
            cluster="crcp01ue1",
            namespace="playbook-dispatcher-prod",
            resource_type="Secret",
            resource_name="auth-psk-config-manager",
        )


def test_secret_in_use_gate_ignores_non_secret_deletions() -> None:
    oc_map = MagicMock()

    assert sut.SecretInUseDeletionGate(oc_map).is_delete_allowed(
        cluster="crcp01ue1",
        namespace="playbook-dispatcher-prod",
        resource_type="ConfigMap",
        resource_name="unrelated",
    )
    oc_map.get_cluster.assert_not_called()


def test_run_enables_gate_only_for_openshift_vault_secrets(
    mocker: MockerFixture,
) -> None:
    run = mocker.patch.object(sut.orb, "run", autospec=True)

    sut.run(dry_run=True)

    assert run.call_args.kwargs["deletion_gate_factory"] is sut.SecretInUseDeletionGate
