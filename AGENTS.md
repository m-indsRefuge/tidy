# Tidy Engineering Principles

## Central Principle

Tidy uses AI to discover rules, not replace rules.

Probabilistic inference may propose classification.
Deterministic policy retains filesystem authority.

Confirmed user behaviour may progressively be promoted into explicit,
inspectable rules.

## Authority Boundary

A model may classify evidence.

A model must never:

- invent executable filesystem paths
- directly move files
- delete files
- overwrite files
- execute files
- bypass destination allow-lists

Only deterministic Tidy code may mutate the filesystem.

## Resolution Order

1. Explicit user rule
2. Deterministic known rule
3. Metadata/evidence rule
4. Model classification
5. Human review

Known deterministic knowledge outranks probabilistic inference.

## Safety

Initial mutation capabilities are limited to:

- move
- create directories inside approved roots
- undo Tidy's own verified moves

Every mutation must be journaled.

Existing files must never be silently overwritten.

Uncertainty is an explicit state, not permission to guess.

## Learning

Tidy owns its memory independently of the model provider.

Individual decisions form episodic evidence.

Repeated behaviour may result in a proposed rule.

Confirmed rules become durable semantic knowledge.

Changing the model provider must not erase learned organisational knowledge.

## Development

Use test-driven development.

Build bounded subsystems with explicit contracts and acceptance criteria.

Model-provider code must remain outside the domain layer.

Filesystem mutation requires stronger verification than observation.
