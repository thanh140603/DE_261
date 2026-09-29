"""RuleRepository adapter loading rules from infra/notification/rules.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from edu_platform.contexts.notification.domain.model import Channel, NotificationRule, Priority


class YamlRuleRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def all(self) -> list[NotificationRule]:
        doc = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        return [
            NotificationRule(
                rule_id=str(r["rule_id"]),
                event_type=str(r["event_type"]),
                channels=tuple(Channel(c) for c in r.get("channels", [])),
                priority=Priority(r.get("priority", "normal")),
                condition=r.get("condition"),
                template_id=str(r.get("template_id", "")),
                audience=str(r.get("audience", "learner")),
                enabled=bool(r.get("enabled", True)),
            )
            for r in doc.get("rules", [])
        ]
