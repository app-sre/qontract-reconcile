from reconcile import queries


def full_name(app):
    """Builds App full_name, prepending the App with the name
    of the parent App.

    :param app: App as returned by queries.get_apps()
    :type app: dict
    :return: full name of the app
    :rtype: string
    """
    name = app["name"]
    if app.get("parentApp"):
        parent_app = app["parentApp"]["name"]
        name = f"{parent_app}/{name}"
    return name


def get_latest_sre_checkpoints():
    """Builds dictionary with the full_name of the app as the key and the
    date of sre_checkpoint as the value.

    :return: dictionary with the latest checkpoints
    :rtype: dict
    """
    checkpoints = {}
    for checkpoint in queries.get_sre_checkpoints():
        name = full_name(checkpoint["app"])
        date = checkpoint["date"]
        checkpoints[name] = max(checkpoints.get(name, ""), date)
    return checkpoints
