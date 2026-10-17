from __future__ import annotations

import os

import pytest

from edu_platform.br45.verify import run


@pytest.mark.e2e
def test_real_postgres_cdc_spark_and_api(tmp_path):
    if os.getenv("EDU_BR45_E2E") != "1":
        pytest.skip("Start the BR45 Compose profile, seed data, and set EDU_BR45_E2E=1")
    result = run(output=str(tmp_path), restart=os.getenv("EDU_BR45_E2E_RESTART") == "1")
    assert result["duplicate_alert_count"] == 0
