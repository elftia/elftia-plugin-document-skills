# Docxtemplater 3.69.3 adoption gate

Date: 2026-07-27  
Decision: **ADOPT**, subject to the exact graph and containment conditions below.

This gate admits published package APIs only. It does not admit a third-party wrapper,
claude-office-skills code, an MCP handler, prompt, schema, template, fixture, transport, or
provider command. The implementation that calls the packages is original Elftia code.

## Exact production graph

```text
docxtemplater@3.69.3
└── @xmldom/xmldom@0.9.10

pizzip@3.2.0
└── pako@2.2.0
```

| Package | Integrity from the accepted lock | License selection |
| --- | --- | --- |
| `docxtemplater` 3.69.3 | `sha512-z6IIXImBvOFudR1VHZIjIoewPd/xft/OVF1JT9eKgJLGWQaFZ8gPrjPuAnho0bbQEfKd5Ge7RPq+owqKLmC3PA==` | MIT |
| `@xmldom/xmldom` 0.9.10 | `sha512-A9gOqLdi6cV4ibazAjcQufGj0B1y/vDqYrcuP6d/6x8P27gRS8643Dj9o1dEKtB6O7fwxb2FgBmJS2mX7gpvdw==` | MIT |
| `pizzip` 3.2.0 | `sha512-X4NPNICxCfIK8VYhF6wbksn81vTiziyLbvKuORVAmolvnUzl1A1xmz9DAWKxPRq9lZg84pJOOAMq3OE61bD8IQ==` | MIT |
| `pako` 2.2.0 | `sha512-zJq6RP/5q+TO2OpFV3FHzlPnFjmkb7Nc99a5SNjJE+uu/PkpChs+NIZSSzbBoD+6kjiISXjfYdwj1ZRQ81dz/w==` | MIT AND Zlib |

The graph has no install lifecycle scripts. The project directly imports only
`docxtemplater` and `pizzip`; the other two packages remain transitive lock/SBOM records.

## Gate evidence

The isolated candidate review used Node 24.14.0 and npm 11.9.0. It observed:

- `npm audit --omit=dev --json`: zero info, low, moderate, high, or critical findings.
- `npm audit signatures`: four audited packages and four verified registry signatures.
- a non-evaluating scalar split-run probe rendered `Alice & Bob` as escaped XML;
- the complete replacement anchored in the first affected formatting run;
- unrelated custom XML and an unknown binary payload retained identical payload bytes;
- two render runs produced the same SHA-256,
  `90ebfc45f5ff88a465adf7469c1ccfce9ab1b4caf5fc2ecd52bfcb087e2026f4`.

The project acceptance suite additionally covers the checked-in rich, preservation,
revision/comment, and malicious fixtures. The frozen release audit verifies the final lock,
allowlists, licenses, notices, provider source, fixture registry, and CycloneDX graph.

## Mandatory containment

Adoption remains valid only while all of these conditions hold:

1. The public command remains frozen uv/Python; no agent-visible Node or npm command is added.
2. Python owns argument/path validation, the approved ASCII/dot scalar token inventory,
   missing/unused/protected analysis, archive security, source hashing, preservation,
   semantic validation, result schema validation, and atomic promotion.
3. Node runs one project-contained script through the centralized allowlisted
   `ProcessRunner`, with bounded private paths, JSON input/output, time, and output bytes.
4. Expression parsers, loops, conditions, raw XML, caller-supplied parser code, function
   calls, assignments, async values, module/plugin loading, subprocesses, networking, MCP,
   and direct promotion remain forbidden.
5. Python reopens the staged output and rejects unexpected added, removed, or changed parts.
6. The exact versions, integrities, dependency licenses, notices, and SBOM identities above
   remain frozen. Any graph change requires a new adoption gate.

The process boundary is containment, not an OS privilege sandbox. Registry audit/signatures
are point-in-time evidence, not proof that unknown vulnerabilities do not exist.

## Reproduction commands

```text
npm ci --ignore-scripts
npm ls --omit=dev --all
npm audit --omit=dev
npm audit signatures
uv run --project . --frozen python -m pytest tests/test_docx_operations.py tests/test_docx_fixtures.py
uv run --project . --frozen python -m tools.audit --project-root .
```

Primary upstream references are the official docxtemplater installation/API/FAQ pages and the
published repositories for docxtemplater, PizZip, xmldom, and pako.
