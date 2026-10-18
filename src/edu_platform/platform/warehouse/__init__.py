"""Lakehouse warehouse runtime: model registry, SQL rendering and the Spark runner.

The SQL itself lives in the repo-level ``warehouse/`` folder (ddl/, transform/, quality/,
models.yaml); this package only knows how to execute it.
"""
