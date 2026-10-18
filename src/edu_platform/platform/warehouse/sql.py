"""SQL file rendering for the warehouse runner (pure, engine-free).

Templates use ``${name}`` placeholders. Only the braced form is a placeholder, so JSON paths
such as ``'$.learner_id'`` pass through untouched. Rendering is strict: a missing parameter is
an error rather than an empty string silently changing a predicate.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_COMMENT_LINE = re.compile(r"^\s*--.*$", re.MULTILINE)
_STATEMENT_END = re.compile(r";\s*$", re.MULTILINE)


def render(template: str, params: Mapping[str, object]) -> str:
    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            raise KeyError(f"SQL template parameter {name!r} is not defined")
        return str(params[name])

    return _PLACEHOLDER.sub(substitute, template)


def split_statements(sql: str) -> list[str]:
    """Split a rendered file into statements: full-line comments dropped, ';' at line end."""
    body = _COMMENT_LINE.sub("", sql)
    return [s.strip() for s in _STATEMENT_END.split(body) if s.strip()]
