"""
terrascript/__init__.py

Base classes and functions that are used elsewhere in
this project.

This module is taken from https://github.com/mjuenema/python-terrascript
We are not using python-terrascript as it is not suitable for python 2
due to a single import statement (documented below)
After we migrate to python 3, this entire module can be removed
and a 'terrascript' requirement should be added to 'setup.py'
"""

__author__ = 'Markus Juenemann <markus@juenemann.net>'
__version__ = '0.6.0'
__license__ = 'BSD 2-clause "Simplified" License'

INDENT = 2
"""JSON indentation level."""

SORT = True
"""Whether to sort keys when generating JSON."""

DEBUG = False
"""Set to enable some debugging."""

import logging 
import os
import shutil
# from collections import defaultdict, UserDict
# The previous line is replaced by the 2 following lines
# in order to work with python 2
from collections import defaultdict
try:
    from collections import UserDict
except ImportError:
    from six.moves import UserDict

logger = logging.getLogger(__name__)


THREE_TIER_ITEMS = ['data', 'resource', 'provider']
TWO_TIER_ITEMS = ['variable', 'module', 'output', 'provisioner']
ONE_TIER_ITEMS = ['terraform']


class _Config(dict):
    def __getitem__(self, key):
        try:
            return super(_Config, self).__getitem__(key)
        except KeyError:
            # Work-around for issue 3 as described in https://github.com/hashicorp/terraform/issues/13037:
            # Make 'data' a list of a single dictionary.
            if key == 'data':
                super(_Config, self).__setitem__(key, [defaultdict(dict)])
            elif key in THREE_TIER_ITEMS:
                super(_Config, self).__setitem__(key, defaultdict(dict))
            elif key in TWO_TIER_ITEMS:
                super(_Config, self).__setitem__(key, {})
            else:
                raise KeyError(key)

        return super(_Config, self).__getitem__(key)


