"""Jinja2 template rendering utilities."""

from typing import Any

import jinja2


def render_template(template: str, **variables: Any) -> str:
    """Render a Jinja2 template string with the given variables.

    Uses strict undefined mode (raises on missing variables),
    trims blocks, and strips leading whitespace from blocks.

    Args:
        template: Jinja2 template string
        **variables: Template variables

    Returns:
        Rendered template string
    """
    return jinja2.Template(
        template,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    ).render(variables)
