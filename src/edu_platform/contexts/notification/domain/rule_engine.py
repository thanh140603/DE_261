"""Domain service: match an incoming event against NotificationRules (BR1).

Conditions use a deliberately tiny expression language so rules can live in
YAML and be evaluated safely (no eval): ``<field> <op> <literal>`` joined by
``and``. Operators: <, <=, >, >=, ==, !=.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable
from typing import Any

from edu_platform.shared_kernel.domain import InvariantViolation

from .model import NotificationRule, Priority

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    ">": operator.gt,
}
_CLAUSE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*(<=|>=|==|!=|<|>)\s*(.+?)\s*$")
_PRIORITY_ORDER = {Priority.HIGH: 0, Priority.NORMAL: 1, Priority.LOW: 2}


def _literal(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith(("'", '"')) and raw.endswith(raw[0]):
        return raw[1:-1]
    if raw in {"true", "false"}:
        return raw == "true"
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return raw


def evaluate_condition(condition: str, payload: dict[str, Any]) -> bool:
    for clause in condition.split(" and "):
        m = _CLAUSE.match(clause)
        if not m:
            raise InvariantViolation(f"unparseable rule condition {clause!r}")
        field, op, literal = m.groups()
        value = payload.get(field)
        if value is None:
            return False
        try:
            if not _OPS[op](value, _literal(literal)):
                return False
        except TypeError:
            return False
    return True


class RuleEngine:
    def __init__(self, rules: list[NotificationRule]) -> None:
        self._rules = [r for r in rules if r.enabled]

    def match(self, event_type: str, payload: dict[str, Any]) -> list[NotificationRule]:
        matched = [
            r
            for r in self._rules
            if r.event_type == event_type
            and (r.condition is None or evaluate_condition(r.condition, payload))
        ]
        return sorted(matched, key=lambda r: _PRIORITY_ORDER[r.priority])
