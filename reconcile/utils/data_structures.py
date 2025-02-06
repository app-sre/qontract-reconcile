def get_or_init(d, k, v):
    """Gets (or initiates) a value in a dictionary key

    Args:
        d (dict): dictionary to work
        k (hashable): key to use
        v (value): value to initiate if key doesn't exist

    Returns:
        [type]: [description]
    """
    d.setdefault(k, v)
    return d[k]
