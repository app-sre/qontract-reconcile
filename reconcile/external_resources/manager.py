import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum

from sretoolbox.utils import threaded

from reconcile.external_resources.factories import (
    AWSExternalResourceFactory,
    ExternalResourceFactory,
    ModuleProvisionDataFactory,
    ObjectFactory,
    TerraformModuleProvisionDataFactory,
    setup_aws_resource_factories,
)
from reconcile.external_resources.metrics import ExternalResourcesReconcileErrorsGauge
from reconcile.external_resources.model import (
    Action,
    ExternalResource,
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
    ExternalResourcesInventory,
    ExternalResourceValidationError,
    ModuleInventory,
    Reconciliation,
)
from reconcile.external_resources.reconciler import ExternalResourcesReconciler
from reconcile.external_resources.secrets_sync import InClusterSecretsReconciler
from reconcile.external_resources.state import (
    ExternalResourcesStateDynamoDB,
    ExternalResourceState,
    ReconcileStatus,
    ResourceStatus,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    ExternalResourcesSettingsV1,
)
from reconcile.utils import metrics
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)
from reconcile.utils.secret_reader import SecretReaderBase

FLAG_RESOURCE_MANAGED_BY_ERV2 = "managed_by_erv2"
FLAG_DELETE_RESOURCE = "delete"


def setup_factories(
    settings: ExternalResourcesSettingsV1,
    module_inventory: ModuleInventory,
    er_inventory: ExternalResourcesInventory,
    secret_reader: SecretReaderBase,
) -> ObjectFactory[ExternalResourceFactory]:
    tf_factory = TerraformModuleProvisionDataFactory(settings=settings)

    aws_provision_factories = ObjectFactory[ModuleProvisionDataFactory]()
    aws_provision_factories.register_factory("terraform", tf_factory)
    aws_provision_factories.register_factory("cdktf", tf_factory)

    of = ObjectFactory[ExternalResourceFactory]()
    of.register_factory(
        "aws",
        AWSExternalResourceFactory(
            module_inventory=module_inventory,
            er_inventory=er_inventory,
            secret_reader=secret_reader,
            provision_factories=aws_provision_factories,
            resource_factories=setup_aws_resource_factories(
                er_inventory, secret_reader
            ),
        ),
    )
    return of


class ReconcileAction(StrEnum):
    NOOP = "NOOP"
    APPLY_NOT_EXISTS = "Resource does not exist"
    APPLY_ERROR = "Resource status in ERROR state"
    APPLY_SPEC_CHANGED = "Resource spec has changed"
    APPLY_DRIFT_DETECTION = "Resource drift detection run"
    DESTROY_CREATED = "Resource no longer exists in the configuration"
    DESTROY_ERROR = "Resource status in ERROR state"


