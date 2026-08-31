from fnmatch import fnmatchcase

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
from tidy.domain.evidence import FileEvidence

_GLOB_TYPES = {
    RuleConditionType.FILENAME_GLOB,
    RuleConditionType.RELATIVE_PATH_GLOB,
}


def _condition_is_valid(condition: object) -> bool:
    if not isinstance(condition, RuleCondition):
        return False
    if not isinstance(condition.condition_type, RuleConditionType):
        return False
    if type(condition.operand) is not str or condition.operand == "":
        return False

    if condition.condition_type in _GLOB_TYPES:
        if "**" in condition.operand:
            return False
        if "[" in condition.operand or "]" in condition.operand:
            return False

    if (
        condition.condition_type is RuleConditionType.FILENAME_GLOB
        and "/" in condition.operand
    ):
        return False

    return True


def validate_rule_configuration(
    confirmed_user_rules: tuple[ClassificationRule, ...],
    known_system_rules: tuple[ClassificationRule, ...],
) -> bool:
    if not isinstance(confirmed_user_rules, tuple):
        return False
    if not isinstance(known_system_rules, tuple):
        return False

    seen_ids: set[str] = set()
    groups = (
        (RuleAuthority.CONFIRMED_USER_RULE, confirmed_user_rules),
        (RuleAuthority.KNOWN_SYSTEM_RULE, known_system_rules),
    )

    for expected_authority, rules in groups:
        for rule in rules:
            if not isinstance(rule, ClassificationRule):
                return False
            if type(rule.rule_id) is not str or rule.rule_id == "":
                return False
            if rule.rule_id in seen_ids:
                return False
            seen_ids.add(rule.rule_id)

            if not isinstance(rule.authority, RuleAuthority):
                return False
            if rule.authority is not expected_authority:
                return False
            if type(rule.priority) is not int:
                return False
            if type(rule.label) is not str or rule.label == "":
                return False
            if not isinstance(rule.conditions, tuple) or not rule.conditions:
                return False
            if not all(
                _condition_is_valid(condition)
                for condition in rule.conditions
            ):
                return False

    return True


def _glob_matches(value: str, pattern: str) -> bool:
    value_parts = value.casefold().split("/")
    pattern_parts = pattern.casefold().split("/")
    return len(value_parts) == len(pattern_parts) and all(
        fnmatchcase(value_part, pattern_part)
        for value_part, pattern_part in zip(
            value_parts,
            pattern_parts,
            strict=True,
        )
    )


def _condition_matches(
    evidence: FileEvidence,
    condition: RuleCondition,
) -> bool:
    operand = condition.operand.casefold()

    if condition.condition_type is RuleConditionType.FILENAME_EQUALS:
        return evidence.filename.casefold() == operand
    if condition.condition_type is RuleConditionType.FILENAME_GLOB:
        return _glob_matches(evidence.filename, condition.operand)
    if condition.condition_type is RuleConditionType.EXTENSION_EQUALS:
        return evidence.extension.casefold() == operand
    if condition.condition_type is RuleConditionType.MIME_HINT_EQUALS:
        return (
            evidence.mime_hint is not None
            and evidence.mime_hint.casefold() == operand
        )
    if condition.condition_type is RuleConditionType.RELATIVE_PATH_GLOB:
        return _glob_matches(
            evidence.relative_path.as_posix(),
            condition.operand,
        )

    return False


def _rule_matches(
    evidence: FileEvidence,
    rule: ClassificationRule,
) -> bool:
    return all(
        _condition_matches(evidence, condition)
        for condition in rule.conditions
    )


def _source_for_authority(
    authority: RuleAuthority,
) -> ClassificationSource:
    if authority is RuleAuthority.CONFIRMED_USER_RULE:
        return ClassificationSource.CONFIRMED_USER_RULE
    return ClassificationSource.KNOWN_SYSTEM_RULE


def _unresolved(reason: UnresolvedReason) -> ClassificationResult:
    return ClassificationResult(
        status=ClassificationStatus.UNRESOLVED,
        label=None,
        source=None,
        reason=reason,
        rule_id=None,
        provider_name=None,
        provider_model=None,
        provider_confidence=None,
    )


def resolve_rule_authority(
    evidence: FileEvidence,
    allowed_labels: tuple[str, ...],
    rules: tuple[ClassificationRule, ...],
    authority: RuleAuthority,
) -> ClassificationResult | None:
    matching = tuple(
        rule for rule in rules if _rule_matches(evidence, rule)
    )
    if not matching:
        return None

    highest_priority = max(rule.priority for rule in matching)
    decisive = tuple(
        rule for rule in matching if rule.priority == highest_priority
    )
    labels = {rule.label for rule in decisive}

    if len(labels) != 1:
        return _unresolved(UnresolvedReason.RULE_CONFLICT)

    label = decisive[0].label
    if label not in allowed_labels:
        return _unresolved(UnresolvedReason.INVALID_RULE_CONFIGURATION)

    return ClassificationResult(
        status=ClassificationStatus.CLASSIFIED,
        label=label,
        source=_source_for_authority(authority),
        reason=None,
        rule_id=min(rule.rule_id for rule in decisive),
        provider_name=None,
        provider_model=None,
        provider_confidence=None,
    )
