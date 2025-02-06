import json
import logging
from collections.abc import Callable, KeysView
from typing import Any, TypedDict

Action = Callable[[Any, list[Any]], bool]
Cond = Callable[[Any], bool]


class RunnerException(Exception):
    pass


class AggregatedItem(TypedDict):
    params: Any
    items: list[Any]


class AggregatedList:
    def __init__(self) -> None:
        self._dict: dict[int, AggregatedItem] = {}

    def add(self, params: Any, new_items: Any | list[Any]) -> None:
        params_hash: int = self.hash_params(params)

        if self._dict.get(params_hash) is None:
            self._dict[params_hash] = {"params": params, "items": []}

        if not isinstance(new_items, list):
            new_items = [new_items]

        for item in new_items:
            if item not in self._dict[params_hash]["items"]:
                self._dict[params_hash]["items"].append(item)

    def get(self, params: Any) -> AggregatedItem:
        return self._dict[self.hash_params(params)]

    def get_all_params_hash(self) -> KeysView[int]:
        return self._dict.keys()

    def get_by_params_hash(self, params_hash: int) -> AggregatedItem:
        return self._dict[params_hash]

    def diff(self, right_state: "AggregatedList") -> dict[str, list[AggregatedItem]]:
        left_params = self.get_all_params_hash()
        right_params = right_state.get_all_params_hash()

        diff: dict[str, list[AggregatedItem]] = {
            "insert": [
                right_state.get_by_params_hash(p)
                for p in right_params
                if p not in left_params
            ],
            "delete": [
                self.get_by_params_hash(p) for p in left_params if p not in right_params
            ],
            "update-insert": [],
            "update-delete": [],
        }

        union = [p for p in left_params if p in right_params]

        for p in union:
            left: AggregatedItem = self.get_by_params_hash(p)
            right: AggregatedItem = right_state.get_by_params_hash(p)

            l_items: list[Any] = left["items"]
            r_items: list[Any] = right["items"]

            update_insert = [i for i in r_items if i not in l_items]
            update_delete = [i for i in l_items if i not in r_items]

            if update_insert:
                diff["update-insert"].append({
                    "params": left["params"],
                    "items": update_insert,
                })

            if update_delete:
                diff["update-delete"].append({
                    "params": left["params"],
                    "items": update_delete,
                })

        return diff

    def dump(self) -> list[AggregatedItem]:
        return list(self._dict.values())

    def toJSON(self) -> str:
        return json.dumps(self.dump(), indent=4)

    @staticmethod
    def hash_params(params: Any) -> int:
        return hash(json.dumps(params, sort_keys=True))


class AggregatedDiffRunner:
    def __init__(self, diff: dict[str, list[AggregatedItem]]) -> None:
        self.diff = diff
        self.actions: list[tuple[str, Action, Cond | None]] = []

    def register(self, on: str, action: Action, cond: Cond | None = None) -> None:
        if on not in self.diff:
            raise Exception(f"Unknown diff key for 'on': {on}")
        self.actions.append((on, action, cond))

    def run(self) -> bool:
        status = True

        for on, action, cond in self.actions:
            diff_list = self.diff.get(on, [])

            for diff_element in diff_list:
                params = diff_element["params"]
                items = diff_element["items"]

                if cond is None or cond(params):
                    try:
                        last_status = action(params, items)
                        status = status and last_status
                    except Exception as e:
                        status = False
                        logging.error([params, items])
                        logging.error(str(e))

        return status
