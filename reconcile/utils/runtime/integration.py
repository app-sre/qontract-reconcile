from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType
from typing import (
    Any,
    Generic,
    Optional,
    TypeVar,
)

from pydantic import BaseModel

from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)


@dataclass
class ShardedRunProposal:
    """
    A `ShardedRunProposal` represents the a proposal how a sharded integration
    run should be executed. It is passed to the `sharded_run_review` callback
    an integration can register in its `DesiredStateShardConfig` instance.
    The integration uses an instance of `ShardedRunProposal` to decide if sharded
    run should be executed or not.

    Right now, a `ShardedRunProposal` only contains the affected shards extracted
    from the diffs in desired state. If additional information is needed to make
    the decision, it can be added to this class.
    """

    proposed_shards: set[str]
    """
    The shards that are affected by the current change. This is the set of shards
    that will be passed to the integration's `run` function individually, if the
    integration decides to execute a sharded run.
    """


@dataclass
class DesiredStateShardConfig:
    """
    A `DesiredStateShardConfig` instance describes how a `QontractReconcileIntegration`
    wants to execute sharded dry-runs on its desired state. It contains the
    information needed to extract the shards from the desired state, and to
    pass them to the integration `run` function. It also contains a callback
    function that allows the integration to review the proposed shards and
    decide if they should be processed with sharded runs or not.
    """

    sharded_run_review: Callable[[ShardedRunProposal], bool]
    """
    A callback function that allows the integration to review the proposed
    shards and decide if they should be processed with sharded runs or not
    """

    shard_path_selectors: set[str]
    """
    A set of JSONPath selectors defining where to find the shards in the desired
    state offered by `QontractReconcileIntegration.get_early_exit_desired_state`
    function.
    """

    shard_arg_name: str
    """
    The name of the argument that the integration's `run` function expects to
    receive the shards in.
    """

    shard_arg_is_collection: bool = False
    """
    Some integration's `run` functions expect the shards to be passed as a
    collection. In that case, this flag should be set to `True`.
    """


RunParamsSelfTypeVar = TypeVar("RunParamsSelfTypeVar", bound="RunParams")


class RunParams(ABC):
    """
    A `RunParams` instance is a container for the parameters that an integration
    needs to run. This is the base class for all flavors of `RunParams`.
    """

    @abstractmethod
    def copy_and_update(
        self: RunParamsSelfTypeVar, update: dict[str, Any]
    ) -> RunParamsSelfTypeVar:
        """
        Returns a copy of the `RunParams` instance with the given `update` applied.
        """

    @abstractmethod
    def get(self, field: str) -> Any:
        """
        Returns the value of the given `field`.
        """


PydanticRunParamsSelfTypeVar = TypeVar(
    "PydanticRunParamsSelfTypeVar", bound="PydanticRunParams"
)


class PydanticRunParams(RunParams, BaseModel):
    """
    A flavor of `RunParams` that uses Pydantic's `BaseModel` as the base class.
    This enables validation based on type hints and pydantic advanced validation.
    """

    def copy_and_update(
        self: PydanticRunParamsSelfTypeVar, update: dict[str, Any]
    ) -> PydanticRunParamsSelfTypeVar:
        return self.copy(update=update)

    def get(self, field: str) -> Any:
        return getattr(self, field)


class NoParams(RunParams):
    """
    A `RunParams` instance that does not contain any parameters.
    """

    def copy_and_update(self, update: dict[str, Any]) -> "NoParams":
        return NoParams()

    def get(self, field: str) -> None:
        raise ValueError(f"Field '{field}' does not exist")


RunParamsTypeVar = TypeVar("RunParamsTypeVar", bound=RunParams)
IntegrationClassTypeVar = TypeVar(
    "IntegrationClassTypeVar", bound="QontractReconcileIntegration"
)


