import pytest

import tidy.classification.service as service_module
from tidy.classification.provider import (
    ProviderClassification,
    ProviderClassificationRequest,
)
from tidy.classification.service import ClassificationService
from tidy.domain.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    ClassificationRequest,
    ClassificationRule,
    ClassificationSource,
    ClassificationStatus,
    RuleAuthority,
    RuleCondition,
    RuleConditionType,
    UnresolvedReason,
)


class RecordingProvider:
    provider_name = "test-provider"
    provider_model = "test-model"

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls = 0
        self.requests: list[object] = []

    def classify(self, request: object) -> object:
        self.calls += 1
        self.requests.append(request)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class ExplodingProvider(RecordingProvider):
    def __init__(self) -> None:
        super().__init__(AssertionError("provider must not be called"))


def condition(kind: RuleConditionType, operand: str) -> RuleCondition:
    return RuleCondition(kind, operand)


def rule(
    rule_id: str,
    label: str,
    kind: RuleConditionType,
    operand: str,
    *,
    authority: RuleAuthority = RuleAuthority.CONFIRMED_USER_RULE,
    priority: int = 10,
) -> ClassificationRule:
    return ClassificationRule(
        rule_id=rule_id,
        authority=authority,
        priority=priority,
        label=label,
        conditions=(condition(kind, operand),),
    )


def request(
    evidence,
    labels: object = ("DOCUMENT", "IMAGE", "RECEIPT"),
    schema: str = CLASSIFICATION_SCHEMA_VERSION,
) -> ClassificationRequest:
    return ClassificationRequest(evidence, labels, schema)


def assert_unresolved(result, reason: UnresolvedReason) -> None:
    assert result.status is ClassificationStatus.UNRESOLVED
    assert result.label is None
    assert result.source is None
    assert result.reason is reason
    assert result.rule_id is None
    assert result.provider_confidence is None


def test_s2_a07_nonmatching_rule_falls_through_to_provider(
    evidence_factory,
) -> None:
    provider = RecordingProvider(
        ProviderClassification("DOCUMENT", False, None)
    )
    service = ClassificationService(
        (
            rule(
                "zip",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".zip",
            ),
        ),
        (),
        provider,
    )

    result = service.classify(request(evidence_factory(extension=".pdf")))

    assert result.source is ClassificationSource.MODEL_INFERENCE
    assert provider.calls == 1


def test_s2_a08_confirmed_user_rule_beats_higher_priority_system_rule(
    evidence_factory,
) -> None:
    provider = ExplodingProvider()
    service = ClassificationService(
        (
            rule(
                "user",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
                priority=1,
            ),
        ),
        (
            rule(
                "system",
                "IMAGE",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
                authority=RuleAuthority.KNOWN_SYSTEM_RULE,
                priority=999,
            ),
        ),
        provider,
    )

    result = service.classify(request(evidence_factory()))

    assert result.label == "DOCUMENT"
    assert result.source is ClassificationSource.CONFIRMED_USER_RULE
    assert provider.calls == 0


def test_s2_a13_rule_conflict_makes_zero_provider_calls(
    evidence_factory,
) -> None:
    provider = ExplodingProvider()
    service = ClassificationService(
        (
            rule(
                "a",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
            ),
            rule(
                "b",
                "IMAGE",
                RuleConditionType.MIME_HINT_EQUALS,
                "application/pdf",
            ),
        ),
        (),
        provider,
    )

    result = service.classify(request(evidence_factory()))

    assert_unresolved(result, UnresolvedReason.RULE_CONFLICT)
    assert provider.calls == 0


def test_s2_a14_disallowed_decisive_rule_makes_zero_provider_calls(
    evidence_factory,
) -> None:
    provider = ExplodingProvider()
    service = ClassificationService(
        (
            rule(
                "secret",
                "SECRET",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
            ),
        ),
        (),
        provider,
    )

    result = service.classify(request(evidence_factory(), ("DOCUMENT",)))

    assert_unresolved(result, UnresolvedReason.INVALID_RULE_CONFIGURATION)
    assert provider.calls == 0


def test_s2_a15_provider_is_called_exactly_once_after_no_rule_match(
    evidence_factory,
) -> None:
    provider = RecordingProvider(
        ProviderClassification("DOCUMENT", False, None)
    )

    result = ClassificationService((), (), provider).classify(
        request(evidence_factory())
    )

    assert result.status is ClassificationStatus.CLASSIFIED
    assert provider.calls == 1