class Terrascript(object):
    """Top-level container for Terraform configurations."""

    def __init__(self):

        self.config = _Config()
        self._item_list = []

    def __add__(self, item):
        # Does not add EMPTY values
        clone = item._kwargs.copy()
        for k in clone:
            if item._kwargs[k] is None:
                del item._kwargs[k]

        # Work-around for issue 3 as described in https://github.com/hashicorp/terraform/issues/13037:
        # Make 'data' a list of a single dictionary.
        if item._class == 'data':
            self.config[item._class][0][item._type][item._name] = item._kwargs
        elif item._class in THREE_TIER_ITEMS:
            self.config[item._class][item._type][item._name] = item._kwargs
        elif item._class in TWO_TIER_ITEMS:
            self.config[item._class][item._name] = item._kwargs
        elif item._class in ONE_TIER_ITEMS:
            self.config[item._class] = item._kwargs
        else:
            raise KeyError(item)

        if not isinstance(item, Terrascript):
            if item in self._item_list:
                self._item_list.remove(item)
            self._item_list.append(item)

        return self

    def add(self, item):
        self.__add__(item)
        return item

    def update(self, terrascript2):
        if isinstance(terrascript2, Terrascript):
            for item in terrascript2._item_list:
                self.__add__(item)
        else:
            raise TypeError('{0} is not a Terrascript instance.'.format(
                type(terrascript2)))

    def dump(self):
        """Return the JSON representaion of config."""
        import json

        def _json_default(v):
            # How to encode non-standard objects
            if isinstance(v, provisioner):
                return {v._type: v.data}
            elif isinstance(v, UserDict):
                return v.data
            else:
                return str(v)

        # Work on copy of _Config but with unused top-level elements removed.
        #
        config = {k: v for k,v in self.config.items() if v}
        return json.dumps(config, indent=INDENT, sort_keys=SORT, default=_json_default)


    def validate(self, tmpdir):
        """Validate a Terraform configuration."""
        import subprocess

        # Validate configuration
        proc = subprocess.Popen(['terraform','validate','-check-variables=false'], cwd=tmpdir,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.communicate()

        return proc.returncode == 0


class _base(object):
    _class = None
    """One of 'resource', 'data', 'module', etc."""

    _type = None
    """The resource type, e.g. 'aws_instance'."""

    _name = None
    """The name of this resource, e.g. 'my_ec2_instance'."""

    def __init__(self, name_, **kwargs):
        if not self._type:
            self._type = self.__class__.__name__
        self._name = name_
        self._kwargs = kwargs


    def __getattr__(self, name):
        """References to attributes."""
        if self._class == 'resource':
            return '${{{}.{}.{}}}'.format(self._type, self._name, name)
        elif self._class == 'module':
            return '${{module.{}.{}}}'.format(self._name, name)
        else:
            return '${{{}.{}.{}.{}}}'.format(self._class, self._type, self._name, name)

    def __getitem__(self, i):
        if isinstance(i, int):
            # "${var.NAME[i]}"
            return '${{var.{}[{}]}}'.format(self._name, i)
        else:
            # "${var.NAME["i"]}"
            return "${{var.{}[\"{}\"]}}".format(self._name, i)

    def __repr__(self):
        """References to objects."""
        if self._class == 'variable':
            """Interpolated reference to a variable, e.g. ``${var.http_port}``."""
            return self.interpolated
        else:
            """Non-interpolated reference to a non-resource, e.g. ``module.http``."""
            return self.fullname

    @property
    def interpolated(self):
        """The object in interpolated syntax: ``${...}``."""
        return '${{{}}}'.format(self.fullname)

    @property
    def fullname(self):
        """The object's full name."""
        if self._class == 'variable':
            return 'var.{}'.format(self._name)
        elif self._class == 'resource':
            return '{}.{}'.format(self._type, self._name)
        else:
            return '{}.{}'.format(self._class, self._name)


class _resource(_base):
    """Base class for resources."""
    _class = 'resource'


class _data(_base):
    """Base class for data sources."""
    _class = 'data'

    def __init__(self, obj_name, **kwargs):
        super(_data, self).__init__(obj_name, **kwargs)


class resource(_base):
    """Class for creating a resource for which no convenience wrapper exists."""
    _class = 'resource'

    def __init__(self, type_, name, **kwargs):
        self._type = type_
        super(resource, self).__init__(name, **kwargs)


class data(_base):
    """Class for creating a data source for which no convenience wrapper exists."""
    _class = 'data'

    def __init__(self, type_, name, **kwargs):
        self._type = type_
        super(data, self).__init__(name, **kwargs)


class module(_base):
    _class = 'module'


class variable(_base):
    _class = 'variable'


class output(_base):
    _class = 'output'


class provider(_base):
    _class = 'provider'

    def __init__(self, name, **kwargs):
       alias = kwargs.get('alias', '__DEFAULT__')
       self._type = name
       super(provider, self).__init__(alias, **kwargs)


class terraform(_base):
    _class = 'terraform'
    def __init__(self, **kwargs):
        # Terraform does not have a name
        super(terraform, self).__init__(None, **kwargs)


class provisioner(UserDict):
    def __init__(self, type_, **kwargs):
       self._type = type_
       self.data = kwargs


class connection(UserDict):
    def __init__(self,  **kwargs):
        self.data = kwargs


class backend(UserDict):
    def __init__(self,  name, **kwargs):
        self.data = {name: kwargs}


class _function(object):
    """Terraform function.

       >>> function.lookup(map, key)
       "${lookup(map, key)}"

    """

    class _function(object):
        def __init__(self, name):
            self.name = name

        def format(self, arg):
            """Format a function argument."""
            if isinstance(arg, _base):
                return arg.fullname
            elif isinstance(arg, str):
                return '"{}"'.format(arg)
            else:
                return arg

        def __call__(self, *args):
            return '${{{}({})}}'.format(self.name, ','.join([self.format(arg) for arg in args]))

    def __getattr__(self, name):
        return self._function(name)

f = fn = func = function = _function()
"""Shortcuts for `function()`."""


__all__ = ['Terrascript',
           'resource', 'data', 'module', 'variable',
           'output', 'terraform', 'provider', 
           'provisioner', 'connection', 'backend',
           'f', 'fn', 'func', 'function']
