import copy
import yaml


class InvalidType(Exception):
    pass


class YamlEntity(object):
    def __init__(self):
        self.data = dict()

    def __str__(self):
        return yaml.dump(self.data)

    def __getstate__(self):
        return self.data


class Config(YamlEntity):
    def __init__(self, default_route):
        super(Config, self).__init__()
        self.data['global'] = {}
        self.data['route'] = default_route
        self.data['receivers'] = []
        self.data['inhibit_rules'] = []
        self.data['templates'] = []

    def add_inhibit_rule(self, rule):
        if not type(rule) == dict:
            raise(InvalidType("Expected {}, got {}".format(
                dict.__name__,
                type(rule),
            )))

        # TODO make sure we do not add a duplicate receiver (name)
        self.data['inhibit_rules'].append(rule)

    def add_receiver(self, receiver):
        if not isinstance(receiver, Receiver):
            raise(InvalidType("Expected {}, got {}".format(
                Receiver.__name__,
                type(receiver),
            )))

        # TODO make sure we do not add a duplicate receiver (name)
        self.data['receivers'].append(receiver)

        return self

    def add_route(self, route):
        if not isinstance(route, Route):
            raise(InvalidType("Expected {}, got {}".format(
                Route.__name__,
                type(route),
            )))

        self.data['route'].add_route(route)
        
        return self

    def add_template(self, path):
        self.data['templates'].append(path)

    def set_global(self, key, value):
        self.data['global'][key] = value

    def render(self):
        return self.render_yaml()

    def render_yaml(self):
        # Turn off yaml tags
        yaml.emitter.Emitter.process_tag = lambda x: None

        #Turn off yaml aliases (anchors/references)
        yaml.Dumper.ignore_aliases = lambda *args: True

        return yaml.dump(self.data)

class Receiver(YamlEntity):
    def __init__(self, name):
        super(Receiver, self).__init__()
        self.data['name'] = name

    @property
    def name(self):
        return self.data['name']

    def __str__(self):
        return yaml.dump(self.data)

    def __getstate__(self):
        return self.data


class SlackConfig(YamlEntity):
    def __init__(self, channel, **kwargs):
        super(SlackConfig, self).__init__()
        self.data = {
            'channel': channel,
        }

        for k, v in kwargs.items():
            k = k.lstrip('__')
            self.data[k] = v


class SlackReceiver(Receiver):
    def __init__(self, name):
        super(SlackReceiver, self).__init__(name)
        self.data['slack_configs'] = []

    def add_slack_config(self, config):
        if not isinstance(config, SlackConfig):
            raise(InvalidType("Expected {}, got {}".format(
                SlackConfig.__name__,
                type(config),
            )))
        self.data['slack_configs'].append(config)
        return self


class EmailConfig(YamlEntity):
    def __init__(self, to, **kwargs):
        super(EmailConfig, self).__init__()
        self.data = {
            'to': to,
        }

        for k, v in kwargs.items():
            k = k.lstrip('__')
            self.data[k] = v


class EmailReceiver(Receiver):
    def __init__(self, name):
        super(EmailReceiver, self).__init__(name)
        self.data['email_configs'] = []

    def add_email_config(self, config):
        if not isinstance(config, EmailConfig):
            raise(InvalidType("Expected {}, got {}".format(
                EmailConfig.__name__,
                type(config),
            )))
        self.data['email_configs'].append(config)
        return self


class PagerdutyConfig(YamlEntity):
    def __init__(self, service_key, **kwargs):
        super(PagerdutyConfig, self).__init__()
        self.data = {
            'service_key': service_key,
        }

        for k, v in kwargs.items():
            k = k.lstrip('__')
            self.data[k] = v


class PagerdutyReceiver(Receiver):
    def __init__(self, name):
        super(PagerdutyReceiver, self).__init__(name)
        self.data['pagerduty_configs'] = []

    def add_pagerduty_config(self, config):
        if not isinstance(config, PagerdutyConfig):
            raise(InvalidType("Expected {}, got {}".format(
                PagerdutyConfig.__name__,
                type(config),
            )))
        self.data['pagerduty_configs'].append(config)
        return self


class Route(YamlEntity):
    def __init__(self, receiver, **kwargs):
        super(Route, self).__init__()
        self.data['receiver'] = receiver
        
        for k, v in kwargs.items():
            k = k.lstrip('__')
            self.data[k] = v

    @property
    def receiver(self):
        return self.data['receiver']

    def add_route(self, route):
        if not isinstance(route, Route):
            raise(InvalidType("Expected {}, got {}".format(
                Route.__name__,
                type(route),
            )))
        self.data.setdefault('routes', []).append(route)
        return self

    def group_by(self, items):
        self.data['group_by'] = items
        return self

    def set_match(self, k, v):
        if type(v) == list:
            regex = "^(?:^({})$)$".format('|'.join(v))
            self.data['match_re'] = {k: regex}
        else:
            self.data['match'] = {k: v}
