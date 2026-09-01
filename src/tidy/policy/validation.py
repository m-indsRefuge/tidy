from tidy.domain.planning import DestinationPolicy, PlanningConfiguration


def validate_relative_directory(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    for segment in value:
        if type(segment) is not str or segment == "":
            return False
        if segment in {".", ".."}:
            return False
        if "/" in segment or "\\" in segment or "\x00" in segment:
            return False
    return True


def validate_planning_configuration(
    configuration: PlanningConfiguration,
) -> bool:
    roots = configuration.approved_destination_root_ids
    policies = configuration.destination_policies

    if not isinstance(roots, tuple):
        return False
    if not all(type(root_id) is str and root_id != "" for root_id in roots):
        return False
    if len(set(roots)) != len(roots):
        return False

    if not isinstance(policies, tuple):
        return False
    if not all(isinstance(policy, DestinationPolicy) for policy in policies):
        return False

    policy_ids = [policy.policy_id for policy in policies]
    if not all(type(policy_id) is str and policy_id != "" for policy_id in policy_ids):
        return False
    if len(set(policy_ids)) != len(policy_ids):
        return False

    labels = [policy.label for policy in policies]
    if not all(type(label) is str and label != "" for label in labels):
        return False
    if len(set(labels)) != len(labels):
        return False

    approved_roots = set(roots)
    for policy in policies:
        if type(policy.destination_root_id) is not str:
            return False
        if policy.destination_root_id not in approved_roots:
            return False
        if not validate_relative_directory(policy.relative_directory):
            return False

    return True
