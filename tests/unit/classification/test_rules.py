from pathlib import Path

import pytest

from tidy.classification.rules import (
    resolve_rule_authority,
    validate_rule_configuration,
)
from tidy.domain.classification import (
    ClassificationResult,
    ClassificationRule,
    ClassificationSource,
    ClassificationStatus,
    RuleAuthority,
    RuleCondition,
    RuleConditionType,
    UnresolvedReason,
)


def condition(kind: RuleConditionType, operand: str) -> RuleCondition:
    return RuleCondition(kind, operand)


def rule(
    rule_id: str,
    label: str,
    *conditions: RuleCondition,
    priority: int = 10,
    authority: RuleAuthority = RuleAuthority.CONFIRMED_USER_RULE,
) -> ClassificationRule:
    return ClassificationRule(
        rule_id=rule_id,
        authority=authority,
        priority=priority,
        label=label,
        conditions=tuple(conditions),
    )


def test_s2_a01_filename_equals_resolves_case_insensitively(
    evidence_factory,
) -> None:
    result = resolve_rule_authority(
        evidence_factory(filename="INVOICE.PDF"),
        ("DOCUMENT",),
        (
            rule(
                "user.invoice",
                "DOCUMENT",
                condition(
                    RuleConditionType.FILENAME_EQUALS,
                    "invoice.pdf",
                ),
            ),
        ),
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert result is not None
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.label == "DOCUMENT"
    assert result.source is ClassificationSource.CONFIRMED_USER_RULE
    assert result.rule_id == "user.invoice"


def test_s2_a02_filename_glob_uses_only_star_and_question_mark(
    evidence_factory,
) -> None:
    result = resolve_rule_authority(
        evidence_factory(filename="Invoice-42.PDF"),
        ("DOCUMENT",),
        (
            rule(
                "user.invoice",
                "DOCUMENT",
                condition(
                    RuleConditionType.FILENAME_GLOB,
                    "invoice-??.pdf",
                ),
            ),
        ),
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert result is not None
    assert result.label == "DOCUMENT"


def test_s2_a03_extension_equals_is_case_insensitive(
    evidence_factory,
) -> None:
    result = resolve_rule_authority(
        evidence_factory(extension=".PDF"),
        ("DOCUMENT",),
        (
            rule(
                "system.pdf",
                "DOCUMENT",
                condition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
            ),
        ),
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert result is not None
    assert result.label == "DOCUMENT"


def test_s2_a04_mime_hint_equals_and_none_is_safe(
    evidence_factory,
) -> None:
    configured = (
        rule(
            "system.pdf",
            "DOCUMENT",
            condition(
                RuleConditionType.MIME_HINT_EQUALS,
                "application/pdf",
            ),
        ),
    )

    matching = resolve_rule_authority(
        evidence_factory(mime_hint="Application/PDF"),
        ("DOCUMENT",),
        configured,
        RuleAuthority.CONFIRMED_USER_RULE,
    )
    missing = resolve_rule_authority(
        evidence_factory(mime_hint=None),
        ("DOCUMENT",),
        configured,
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert matching is not None
    assert matching.label == "DOCUMENT"
    assert missing is None


def test_s2_a05_relative_path_glob_is_relative_segment_bounded(
    evidence_factory,
) -> None:
    nested_rule = (
        rule(
            "receipt.nested",
            "RECEIPT",
            condition(
                RuleConditionType.RELATIVE_PATH_GLOB,
                "receipts/*/invoice.pdf",
            ),
        ),
    )

    misleading = resolve_rule_authority(
        evidence_factory(
            path=Path("Z:/receipts/2026/invoice.pdf"),
            relative_path=Path("other/invoice.pdf"),
        ),
        ("RECEIPT",),
        nested_rule,
        RuleAuthority.CONFIRMED_USER_RULE,
    )
    matching = resolve_rule_authority(
        evidence_factory(
            relative_path=Path("receipts/2026/invoice.pdf"),
        ),
        ("RECEIPT",),
        nested_rule,
        RuleAuthority.CONFIRMED_USER_RULE,
    )
    segment_cross = resolve_rule_authority(
        evidence_factory(
            relative_path=Path("receipts/2026/invoice.pdf"),
        ),
        ("RECEIPT",),
        (
            rule(
                "receipt.flat",
                "RECEIPT",
                condition(
                    RuleConditionType.RELATIVE_PATH_GLOB,
                    "receipts/*.pdf",
                ),
            ),
        ),
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert misleading is None
    assert matching is not None
    assert matching.label == "RECEIPT"
    assert segment_cross is None


def test_s2_a06_all_conditions_must_match(evidence_factory) -> None:
    configured = (
        rule(
            "receipt.pdf",
            "RECEIPT",
            condition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
            condition(
                RuleConditionType.FILENAME_GLOB,
                "receipt-*.pdf",
            ),
        ),
    )

    matching = resolve_rule_authority(
        evidence_factory(filename="receipt-42.pdf", extension=".PDF"),
        ("RECEIPT",),
        configured,
        RuleAuthority.CONFIRMED_USER_RULE,
    )
    nonmatching = resolve_rule_authority(
        evidence_factory(filename="invoice-42.pdf", extension=".PDF"),
        ("RECEIPT",),
        configured,
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert matching is not None
    assert nonmatching is None


def test_s2_a09_higher_priority_wins_inside_one_authority(
    evidence_factory,
) -> None:
    rules = (
        rule(
            "low",
            "IMAGE",
            condition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
            priority=1,
        ),
        rule(
            "high",
            "DOCUMENT",
            condition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
            priority=100,
        ),
    )

    result = resolve_rule_authority(
        evidence_factory(extension=".pdf"),
        ("IMAGE", "DOCUMENT"),
        rules,
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert result is not None
    assert result.label == "DOCUMENT"
    assert result.rule_id == "high"


def test_s2_a10_equal_priority_same_label_succeeds(
    evidence_factory,
) -> None:
    rules = (
        rule(
            "b",
            "DOCUMENT",
            condition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
        ),
        rule(
            "a",
            "DOCUMENT",
            condition(
                RuleConditionType.MIME_HINT_EQUALS,
                "application/pdf",
            ),
        ),
    )

    result = resolve_rule_authority(
        evidence_factory(),
        ("DOCUMENT",),
        rules,
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert result is not None
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.label == "DOCUMENT"


def test_s2_a11_same_label_tie_uses_lexicographically_lowest_rule_id(
    evidence_factory,
) -> None:
    rules = (
        rule(
            "z-rule",
            "DOCUMENT",
            condition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
        ),
        rule(
            "a-rule",
            "DOCUMENT",
            condition(
                RuleConditionType.MIME_HINT_EQUALS,
                "application/pdf",
            ),
        ),
    )

    result = resolve_rule_authority(
        evidence_factory(),
        ("DOCUMENT",),
        rules,
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert result is not None
    assert result.rule_id == "a-rule"


def test_s2_a12_equal_priority_different_labels_is_rule_conflict(
    evidence_factory,
) -> None:
    rules = (
        rule(
            "r1",
            "DOCUMENT",
            condition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
        ),
        rule(
            "r2",
            "RECEIPT",
            condition(
                RuleConditionType.MIME_HINT_EQUALS,
                "application/pdf",
            ),
        ),
    )

    result = resolve_rule_authority(
        evidence_factory(),
        ("DOCUMENT", "RECEIPT"),
        rules,
        RuleAuthority.CONFIRMED_USER_RULE,
    )

    assert result == ClassificationResult(
        status=ClassificationStatus.UNRESOLVED,
        label=None,
        source=None,
        reason=UnresolvedReason.RULE_CONFLICT,
        rule_id=None,
        provider_name=None,
        provider_model=None,
        provider_confidence=None,
    )


def _valid_condition() -> RuleCondition:
    return condition(RuleConditionType.EXTENSION_EQUALS, ".pdf")


def _configured(
    *,
    rule_id: object = "r",
    authority: object = RuleAuthority.CONFIRMED_USER_RULE,
    priority: object = 1,
    label: object = "DOCUMENT",
    conditions: object = None,
) -> tuple[object, ...]:
    if conditions is None:
        conditions = (_valid_condition(),)
    return (
        ClassificationRule(
            rule_id=rule_id,
            authority=authority,
            priority=priority,
            label=label,
            conditions=conditions,
        ),
    )


@pytest.mark.parametrize(
    "configured",
    [
        _configured(rule_id=""),
        _configured(rule_id=1),
        _configured(authority="confirmed_user_rule"),
        _configured(authority=RuleAuthority.KNOWN_SYSTEM_RULE),
        _configured(priority=True),
        _configured(priority="1"),
        _configured(label=""),
        _configured(label=2),
        _configured(conditions=()),
        _configured(conditions=[_valid_condition()]),
        _configured(conditions=("bad",)),
        _configured(
            conditions=(RuleCondition("extension_equals", ".pdf"),),
        ),
        _configured(
            conditions=(
                RuleCondition(RuleConditionType.EXTENSION_EQUALS, ""),
            ),
        ),
        _configured(
            conditions=(
                RuleCondition(RuleConditionType.EXTENSION_EQUALS, 1),
            ),
        ),
        _configured(
            conditions=(
                condition(
                    RuleConditionType.FILENAME_GLOB,
                    "folder/*.pdf",
                ),
            ),
        ),
        _configured(
            conditions=(
                condition(
                    RuleConditionType.RELATIVE_PATH_GLOB,
                    "**/*.pdf",
                ),
            ),
        ),
        _configured(
            conditions=(
                condition(
                    RuleConditionType.RELATIVE_PATH_GLOB,
                    "folder/[ab].pdf",
                ),
            ),
        ),
    ],
)
def test_structurally_invalid_rule_shapes_are_rejected(
    configured,
) -> None:
    assert not validate_rule_configuration(configured, ())


def test_duplicate_rule_ids_across_authorities_are_invalid() -> None:
    shared = _valid_condition()
    assert not validate_rule_configuration(
        (rule("same", "DOCUMENT", shared),),
        (
            rule(
                "same",
                "IMAGE",
                shared,
                authority=RuleAuthority.KNOWN_SYSTEM_RULE,
            ),
        ),
    )


def test_rule_collections_must_be_tuples() -> None:
    assert not validate_rule_configuration([], ())
    assert not validate_rule_configuration((), [])


def test_nonmatching_disallowed_label_is_not_structurally_invalid(
    evidence_factory,
) -> None:
    configured = (
        rule(
            "zip",
            "NOT_ALLOWED",
            condition(RuleConditionType.EXTENSION_EQUALS, ".zip"),
        ),
    )

    assert validate_rule_configuration(configured, ())
    assert (
        resolve_rule_authority(
            evidence_factory(extension=".pdf"),
            ("DOCUMENT",),
            configured,
            RuleAuthority.CONFIRMED_USER_RULE,
        )
        is None
    )
