"""Grading Ingestion Service (BR3) entrypoint.

Run: ``uvicorn edu_platform.entrypoints.services.grading_ingestion.app:app``
with ``EDU_ENV=docker`` (or ``python -m edu_platform.entrypoints.services.grading_ingestion.main``).
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    from edu_platform.entrypoints.services.grading_ingestion.app import build_app
    from edu_platform.platform.config import get_settings

    app = build_app(get_settings())
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("EDU_GRADING_PORT", "8001")))


if __name__ == "__main__":
    main()
