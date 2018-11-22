import json


class AggregatedList(object):
    def __init__(self):
        self._dict = {}

    def add(self, params, items):
        params_hash = self.hash_params(params)

        if self._dict.get(params_hash):
            for item in items:
                if item not in self._dict[params_hash]["items"]:
                    self._dict[params_hash]["items"].append(item)
        else:
            self._dict[params_hash] = self.element(params, items)

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
            'insert': [
                right_state.get_by_params_hash(p)
                for p in right_params
                if p not in left_params
            ],
            'delete': [
                self.get_by_params_hash(p)
                for p in left_params
                if p not in right_params
            ],
            'update-insert': [],
            'update-delete': []
        }

        union = [p for p in left_params if p in right_params]

        for p in union:
            left = self.get_by_params_hash(p)
            right = right_state.get_by_params_hash(p)

            l_items = left['items']
            r_items = right['items']

            update_insert = [i for i in r_items if i not in l_items]
            update_delete = [i for i in l_items if i not in r_items]

            if update_insert:
                diff['update-insert'].append({
                    'params': left['params'],
                    'items': update_insert
                })

            if update_delete:
                diff['update-delete'].append({
                    'params': left['params'],
                    'items': update_delete
                })

        return diff

    def dump(self):
        return self._dict.values()

    def toJSON(self):
        return json.dumps(self.dump())

    @staticmethod
    def hash_params(params):
        return hash(json.dumps(params, sort_keys=True))

    @staticmethod
    def element(params, items):
        return {
            'params': params,
            'items': items
        }


class AggregatedDiffRunner(object):
    def __init__(self, state):
        self.state = state
        self.actions = []

    def register(self, on, cond, action):
        self.actions.append((on, cond, action))

    def run(self):
        for (on, cond, action) in self.actions:
            diff_list = self.state.get(on, [])

            for diff_element in diff_list:
                params = diff_element['params']
                items = diff_element['items']

                if cond(params):
                    action(params, items)
