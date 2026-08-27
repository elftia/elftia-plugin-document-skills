# Public Protocol Schemas

## Purpose

This directory contains the JSON Schema envelopes shared by every Document Skills command. They define the versioned public request and report shapes; format-specific arguments and diagnostics remain in typed contracts and Skill references.

## Ownership and boundaries

Schemas validate protocol structure, closed keys, statuses, errors, gates, artifacts, and bounded evidence. They do not advertise runtime provider availability, evaluate document semantics, or replace format-specific validation. The supervisor validates the final result before the only stdout write.

## Entry points

| Schema | Owns |
| --- | --- |
| [`operation-request.schema.json`](operation-request.schema.json) | Versioned operation/input/output/options/arguments envelope |
| [`operation-result.schema.json`](operation-result.schema.json) | Final status, artifacts, diagnostics, gates, warnings/degradations, and errors |
| [`doctor-report.schema.json`](doctor-report.schema.json) | Runtime/provider health evidence |
| [`capability-report.schema.json`](capability-report.schema.json) | Registered operation/provider availability report |
| [`validation-report.schema.json`](validation-report.schema.json) | Standalone artifact validation report |

All public envelopes currently use `schema_version: "1.0"`. Use the [Skill catalog](../skills/README.md) and format references for operation-specific request examples.

## Safety and failure semantics

Unknown keys and invalid types fail before provider execution where the owning contract is closed. Schema success is necessary but not sufficient for a safe document operation: path policy, archive preflight, selectors, provider acceptance, package validation, consumer evidence, and promotion gates still apply.

An optional validation gate that did not run must remain `unavailable` or `not_run`; schema shape cannot upgrade it to `pass`.

## Verification

Schema fixtures and public protocol tests are owned by the [plugin test suite](../tests/README.md) and run through the aggregate checks documented in the [producer verification guide](../../scripts/README.md).

## Related documentation

- [Runtime overview](../README.md)
- [Public Skills](../skills/README.md)
- [Shared Core](../src/document_skills_core/README.md)
- [Consumer validation](../consumer_validation/README.md)
- [Tests](../tests/README.md)
