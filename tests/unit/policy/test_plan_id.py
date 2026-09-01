import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path

from tidy.domain.classification import ClassificationSource
from tidy.domain.planning import PlannedDestination, PlannedSource, PlanPrecondition
from tidy.policy.plan_id import canonical_authorization_payload, derive_plan_id


def _fields() -> dict[str, object]:
    return {
        "schema_version": "tidy.planning.v1",
        "source": PlannedSource(
            inbox_id="downloads",
            relative_path=Path("receipts/2026/invoice.pdf"),
            expected_sha256="a" * 64,
            expected_size_bytes=123,
            expected_modified_ns=456,
        ),
        "destination": PlannedDestination(
            root_id="documents",
            relative_directory=("Finance", "Invoices"),
            filename="invoice.pdf",
        ),
        "authorized_directories": (("Finance",), ("Finance", "Invoices")),
        "preconditions": (PlanPrecondition.DESTINATION_MUST_NOT_EXIST,),
        "classification_label": "DOCUMENT",
        "classification_source": ClassificationSource.MODEL_INFERENCE,
        "policy_id": "documents.invoice",
    }


def test_s3_a39_plan_id_is_sha256_of_canonical_payload() -> None:
    fields = _fields()
    payload = canonical_authorization_payload(**fields)
    assert derive_plan_id(**fields) == hashlib.sha256(payload).hexdigest()
    assert len(derive_plan_id(**fields)) == 64


def test_s3_a40_plan_id_has_no_clock_random_or_caller_identifier_input() -> None:
    parameters = inspect.signature(derive_plan_id).parameters
    assert "plan_id" not in parameters
    assert "created_at" not in parameters
    assert "timestamp" not in parameters
    fields = _fields()
    assert derive_plan_id(**fields) == derive_plan_id(**fields)


def test_s3_a41_changing_any_authority_field_changes_payload_and_id() -> None:
    base = _fields()
    source = base["source"]
    destination = base["destination"]
    assert isinstance(source, PlannedSource)
    assert isinstance(destination, PlannedDestination)
    variants = (
        {**base, "schema_version": "tidy.planning.v2"},
        {**base, "source": replace(source, inbox_id="other")},
        {**base, "source": replace(source, relative_path=Path("other.pdf"))},
        {**base, "source": replace(source, expected_sha256="b" * 64)},
        {**base, "source": replace(source, expected_size_bytes=124)},
        {**base, "source": replace(source, expected_modified_ns=457)},
        {**base, "destination": replace(destination, root_id="archive")},
        {**base, "destination": replace(destination, relative_directory=("Finance",))},
        {**base, "destination": replace(destination, filename="other.pdf")},
        {**base, "authorized_directories": (("Finance",),)},
        {**base, "preconditions": ()},
        {**base, "classification_label": "IMAGE"},
        {**base, "classification_source": ClassificationSource.KNOWN_SYSTEM_RULE},
        {**base, "policy_id": "documents.changed"},
    )
    base_payload = canonical_authorization_payload(**base)
    base_id = derive_plan_id(**base)
    for variant in variants:
        assert canonical_authorization_payload(**variant) != base_payload
        assert derive_plan_id(**variant) != base_id


def test_s3_a42_canonical_directory_encoding_is_segment_based_and_platform_neutral() -> None:
    fields = _fields()
    payload = canonical_authorization_payload(**fields)
    decoded = json.loads(payload.decode("utf-8"))
    assert decoded[1][2] == ["receipts", "2026", "invoice.pdf"]
    assert decoded[2][2] == ["Finance", "Invoices"]
    assert decoded[3] == [["Finance"], ["Finance", "Invoices"]]
    assert "Finance/Invoices" not in payload.decode("utf-8")
