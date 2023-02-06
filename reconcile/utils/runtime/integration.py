from abc import (
    ABC,
    abstractmethod,
)
from dataclasses import dataclass
from types import ModuleType
from typing import (
    Any,
    Callable,
    Optional,
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


class QontractReconcileIntegration(ABC):
    """
    The base class for all integrations. It defines the basic interface to interact
    with an integration and offers hook methods that allow the integration to opt
    into optional functionality like early-exit or sharded dry-runs.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    def get_early_exit_desired_state(
        self, *args: Any, **kwargs: Any
    ) -> Optional[dict[str, Any]]:
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
    def run(self, dry_run: bool, *args: Any, **kwargs: Any) -> None:
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

    def kwargs_have_shard_info(self, **kwargs: Any) -> bool:
        """
        Returns `True` if the args and kwargs already contain sharding information.
        """
        sharding_config = (  # pylint: disable=assignment-from-none
            self.get_desired_state_shard_config()
        )
        if sharding_config:
            shard_arg_value = kwargs.get(sharding_config.shard_arg_name)
            return shard_arg_value is not None and shard_arg_value
        else:
            return False

    def run_for_shard(
        self, dry_run: bool, shard: str, *run_args: Any, **run_kwargs: Any
    ) -> None:
        """
        Runs the integration for a specific shard, by patching the `run_kwargs`.
        If the integration does not support sharded runs, it raises an exception.
        """
        sharding_config = (  # pylint: disable=assignment-from-none
            self.get_desired_state_shard_config()
        )
        if sharding_config:
            shard_kwargs = run_kwargs.copy()
            if sharding_config.shard_arg_is_collection:
                shard_kwargs[sharding_config.shard_arg_name] = [shard]
            else:
                shard_kwargs[sharding_config.shard_arg_name] = shard
            self.run(dry_run, *run_args, **shard_kwargs)
        else:
            raise NotImplementedError(
                "The integration does not support run in sharded mode."
            )


RUN_FUNCTION = "run"
EARLY_EXIT_DESIRED_STATE_FUNCTION = "early_exit_desired_state"
DESIRED_STATE_SHARD_CONFIG_FUNCTION = "desired_state_shard_config"


class ModuleBasedQontractReconcileIntegration(QontractReconcileIntegration):
    """
    Since most integrations are implemented as modules, this class provides a
    wrapper around a module that implements the `QontractReconcileIntegration`
    interface. This way such module based integrations can be used as if they
    were instances of the `QontractReconcileIntegration` class.
    """

    def __init__(self, module: ModuleType):
        self._module = module
        self.name  # run to check if the name can be extracted from the module
        if not self._integration_supports(RUN_FUNCTION):
            raise NotImplementedError(f"Integration has no {RUN_FUNCTION}() function")

    def _integration_supports(self, func_name: str) -> bool:
        """
        Verifies, that an integration supports a specific function.
        todo: more thorough verification of the functions signature would be required.
        """
        return func_name in dir(self._module)

    @property
    def name(self) -> str:
        try:
            return self._module.QONTRACT_INTEGRATION.replace("_", "-")
        except AttributeError:
            raise NotImplementedError("Integration missing QONTRACT_INTEGRATION.")

    def get_early_exit_desired_state(
        self, *args: Any, **kwargs: Any
    ) -> Optional[dict[str, Any]]:
        if self._integration_supports(EARLY_EXIT_DESIRED_STATE_FUNCTION):
            return self._module.early_exit_desired_state(*args, **kwargs)
        else:
            return None

    def get_desired_state_shard_config(self) -> Optional["DesiredStateShardConfig"]:
        if self._integration_supports(DESIRED_STATE_SHARD_CONFIG_FUNCTION):
            return self._module.desired_state_shard_config()
        return None

    def run(self, dry_run: bool, *args: Any, **kwargs: Any) -> None:
        self._module.run(dry_run, *args, **kwargs)
