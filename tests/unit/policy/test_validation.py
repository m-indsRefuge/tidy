from tidy.domain.planning import DestinationPolicy, PlanningConfiguration
from tidy.policy.validation import validate_planning_configuration


def _policy(
    policy_id: object = "documents.document",
    label: object = "DOCUMENT",
    root_id: object = "documents",
    directory: object = ("Sorted",),
) -> DestinationPolicy:
    return DestinationPolicy(policy_id, label, root_id, directory)


def _config(
    roots: object = ("documents",),
    policies: object = (_policy(),),
) -> PlanningConfiguration:
    return PlanningConfiguration(roots, policies)


def test_s3_a08_approved_root_ids_must_be_nonempty_strings() -> None:
    assert not validate_planning_configuration(_config(roots=("",)))
    assert not validate_planning_configuration(_config(roots=(1,)))


def test_s3_a09_approved_root_ids_must_be_unique() -> None:
    assert not validate_planning_configuration(
        _config(roots=("documents", "documents"))
    )


def test_s3_a10_policy_ids_must_be_nonempty_strings_and_unique() -> None:
    assert not validate_planning_configuration(_config(policies=(_policy(policy_id=""),)))
    assert not validate_planning_configuration(_config(policies=(_policy(policy_id=1),)))
    assert not validate_planning_configuration(
        _config(
            policies=(
                _policy(policy_id="same"),
                _policy(policy_id="same", label="IMAGE"),
            )
        )
    )


def test_s3_a11_policy_labels_must_be_nonempty_exact_strings() -> None:
    assert not validate_planning_configuration(_config(policies=(_policy(label=""),)))
    assert not validate_planning_configuration(_config(policies=(_policy(label=1),)))


def test_s3_a12_duplicate_policy_labels_make_configuration_invalid() -> None:
    assert not validate_planning_configuration(
        _config(
            policies=(
                _policy(policy_id="one", label="DOCUMENT"),
                _policy(policy_id="two", label="DOCUMENT"),
            )
        )
    )


def test_s3_a13_policy_root_id_must_belong_to_approved_set() -> None:
    assert not validate_planning_configuration(
        _config(policies=(_policy(root_id="archive"),))
    )


def test_s3_a14_relative_directory_must_be_tuple_of_literal_segments() -> None:
    assert not validate_planning_configuration(
        _config(policies=(_policy(directory="Sorted/Documents"),))
    )
    assert not validate_planning_configuration(
        _config(policies=(_policy(directory=("Sorted", 1)),))
    )


def test_s3_a15_empty_directory_tuple_is_valid_root_level_destination() -> None:
    assert validate_planning_configuration(
        _config(policies=(_policy(directory=()),))
    )


def test_s3_a16_unsafe_literal_directory_segments_are_invalid() -> None:
    for segment in ("", ".", "..", "a/b", "a\\b", "a\x00b"):
        assert not validate_planning_configuration(
            _config(policies=(_policy(directory=(segment,)),))
        )


def test_s3_a17_any_invalid_policy_invalidates_complete_configuration() -> None:
    configuration = _config(
        roots=("documents",),
        policies=(
            _policy(policy_id="good", label="DOCUMENT"),
            _policy(policy_id="bad", label="IMAGE", root_id="unapproved"),
        ),
    )
    assert not validate_planning_configuration(configuration)
