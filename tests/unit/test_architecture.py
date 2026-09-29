"""Architecture guardrails (lightweight import-linter).

- domain packages must not import application/infrastructure/platform or any engine.
- application packages must not import infrastructure or engines.
- contexts may import another context's *domain* package only (its published
  language, e.g. telemetry.LearningEvent, grading.Submission), never its
  application or infrastructure.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "edu_platform"
CONTEXTS = SRC / "contexts"
ENGINES = ("pyspark", "pyflink", "confluent_kafka", "redis", "boto3", "delta")


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _files(layer: str) -> list[pathlib.Path]:
    return sorted(CONTEXTS.glob(f"*/{layer}/**/*.py"))


@pytest.mark.parametrize("path", _files("domain"), ids=lambda p: str(p.relative_to(SRC)))
def test_domain_is_pure(path: pathlib.Path) -> None:
    for name in _imports(path):
        assert not name.startswith(ENGINES), f"{path}: domain imports engine {name}"
        assert ".application" not in name and ".infrastructure" not in name, f"{path}: {name}"
        assert not name.startswith("edu_platform.platform"), f"{path}: {name}"


@pytest.mark.parametrize("path", _files("application"), ids=lambda p: str(p.relative_to(SRC)))
def test_application_has_no_infrastructure(path: pathlib.Path) -> None:
    for name in _imports(path):
        assert not name.startswith(ENGINES), f"{path}: application imports engine {name}"
        assert ".infrastructure" not in name, f"{path}: {name}"


@pytest.mark.parametrize(
    "path", sorted(CONTEXTS.glob("*/**/*.py")), ids=lambda p: str(p.relative_to(SRC))
)
def test_contexts_only_share_published_language(path: pathlib.Path) -> None:
    own = path.relative_to(CONTEXTS).parts[0]
    for name in _imports(path):
        if name.startswith("edu_platform.contexts."):
            parts = name.split(".")
            if parts[2] != own:
                assert len(parts) > 3 and parts[3] == "domain", (
                    f"{path}: cross-context import of non-domain module {name}"
                )