class ExternalResourcesManager:
    def __init__(
        self,
        state_manager: ExternalResourcesStateDynamoDB,
        settings: ExternalResourcesSettingsV1,
        module_inventory: ModuleInventory,
        reconciler: ExternalResourcesReconciler,
        secret_reader: SecretReaderBase,
        er_inventory: ExternalResourcesInventory,
        factories: ObjectFactory[ExternalResourceFactory],
        secrets_reconciler: InClusterSecretsReconciler,
        thread_pool_size: int,
    ) -> None:
        self.state_mgr = state_manager
        self.settings = settings
        self.module_inventory = module_inventory
        self.reconciler = reconciler
        self.er_inventory = er_inventory
        self.factories = factories
        self.secret_reader = secret_reader
        self.secrets_reconciler = secrets_reconciler
        self.errors: dict[ExternalResourceKey, ExternalResourceValidationError] = {}
        self.thread_pool_size = thread_pool_size

    def _get_reconcile_action(
        self, reconciliation: Reconciliation, state: ExternalResourceState
    ) -> ReconcileAction:
        if reconciliation.action == Action.APPLY:
            match state.resource_status:
                case ResourceStatus.NOT_EXISTS:
                    return ReconcileAction.APPLY_NOT_EXISTS
                case ResourceStatus.ERROR:
                    return ReconcileAction.APPLY_ERROR
                case ResourceStatus.CREATED:
                    if (
                        reconciliation.resource_hash
                        != state.reconciliation.resource_hash
                    ):
                        return ReconcileAction.APPLY_SPEC_CHANGED
                    elif (
                        (datetime.now(state.ts.tzinfo) - state.ts).total_seconds()
                        > reconciliation.module_configuration.reconcile_drift_interval_minutes
                        * 60
                    ):
                        return ReconcileAction.APPLY_DRIFT_DETECTION
        elif reconciliation.action == Action.DESTROY:
            match state.resource_status:
                case ResourceStatus.CREATED:
                    return ReconcileAction.DESTROY_CREATED
                case ResourceStatus.ERROR:
                    return ReconcileAction.DESTROY_ERROR

        return ReconcileAction.NOOP

    def _resource_needs_reconciliation(
        self,
        reconciliation: Reconciliation,
        state: ExternalResourceState,
    ) -> bool:
        reconcile_action = self._get_reconcile_action(reconciliation, state)
        reconcile = reconcile_action != ReconcileAction.NOOP
        if reconcile:
            logging.info(
                "Reconciling: Status: [%s], Action: [%s], reason: [%s], key:[%s]",
                state.resource_status.value,
                reconciliation.action.value,
                reconcile_action.value,
                reconciliation.key,
            )
        return reconcile

    def _get_desired_objects_reconciliations(self) -> set[Reconciliation]:
        r: set[Reconciliation] = set()
        for key, spec in self.er_inventory.items():
            if spec.marked_to_delete:
                continue
            module = self.module_inventory.get_from_spec(spec)
            try:
                resource = self._build_external_resource(spec, self.er_inventory)
            except ExternalResourceValidationError as e:
                self.errors[key] = e
                continue

            reconciliation = Reconciliation(
                key=key,
                resource_hash=resource.hash(),
                input=self._serialize_resource_input(resource),
                action=Action.APPLY,
                module_configuration=ExternalResourceModuleConfiguration.resolve_configuration(
                    module, spec
                ),
            )
            r.add(reconciliation)
        return r

    def _get_deleted_objects_reconciliations(self) -> set[Reconciliation]:
        to_reconcile: set[Reconciliation] = set()
        deleted_keys = (k for k, v in self.er_inventory.items() if v.marked_to_delete)
        for key in deleted_keys:
            state = self.state_mgr.get_external_resource_state(key)
            if state.resource_status == ResourceStatus.NOT_EXISTS:
                logging.debug("Resource has already been removed. key: %s", key)
                continue

            r = Reconciliation(
                key=key,
                resource_hash=state.reconciliation.resource_hash,
                module_configuration=state.reconciliation.module_configuration,
                input=state.reconciliation.input,
                action=Action.DESTROY,
            )
            to_reconcile.add(r)
        return to_reconcile

    def _update_in_progress_state(
        self, r: Reconciliation, state: ExternalResourceState
    ) -> bool:
        """Gets the resource reconciliation state from the Job and updates the
        Resource state accordingly. It also returns if the target outputs secret needs
        to be reconciled.

        :param r: Reconciliation object
        :param state: State object
        :return: True/False if target Secret needs to be reconciled.
        """
        need_secret_sync = False

        if state.resource_status not in set([
            ResourceStatus.DELETE_IN_PROGRESS,
            ResourceStatus.IN_PROGRESS,
        ]):
            return False

        logging.info(
            "Reconciliation In progress. Action: %s, Key:%s",
            state.reconciliation.action,
            state.reconciliation.key,
        )

        # Need to check the reconciliation set in the state, not the desired one
        # as the reconciliation object might be from a previous desired state
        error = False
        match self.reconciler.get_resource_reconcile_status(state.reconciliation):
            case ReconcileStatus.SUCCESS:
                logging.info(
                    "Reconciliation ended SUCCESSFULLY. Action: %s, key:%s",
                    r.action.value,
                    r.key,
                )
                if r.action == Action.APPLY:
                    state.resource_status = ResourceStatus.PENDING_SECRET_SYNC
                    state.reconciliation_errors = 0
                    self.state_mgr.set_external_resource_state(state)
                    need_secret_sync = True
                elif r.action == Action.DESTROY:
                    state.resource_status = ResourceStatus.DELETED
                    self.state_mgr.del_external_resource_state(r.key)
            case ReconcileStatus.ERROR:
                logging.info(
                    "Reconciliation ended with ERROR: Action:%s, Key:%s",
                    r.action.value,
                    r.key,
                )
                error = True
            case ReconcileStatus.NOT_EXISTS:
                logging.info(
                    "Reconciliation should exist but it doesn't. Marking as ERROR to retrigger: Action:%s, Key:%s",
                    r.action.value,
                    r.key,
                )
                error = True
        if error:
            state.resource_status = ResourceStatus.ERROR
            state.reconciliation_errors += 1
            self.state_mgr.set_external_resource_state(state)

        return need_secret_sync

    def _update_state(self, r: Reconciliation, state: ExternalResourceState) -> None:
        state.ts = datetime.now(UTC)
        if r.action == Action.APPLY:
            state.resource_status = ResourceStatus.IN_PROGRESS
        elif r.action == Action.DESTROY:
            state.resource_status = ResourceStatus.DELETE_IN_PROGRESS
        state.reconciliation = r
        self.state_mgr.set_external_resource_state(state)

    def _need_secret_sync(
        self, r: Reconciliation, state: ExternalResourceState
    ) -> bool:
        return (
            r.action == Action.APPLY and state.resource_status == ResourceStatus.CREATED
        )

    def _sync_secrets(
        self,
        to_sync_keys: Iterable[ExternalResourceKey],
    ) -> None:
        specs = [
            spec for key in set(to_sync_keys) if (spec := self.er_inventory.get(key))
        ]

        sync_error_spec_keys = {
            ExternalResourceKey.from_spec(spec)
            for spec in self.secrets_reconciler.sync_secrets(specs=specs)
        }

        for key in to_sync_keys:
            if key in sync_error_spec_keys:
                logging.error(
                    "Outputs secret for key can not be reconciled. Key: %s", key
                )
            else:
                logging.debug(
                    "Outputs secret for key has been reconciled. Marking resource as %s. Key: %s",
                    ResourceStatus.CREATED,
                    key,
                )
                self.state_mgr.update_resource_status(key, ResourceStatus.CREATED)

    def _build_external_resource(
        self, spec: ExternalResourceSpec, er_inventory: ExternalResourcesInventory
    ) -> ExternalResource:
        f = self.factories.get_factory(spec.provision_provider)
        resource = f.create_external_resource(spec)
        f.validate_external_resource(resource)
        return resource

    def _serialize_resource_input(self, resource: ExternalResource) -> str:
        return resource.json(
            exclude={"data": {FLAG_RESOURCE_MANAGED_BY_ERV2, FLAG_DELETE_RESOURCE}}
        )

    def handle_resources(self) -> None:
        desired_r = self._get_desired_objects_reconciliations()
        deleted_r = self._get_deleted_objects_reconciliations()
        to_sync_keys: set[ExternalResourceKey] = set()
        for r in desired_r.union(deleted_r):
            state = self.state_mgr.get_external_resource_state(r.key)
            need_sync = self._update_in_progress_state(r, state)
            if need_sync:
                to_sync_keys.add(r.key)

            metrics.set_gauge(
                ExternalResourcesReconcileErrorsGauge(
                    provision_provider=r.key.provision_provider,
                    provisioner_name=r.key.provisioner_name,
                    provider=r.key.provider,
                    identifier=r.key.identifier,
                ),
                float(state.reconciliation_errors),
            )

            if self._resource_needs_reconciliation(reconciliation=r, state=state):
                self.reconciler.reconcile_resource(reconciliation=r)
                self._update_state(r, state)

        pending_sync_keys = self.state_mgr.get_keys_by_status(
            ResourceStatus.PENDING_SECRET_SYNC
        )

        if to_sync_keys or pending_sync_keys:
            self._sync_secrets(to_sync_keys=to_sync_keys | pending_sync_keys)

    def handle_dry_run_resources(self) -> None:
        desired_r = self._get_desired_objects_reconciliations()
        deleted_r = self._get_deleted_objects_reconciliations()
        reconciliations = desired_r.union(deleted_r)
        triggered = set[Reconciliation]()

        for r in reconciliations:
            state = self.state_mgr.get_external_resource_state(key=r.key)
            if (
                r.action == Action.APPLY
                and state.reconciliation.resource_hash != r.resource_hash
            ) or r.action == Action.DESTROY:
                triggered.add(r)

        threaded.run(
            self.reconciler.reconcile_resource,
            triggered,
            thread_pool_size=self.thread_pool_size,
        )

        results = self.reconciler.wait_for_reconcile_list_completion(
            triggered, check_interval_seconds=10, timeout_seconds=-1
        )

        for r in triggered:
            self.reconciler.get_resource_reconcile_logs(reconciliation=r)

        if ReconcileStatus.ERROR in [rs for rs in results.values()]:
            raise Exception("Some Resources have reconciliation errors.")
