import toml

_config = None


class ConfigNotFound(Exception):
    pass


class SecretNotFound(Exception):
    pass


def get_config():
    global _config
    return _config


def init(config):
    global _config
    _config = config
    return _config


def init_from_toml(configfile):
    return init(toml.load(configfile))


def read(secret):
    path = secret["path"]
    field = secret["field"]
    try:
        path_tokens = path.split("/")
        config = get_config()
        for t in path_tokens:
            config = config[t]
        return config[field]
    except Exception as e:
        raise SecretNotFound(f"key not found in config file {path}: {str(e)}")


def read_all(secret):
    path = secret["path"]
    try:
        path_tokens = path.split("/")
        config = get_config()
        for t in path_tokens:
            config = config[t]
        return config
    except Exception as e:
        raise SecretNotFound(f"secret {path} not found in config file: {str(e)}")