def test_s2_a16_provider_receives_provider_request_not_service_request(
    evidence_factory,
) -> None:
    provider = RecordingProvider(
        ProviderClassification("DOCUMENT", False, None)
    )
    service_request = request(evidence_factory())

    ClassificationService((), (), provider).classify(service_request)

    assert provider.calls == 1
    assert isinstance(provider.requests[0], ProviderClassificationRequest)
    assert not isinstance(provider.requests[0], ClassificationRequest)


def test_s2_a22_provider_exception_becomes_provider_unavailable(
    evidence_factory,
) -> None:
    provider = RecordingProvider(RuntimeError("offline"))

    result = ClassificationService((), (), provider).classify(
        request(evidence_factory())
    )

    assert_unresolved(result, UnresolvedReason.PROVIDER_UNAVAILABLE)
    assert result.provider_name == "test-provider"
    assert result.provider_model == "test-model"


def test_s2_a23_provider_failure_has_no_retry(evidence_factory) -> None:
    provider = RecordingProvider(RuntimeError("offline"))

    ClassificationService((), (), provider).classify(
        request(evidence_factory())
    )

    assert provider.calls == 1


def test_s2_a29_original_file_evidence_and_excluded_fields_never_reach_adapter(
    evidence_factory,
) -> None:
    evidence = evidence_factory()
    provider = RecordingProvider(
        ProviderClassification("DOCUMENT", False, None)
    )

    ClassificationService((), (), provider).classify(request(evidence))

    captured = provider.requests[0]
    assert isinstance(captured, ProviderClassificationRequest)
    assert captured.evidence.relative_path == evidence.relative_path.as_posix()
    for forbidden in (
        "path",
        "inbox_id",
        "size_bytes",
        "modified_ns",
        "sha256",
        "observed_at",
    ):
        assert not hasattr(captured.evidence, forbidden)


def test_s2_a37_no_provider_call_leaves_all_provider_fields_none(
    evidence_factory,
) -> None:
    result = ClassificationService(
        (
            rule(
                "pdf",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
            ),
        ),
        (),
        ExplodingProvider(),
    ).classify(request(evidence_factory()))

    assert result.provider_name is None
    assert result.provider_model is None
    assert result.provider_confidence is None


def test_s2_a38_confirmed_decision_skips_system_resolution_and_provider(
    evidence_factory,
    monkeypatch,
) -> None:
    real = service_module.resolve_rule_authority
    authorities: list[RuleAuthority] = []

    def tracking(*args, **kwargs):
        authorities.append(args[3])
        return real(*args, **kwargs)

    monkeypatch.setattr(service_module, "resolve_rule_authority", tracking)
    service = ClassificationService(
        (
            rule(
                "user",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
            ),
        ),
        (
            rule(
                "system",
                "IMAGE",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
                authority=RuleAuthority.KNOWN_SYSTEM_RULE,
            ),
        ),
        ExplodingProvider(),
    )

    service.classify(request(evidence_factory()))

    assert authorities == [RuleAuthority.CONFIRMED_USER_RULE]


def test_s2_a39_system_decision_skips_provider(evidence_factory) -> None:
    provider = ExplodingProvider()
    result = ClassificationService(
        (),
        (
            rule(
                "system",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
                authority=RuleAuthority.KNOWN_SYSTEM_RULE,
            ),
        ),
        provider,
    ).classify(request(evidence_factory()))

    assert result.source is ClassificationSource.KNOWN_SYSTEM_RULE
    assert provider.calls == 0


def test_s2_a40_confirmed_conflict_terminates_immediately(
    evidence_factory,
    monkeypatch,
) -> None:
    real = service_module.resolve_rule_authority
    authorities: list[RuleAuthority] = []

    def tracking(*args, **kwargs):
        authorities.append(args[3])
        return real(*args, **kwargs)

    monkeypatch.setattr(service_module, "resolve_rule_authority", tracking)
    service = ClassificationService(
        (
            rule(
                "a",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
            ),
            rule(
                "b",
                "IMAGE",
                RuleConditionType.MIME_HINT_EQUALS,
                "application/pdf",
            ),
        ),
        (),
        ExplodingProvider(),
    )

    result = service.classify(request(evidence_factory()))

    assert result.reason is UnresolvedReason.RULE_CONFLICT
    assert authorities == [RuleAuthority.CONFIRMED_USER_RULE]