class QontractReconcileIntegration(ABC, Generic[RunParamsTypeVar]):
    """
    The base class for all integrations. It defines the basic interface to interact
    with an integration and offers hook methods that allow the integration to opt
    into optional functionality like early-exit or sharded dry-runs.
    """

    def __init__(self, params: RunParamsTypeVar) -> None:
        self.params: RunParamsTypeVar = params
        self._secret_reader: SecretReaderBase | None = None

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def secret_reader(self) -> SecretReaderBase:
        """
        Returns a function that can be used to read secrets from the vault or another secret reader.
        """
        if self._secret_reader is None:
            vault_settings = get_app_interface_vault_settings()
            self._secret_reader = create_secret_reader(use_vault=vault_settings.vault)
        return self._secret_reader

    def get_early_exit_desired_state(self) -> dict[str, Any] | None:
        """
        An integration that wants to support early exit on its desired state
        must implement this method and return the desired state as a dictionary.
        The dictionary can be nested and can contain any data type that can be
        serialized to JSON.

        If `None` is returned, the integration will not be able to opt into
        early exit.
        """
        return None

    def get_desired_state_shard_config(self) -> Optional["DesiredStateShardConfig"]:
        """
        An integration that wants to support sharded dry-runs on its desired state
        must implement this method and return a `DesiredStateShardConfig` instance.

        If `None` is returned, the integration will not be able to opt into
        sharded dry-runs.
        """
        return None

    @abstractmethod
    def run(self, dry_run: bool) -> None:
        """
        The `run` function of a QontractReconcileIntegration is the entry point to
        its actual functionality. It is obliged to honor the `dry_run` argument and not
        perform any changes to the system if it is set to `True`. At the same time
        the integration should progress as far as possible in the dry-run mode to
        highlight any issues that would have prevented it from running in non-dry-run
        mode.
        """

    def supports_sharded_dry_run_mode(self) -> bool:
        """
        Returns `True` if the integration supports sharded dry-runs.
        """
        return self.get_desired_state_shard_config() is not None

    def params_have_shard_info(self) -> bool:
        """
        Returns `True` if the params already contain sharding information.
        """
        sharding_config = (  # pylint: disable=assignment-from-none
            self.get_desired_state_shard_config()
        )
        if sharding_config:
            shard_arg_value = self.params.get(sharding_config.shard_arg_name)
            return bool(shard_arg_value)
        return False

    def build_integration_instance_for_shard(
        self: IntegrationClassTypeVar, shard: str
    ) -> IntegrationClassTypeVar:
        """
        Create an instegration instance for a specific shard, by patching the run parameters.
        If the integration does not support sharded runs, it raises an exception.
        """
        sharding_config = (  # pylint: disable=assignment-from-none
            self.get_desired_state_shard_config()
        )
        if sharding_config:
            sharded_params = self.params.copy_and_update({
                sharding_config.shard_arg_name: [shard]
                if sharding_config.shard_arg_is_collection
                else shard
            })
            return type(self)(sharded_params)

        raise NotImplementedError(
            "The integration does not support run in sharded mode."
        )


RUN_FUNCTION = "run"
NAME_FIELD = "QONTRACT_INTEGRATION"
EARLY_EXIT_DESIRED_STATE_FUNCTION = "early_exit_desired_state"
DESIRED_STATE_SHARD_CONFIG_FUNCTION = "desired_state_shard_config"


class ModuleArgsKwargsRunParams(RunParams):
    module: ModuleType
    args: Any
    kwargs: Any

    def __init__(self, module: ModuleType, *args: Any, **kwargs: Any) -> None:
        self.module = module
        self.args = args
        self.kwargs = kwargs

    def copy_and_update(self, update: dict[str, Any]) -> "ModuleArgsKwargsRunParams":
        kwargs_copy = self.kwargs.copy()
        kwargs_copy.update(update)
        return ModuleArgsKwargsRunParams(self.module, *self.args, **kwargs_copy)

    def get(self, field: str) -> Any:
        return self.kwargs.get(field)


class ModuleBasedQontractReconcileIntegration(
    QontractReconcileIntegration[ModuleArgsKwargsRunParams]
):
    """
    Since most integrations are implemented as modules, this class provides a
    wrapper around a module that implements the `QontractReconcileIntegration`
    interface. This way such module based integrations can be used as if they
    were instances of the `QontractReconcileIntegration` class.
    """

    def __init__(self, params: ModuleArgsKwargsRunParams):
        super().__init__(params)
        # self.name  # run to check if the name can be extracted from the module
        if not self._integration_supports(NAME_FIELD):
            raise NotImplementedError(f"Integration has no {NAME_FIELD} field")
        if not self._integration_supports(RUN_FUNCTION):
            raise NotImplementedError(f"Integration has no {RUN_FUNCTION}() function")

    def _integration_supports(self, func_name: str) -> bool:
        """
        Verifies, that an integration supports a specific function.
        todo: more thorough verification of the functions signature would be required.
        """
        return func_name in dir(self.params.module)

    @property
    def name(self) -> str:
        if self._integration_supports(NAME_FIELD):
            return self.params.module.QONTRACT_INTEGRATION.replace("_", "-")
        raise NotImplementedError("Integration missing QONTRACT_INTEGRATION.")

    def get_early_exit_desired_state(self) -> dict[str, Any] | None:
        if self._integration_supports(EARLY_EXIT_DESIRED_STATE_FUNCTION):
            return self.params.module.early_exit_desired_state(
                *self.params.args, **self.params.kwargs
            )
        return None

    def get_desired_state_shard_config(self) -> Optional["DesiredStateShardConfig"]:
        if self._integration_supports(DESIRED_STATE_SHARD_CONFIG_FUNCTION):
            return self.params.module.desired_state_shard_config()
        return None

    def run(self, dry_run: bool) -> None:
        self.params.module.run(dry_run, *self.params.args, **self.params.kwargs)
