import yaml
import subprocess

from collections import OrderedDict


class InvalidType(Exception):
    pass


class ConfigError(Exception):
    pass


class DuplicateReceiver(Exception):
    pass


class RouteMatcher(object):
    def __init__(self, k, v):
        self.config = {}

        if type(v) == list and len(v) > 1:
            regex = "^({})$".format('|'.join(v))
            self._kind = 'match_re'
            self._rules = {k: regex}
        elif type(v) == list and len(v) == 1:
            self._kind = 'match'
            self._rules = {k: v[0]}
        else:
            self._kind = 'match'
            self._rules = {k: v}

    @property
    def kind(self):
        return self._kind

    @property
    def rules(self):
        return self._rules


class Route(object):
    def __init__(self, receiver=None, matcher=None, **kwargs):
        self.config = OrderedDict()

        if receiver:
            self.config['receiver'] = receiver

        if matcher:
            self.config[matcher.kind] = matcher.rules

        for k, v in kwargs.items():
            k = k.lstrip('__')
            self.config[k] = v

    @property
    def receiver(self):
        return self.config['receiver']

    def add_route(self, route):
        if not isinstance(route, Route):
            raise(InvalidType("expected Route object, got {}".format(route)))
        self.config.setdefault('routes', []).append(route)
        return self


class Alertmanager(object):
    """
    Alertmanager object that holds an alertmanager configuration file
    """
    def __init__(self):
        self._config = OrderedDict()
        self._config['global'] = OrderedDict()
        self._config['inhibit_rules'] = list()
        self._config['route'] = OrderedDict()
        self._config['receivers'] = list()

        self.set_default_route('default')
        self.add_receiver('default')

        # Turn off yaml tags
        yaml.emitter.Emitter.process_tag = lambda x: None

        # Turn off yaml aliases (anchors/references)
        yaml.Dumper.ignore_aliases = lambda *args: True

        # Dump in ordereddict format
        yaml.add_representer(OrderedDict, self.represent_ordereddict)

    def represent_ordereddict(self, dumper, data):
        """
        YAML representer for the OrderedDict type
        """
        value = []
        for item_key, item_value in data.items():
            node_key = dumper.represent_data(item_key)
            node_value = dumper.represent_data(item_value)

            value.append((node_key, node_value))
        return yaml.nodes.MappingNode(u'tag:yaml.org,2002:map', value)

    def validate_config(self, amtool=None):
        """
        Validate the configuration using `amtool`
        """
        proc = subprocess.Popen(['amtool', 'check-config'],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        out = proc.communicate(input=yaml.dump(self._config, sort_keys=False))

        if proc.returncode != 0:
            return False, out

        return True, None

    def config(self, validate=True):
        """
        Render the alertmanager configuration in YAML format
        """
        if validate:
            ok, err = self.validate_config()
            if not ok:
                raise(ConfigError(err))

        return yaml.dump(self._config, sort_keys=False)

    def routing_tree(self):
        """
        Render the routing tree using `amtool`
        """
        ok, err = self.validate_config()
        if not ok:
            raise(ConfigError(err))

        import tempfile
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(self.config())
        f.close()

        cmd = ['amtool',
               'config',
               'routes',
               'show',
               '--config.file={}'.format(f.name)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = proc.communicate(input=self.config())

        if proc.returncode != 0:
            return "Could not generate routing tree: {}".format(out[1])

        return out[0]

    def set_global(self, key, val):
        self._config['global'][key] = val

    def set_default_route(self, receiver, **kwargs):
        self._config['route']['receiver'] = receiver

        for k, v in kwargs.items():
            k = k.lstrip('__')
            self._config['route'][k] = v

    def add_inhibit_rule(self, rule):
        if isinstance(rule, dict):
            # TODO make sure we do not add a duplicate receiver (name)
            self._config.setdefault('inhibit_rules', []).append(rule)
        else:
            raise(InvalidType("inhibit rule must be a dict"))

    def add_route(self, receiver=None, **kwargs):
        """
        Add a route under the default route
        """
        route = OrderedDict()

        if receiver:
            route['receiver'] = receiver

        if kwargs['match']:
            route['match'] = kwargs['match']

        for k, v in kwargs.items():
            k = k.lstrip('__')
            route[k] = v

        self._config['route'].setdefault('routes', []).append(route)

    def add_receiver(self, name, **kwargs):
        """
        Add a receiver

        Receiver names should be unique
        """
        receiver = OrderedDict({'name': name})

        # Make sure we don't add duplicates
        for r in self._config['receivers']:
            if r['name'] == name:
                msg = "receiver {} already exists in the config".format(name)
                raise(DuplicateReceiver(msg))

        for k, v in kwargs.items():
            if isinstance(v, list):
                receiver[k] = v
            else:
                raise(InvalidType("receiver config must be a list"))

        self._config['receivers'].append(receiver)

    def add_slack_receiver(self, name, params={}):
        self.add_receiver(name, slack_configs=[params])

    def add_email_receiver(self, name, params={}):
        self.add_receiver(name, email_configs=[params])

    def add_pagerduty_receiver(self, name, params={}):
        self.add_receiver(name, pagerduty_configs=[params])

    def add_webhook_receiver(self, name, params={}):
        self.add_receiver(name, webhook_configs=[params])

    def add_template(self, path):
        self._config.setdefault('templates', []).append(path)
