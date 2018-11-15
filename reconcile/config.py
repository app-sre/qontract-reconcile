import toml

_config = None


def get_config():
    global _config
    return _config


def init(config):
    global _config
    _config = config
    return _config


def init_from_toml(configfile):
    return init(toml.load(configfile))
