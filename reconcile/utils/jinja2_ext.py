import base64
import textwrap

from jinja2 import nodes
from jinja2.ext import Extension
from jinja2.exceptions import TemplateRuntimeError


class B64EncodeExtension(Extension):
    tags = {'b64encode'}

    def parse(self, parser):
        lineno = next(parser.stream).lineno

        body = parser.parse_statements(['name:endb64encode'], drop_needle=True)

        return nodes.CallBlock(self.call_method('_b64encode', None),
                               [], [], body).set_lineno(lineno)

    @staticmethod
    def _b64encode(caller):
        content = caller()
        content = textwrap.dedent(content)
        return base64.b64encode(content.encode()).decode('utf-8')


class RaiseErrorExtension(Extension):
    tags = {'raise_error'}

    def parse(self, parser):
        lineno = next(parser.stream).lineno

        msg = parser.parse_expression()

        return nodes.CallBlock(
            self.call_method('_raise_error', [msg], lineno=lineno),
            [], [], [], lineno=lineno
        )

    @staticmethod
    def _raise_error(msg, caller):
        raise TemplateRuntimeError(msg)
