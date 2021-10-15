import os

import jinja2

from reconcile import templates


def get_package_environment():
    """Loads templates from the current Python package"""
    templates_dir = os.path.dirname(templates.__file__)
    template_loader = jinja2.FileSystemLoader(searchpath=templates_dir)
    return jinja2.Environment(loader=template_loader)
