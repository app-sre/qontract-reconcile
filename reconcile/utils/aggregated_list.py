import json
import logging


class RunnerException(Exception):
    pass


class AggregatedList:
    def __init__(self):
        self._dict = {}

    def add(self, params, new_items):
        params_hash = self.hash_params(params)

        if self._dict.get(params_hash) is None:
            self._dict[params_hash] = {"params": params, "items": []}

        if not isinstance(new_items, list):
            new_items = [new_items]

        for item in new_items:
            if item not in self._dict[params_hash]["items"]:
                self._dict[params_hash]["items"].append(item)

    def get(self, params):
        return self._dict[self.hash_params(params)]

    def get_all_params_hash(self):
        return self._dict.keys()

    def get_by_params_hash(self, params_hash):
        return self._dict[params_hash]

    def diff(self, right_state):
        left_params = self.get_all_params_hash()
        right_params = right_state.get_all_params_hash()

        diff = {
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
            left = self.get_by_params_hash(p)
            right = right_state.get_by_params_hash(p)

            l_items = left["items"]
            r_items = right["items"]

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

    def dump(self):
        return list(self._dict.values())

    def toJSON(self):
        return json.dumps(self.dump(), indent=4)

    @staticmethod
    def hash_params(params):
        return hash(json.dumps(params, sort_keys=True))


class AggregatedDiffRunner:
    def __init__(self, diff):
        self.diff = diff
        self.actions = []

    def register(self, on, action, cond=None):
        if on not in self.diff.keys():
            raise Exception("Unknown diff key for 'on': {}".format(on))
        self.actions.append((on, action, cond))

    def run(self):
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