def test_s2_a41_system_conflict_terminates_immediately(
    evidence_factory,
) -> None:
    provider = ExplodingProvider()
    system_rules = (
        rule(
            "a",
            "DOCUMENT",
            RuleConditionType.EXTENSION_EQUALS,
            ".pdf",
            authority=RuleAuthority.KNOWN_SYSTEM_RULE,
        ),
        rule(
            "b",
            "IMAGE",
            RuleConditionType.MIME_HINT_EQUALS,
            "application/pdf",
            authority=RuleAuthority.KNOWN_SYSTEM_RULE,
        ),
    )

    result = ClassificationService((), system_rules, provider).classify(
        request(evidence_factory())
    )

    assert_unresolved(result, UnresolvedReason.RULE_CONFLICT)
    assert provider.calls == 0


def test_s2_a42_invalid_rule_configuration_terminates_before_provider(
    evidence_factory,
) -> None:
    provider = ExplodingProvider()
    invalid = ClassificationRule(
        rule_id="",
        authority=RuleAuthority.CONFIRMED_USER_RULE,
        priority=1,
        label="DOCUMENT",
        conditions=(
            condition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
        ),
    )

    result = ClassificationService((invalid,), (), provider).classify(
        request(evidence_factory())
    )

    assert_unresolved(result, UnresolvedReason.INVALID_RULE_CONFIGURATION)
    assert provider.calls == 0


def test_s2_a43_provider_is_reached_only_after_both_authorities_have_no_decision(
    evidence_factory,
    monkeypatch,
) -> None:
    real = service_module.resolve_rule_authority
    authorities: list[RuleAuthority] = []

    def tracking(*args, **kwargs):
        authorities.append(args[3])
        return real(*args, **kwargs)

    monkeypatch.setattr(service_module, "resolve_rule_authority", tracking)
    provider = RecordingProvider(
        ProviderClassification("DOCUMENT", False, None)
    )
    service = ClassificationService(
        (
            rule(
                "user",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".zip",
            ),
        ),
        (
            rule(
                "system",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".docx",
                authority=RuleAuthority.KNOWN_SYSTEM_RULE,
            ),
        ),
        provider,
    )

    result = service.classify(request(evidence_factory(extension=".pdf")))

    assert result.source is ClassificationSource.MODEL_INFERENCE
    assert authorities == [
        RuleAuthority.CONFIRMED_USER_RULE,
        RuleAuthority.KNOWN_SYSTEM_RULE,
    ]
    assert provider.calls == 1


def test_s2_a44_every_classified_result_label_is_exactly_allowed(
    evidence_factory,
) -> None:
    deterministic = ClassificationService(
        (
            rule(
                "pdf",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
            ),
        ),
        (),
        ExplodingProvider(),
    ).classify(request(evidence_factory(), ("DOCUMENT",)))
    model = ClassificationService(
        (),
        (),
        RecordingProvider(ProviderClassification("DOCUMENT", False, None)),
    ).classify(request(evidence_factory(), ("DOCUMENT",)))

    assert deterministic.label in ("DOCUMENT",)
    assert model.label in ("DOCUMENT",)


def test_s2_a45_deterministic_success_has_rule_id_and_no_provider_metadata(
    evidence_factory,
) -> None:
    result = ClassificationService(
        (
            rule(
                "pdf",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
            ),
        ),
        (),
        ExplodingProvider(),
    ).classify(request(evidence_factory()))

    assert result.rule_id == "pdf"
    assert result.provider_name is None
    assert result.provider_model is None
    assert result.provider_confidence is None


def test_s2_a46_model_success_has_adapter_identity_and_no_rule_id(
    evidence_factory,
) -> None:
    result = ClassificationService(
        (),
        (),
        RecordingProvider(ProviderClassification("DOCUMENT", False, 0.2)),
    ).classify(request(evidence_factory()))

    assert result.source is ClassificationSource.MODEL_INFERENCE
    assert result.rule_id is None
    assert result.provider_name == "test-provider"
    assert result.provider_model == "test-model"
    assert result.provider_confidence == 0.2


