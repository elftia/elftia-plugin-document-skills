# Consumer Validation Harness

## Purpose

`consumer_validation` is an independent bounded harness for reopening generated DOCX, XLSX, PPTX, and PDF artifacts with supported consumer/tool paths and returning typed evidence. It is assurance infrastructure, not a document-authoring provider.

## Ownership and boundaries

The harness owns process cleanup, timeouts, Office/LibreOffice invocation wrappers, OOXML/PDF evidence normalization, and truthful consumer identity. Format Core remains responsible for the operation transaction and mandatory structural validation.

Consumer validation does not make a provider available, infer support from executable presence, hide a timeout/crash as a skip, or promote an artifact. A consumer result is scoped to the exact executable/version, artifact hash, command, and run.

## Entry points

- [`__main__.py`](__main__.py) and [`cli.py`](cli.py) expose the internal harness CLI.
- [`harness.py`](harness.py) coordinates bounded execution and cleanup.
- [`office.py`](office.py) owns Office/LibreOffice process behavior.
- [`ooxml.py`](ooxml.py), [`docx.py`](docx.py), and [`pdf.py`](pdf.py) normalize evidence by format.

The harness CLI is producer-internal. Agent Skills do not call this module directly; public operations return their own validated result envelopes. Producer invocation and verification belong to the [repository-level script guide](../../scripts/README.md).

## Safety and failure semantics

Inputs are local and hash-bound. Subprocesses have explicit timeouts, bounded output, private state, and deterministic cleanup. A crash, hang, wrong consumer identity, output mismatch, or reopen failure is recorded as a failure/unavailable boundary; it is not converted to `pass` because the source package was structurally valid.

Generated evidence must not contain secrets, raw environment dumps, unbounded logs, or unsanitized filesystem details.

## Verification

Harness, timeout, cross-format, and real-consumer-gated coverage is owned by the [plugin test suite](../tests/README.md) and the [producer verification guide](../../scripts/README.md). Real Office tests may skip when the exact consumer is absent. A locally observed application crash remains a recorded failure boundary, not a passing or unavailable-by-assumption result.

## Related documentation

- [Runtime overview](../README.md)
- [Shared Core](../src/document_skills_core/README.md)
- [Providers](../src/document_skills_core/providers/README.md)
- [Schemas](../schemas/README.md)
- [Tests](../tests/README.md)
- [Distribution E2E](../../e2e/README.md)
