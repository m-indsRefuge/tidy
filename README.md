# Tidy

Tidy is a local AI-assisted file organiser that learns how its user
manages a digital environment while keeping filesystem authority
deterministic, inspectable, and reversible.

> Tidy uses AI to discover rules, not replace rules.

A model can help determine what a file appears to be. It does not decide
what filesystem operations are permitted.

Tidy learns from user decisions and corrections. Repeated confirmed
behaviour can become explicit rules, allowing the system to become more
deterministic — and less dependent on probabilistic AI — over time.

## Architecture

### TIDY-S1 — Intake & Evidence

Observe configured inboxes, verify file stability, fingerprint files,
and construct safe evidence.

### TIDY-S2 — Classification

Resolve known rules first and expose a model-independent classification
interface for cases requiring inference.

### TIDY-S3 — Policy & Planning

Apply destination policy, allow-lists, uncertainty handling, collision
rules, and produce mutation plans without executing them.

### TIDY-S4 — Execution & Recovery

Perform authorized filesystem mutations, maintain an evidence ledger,
and provide verified recovery and undo operations.

### TIDY-S5 — Learning & UX

Record decisions and corrections, detect recurring behaviour, propose
rule promotion, and provide review and history interfaces.

## Status

Architecture bootstrap.

Production behaviour will be added subsystem by subsystem after its
contracts and acceptance criteria are defined.