def test_s2_a47_every_unresolved_result_has_exact_unresolved_shape(
    evidence_factory,
) -> None:
    provider_result = ClassificationService(
        (),
        (),
        RecordingProvider(ProviderClassification(None, True, None)),
    ).classify(request(evidence_factory()))
    conflict = ClassificationService(
        (
            rule(
                "a",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
            ),
            rule(
                "b",
                "IMAGE",
                RuleConditionType.MIME_HINT_EQUALS,
                "application/pdf",
            ),
        ),
        (),
        ExplodingProvider(),
    ).classify(request(evidence_factory()))

    for result in (provider_result, conflict):
        assert result.status is ClassificationStatus.UNRESOLVED
        assert result.label is None
        assert result.source is None
        assert result.rule_id is None
        assert isinstance(result.reason, UnresolvedReason)


def test_s2_a48_provider_unresolved_has_identity_but_deterministic_unresolved_does_not(
    evidence_factory,
) -> None:
    provider_result = ClassificationService(
        (),
        (),
        RecordingProvider(ProviderClassification(None, True, None)),
    ).classify(request(evidence_factory()))
    conflict = ClassificationService(
        (
            rule(
                "a",
                "DOCUMENT",
                RuleConditionType.EXTENSION_EQUALS,
                ".pdf",
            ),
            rule(
                "b",
                "IMAGE",
                RuleConditionType.MIME_HINT_EQUALS,
                "application/pdf",
            ),
        ),
        (),
        ExplodingProvider(),
    ).classify(request(evidence_factory()))

    assert provider_result.provider_name == "test-provider"
    assert provider_result.provider_model == "test-model"
    assert provider_result.provider_confidence is None
    assert conflict.provider_name is None
    assert conflict.provider_model is None
    assert conflict.provider_confidence is None


def test_s2_a49_empty_allowed_labels_is_rejected_before_work(
    evidence_factory,
) -> None:
    provider = ExplodingProvider()

    with pytest.raises(ValueError, match="allowed_labels"):
        ClassificationService((), (), provider).classify(
            request(evidence_factory(), ())
        )

    assert provider.calls == 0


@pytest.mark.parametrize(
    "labels",
    [
        ("DOCUMENT", "DOCUMENT"),
        ("",),
        (1,),
        ["DOCUMENT"],
        (" Document ", "Document"),
    ],
)
def test_s2_a50_duplicate_empty_nonstring_or_nontuple_labels_are_rejected_without_normalization(
    evidence_factory,
    labels,
) -> None:
    provider = ExplodingProvider()

    if labels == (" Document ", "Document"):
        result = ClassificationService(
            (),
            (),
            RecordingProvider(
                ProviderClassification(" Document ", False, None)
            ),
        ).classify(request(evidence_factory(), labels))
        assert result.label == " Document "
        return

    with pytest.raises(ValueError, match="allowed_labels"):
        ClassificationService((), (), provider).classify(
            request(evidence_factory(), labels)
        )

    assert provider.calls == 0


def test_s2_a51_unsupported_schema_is_rejected_before_work(
    evidence_factory,
) -> None:
    provider = ExplodingProvider()

    with pytest.raises(ValueError, match="schema_version"):
        ClassificationService((), (), provider).classify(
            request(
                evidence_factory(),
                ("DOCUMENT",),
                "tidy.classification.v2",
            )
        )

    assert provider.calls == 0


def test_s2_a52_identical_inputs_and_provider_outcomes_produce_identical_results(
    evidence_factory,
) -> None:
    request_value = request(evidence_factory())
    first = ClassificationService(
        (),
        (),
        RecordingProvider(ProviderClassification("DOCUMENT", False, 0.42)),
    ).classify(request_value)
    second = ClassificationService(
        (),
        (),
        RecordingProvider(ProviderClassification("DOCUMENT", False, 0.42)),
    ).classify(request_value)

    assert first == second


def test_service_rejects_invalid_provider_identity() -> None:
    provider = RecordingProvider(
        ProviderClassification("DOCUMENT", False, None)
    )
    provider.provider_name = ""

    with pytest.raises(ValueError, match="provider_name"):
        ClassificationService((), (), provider)


def test_request_requires_file_evidence(evidence_factory) -> None:
    bad_request = ClassificationRequest(
        object(),
        ("DOCUMENT",),
        CLASSIFICATION_SCHEMA_VERSION,
    )

    with pytest.raises(ValueError, match="evidence"):
        ClassificationService((), (), ExplodingProvider()).classify(
            bad_request
        )
