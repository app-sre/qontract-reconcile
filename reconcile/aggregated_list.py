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
            ]
        }

        diff['update'] = []
        union = [p for p in left_params if p in right_params]

        for p in union:
            left = self.get_by_params_hash(p)
            right = right_state.get_by_params_hash(p)

            l_items = left['items']
            r_items = right['items']

            if set(l_items) != set(r_items):
                diff['update'].append(
                    {
                        'params': left['params'],
                        'insert': [i for i in r_items if i not in l_items],
                        'delete': [i for i in l_items if i not in r_items],
                    }
                )

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
