from pathlib import Path

import pytest

from tidy.domain.classification import ClassificationSource
from tidy.domain.planning import (
    PLANNING_SCHEMA_VERSION,
    MutationPlan,
    PlannedDestination,
    PlannedSource,
    PlanningBlockedReason,
    PlanningResult,
    PlanningStatus,
    PlanPrecondition,
)


def _plan() -> MutationPlan:
    return MutationPlan(
        schema_version=PLANNING_SCHEMA_VERSION,
        plan_id="a" * 64,
        source=PlannedSource(
            "downloads",
            Path("invoice.pdf"),
            "b" * 64,
            10,
            20,
        ),
        destination=PlannedDestination("documents", (), "invoice.pdf"),
        authorized_directories=(),
        preconditions=(PlanPrecondition.DESTINATION_MUST_NOT_EXIST,),
        classification_label="DOCUMENT",
        classification_source=ClassificationSource.KNOWN_SYSTEM_RULE,
        policy_id="documents.document",
    )


def test_s3_a06_planned_result_requires_mutation_plan_and_no_reason() -> None:
    with pytest.raises(ValueError):
        PlanningResult(PlanningStatus.PLANNED, None, None)
    with pytest.raises(ValueError):
        PlanningResult(PlanningStatus.PLANNED, object(), None)
    with pytest.raises(ValueError):
        PlanningResult(
            PlanningStatus.PLANNED,
            _plan(),
            PlanningBlockedReason.NO_DESTINATION_POLICY,
        )
    valid = PlanningResult(PlanningStatus.PLANNED, _plan(), None)
    assert valid.plan == _plan()


def test_s3_a07_blocked_result_requires_no_plan_and_typed_reason() -> None:
    with pytest.raises(ValueError):
        PlanningResult(PlanningStatus.BLOCKED, None, None)
    with pytest.raises(ValueError):
        PlanningResult(
            PlanningStatus.BLOCKED,
            _plan(),
            PlanningBlockedReason.NO_DESTINATION_POLICY,
        )
    with pytest.raises(ValueError):
        PlanningResult(PlanningStatus.BLOCKED, None, "no_destination_policy")
    valid = PlanningResult(
        PlanningStatus.BLOCKED,
        None,
        PlanningBlockedReason.NO_DESTINATION_POLICY,
    )
    assert valid.plan is None
