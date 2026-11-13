from __future__ import annotations

import json
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from .advisor import CoursePolicy, Note, NoteBody, PolicyChange
from .api import RefreshBody
from .contracts import CONTRACTS
from .db import ROOT
from .outputs import Alert, AssessmentPage, JobStatus, Metric, Risk


class ActivityDelta(BaseModel):
    event_id: str = Field(min_length=1)
    student_id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    event_time: AwareDatetime
    delta: Literal[-1, 0, 1]
    kind: Literal["activity", "clock", "metadata"]


def main() -> None:
    root = ROOT / "schemas/br45/v1"
    root.mkdir(parents=True, exist_ok=True)
    models: dict[str, type[BaseModel]] = {
        **CONTRACTS,
        "activity_delta": ActivityDelta,
        "assessment_metric": Metric,
        "student_risk": Risk,
        "dropout_alert": Alert,
    }
    for name, model in models.items():
        (root / f"{name}.schema.json").write_text(
            json.dumps(model.model_json_schema(), indent=2) + "\n"
        )

    root = root.parent / "v2"
    root.mkdir(exist_ok=True)
    contracts: dict[str, type[BaseModel]] = {
        "assessment_page": AssessmentPage,
        "assessment_job": JobStatus,
        "assessment_request": RefreshBody,
        "course_policy": CoursePolicy,
        "course_policy_change": PolicyChange,
        "intervention_note": Note,
        "intervention_note_request": NoteBody,
    }
    for name, contract in contracts.items():
        (root / f"{name}.schema.json").write_text(
            json.dumps(contract.model_json_schema(), indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
