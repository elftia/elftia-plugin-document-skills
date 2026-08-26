# Semantic template inspection and fill

`pptx.template.inspect` reads an inert `.pptx` or `.potx` package without
dereferencing external targets. Structural inspection works without a
descriptor. Writable semantic slots exist only when the three A-Contract
artifacts validate against the pinned contract owner package and their exact
SHA-256 references match.

## Inspect a semantic template

```json
{
  "schema_version": "1.0",
  "operation": "pptx.template.inspect",
  "input": "template.sanitized.pptx",
  "arguments": {
    "catalog_ref": {
      "assetId": "neutral-consulting",
      "catalogId": "synthetic",
      "sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "version": "1.0.0"
    },
    "contact_sheet": false,
    "descriptor": {
      "contract_root": "presentation-contracts",
      "deck_ir": {
        "path": "neutral.deck-ir.json",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      },
      "semantic_slots": {
        "path": "neutral.semantic-slots.json",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      },
      "template_contract": {
        "path": "neutral.template-contract.json",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      }
    },
    "expected_input_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "mode": "strict"
  }
}
```

Set `descriptor` and `catalog_ref` to `null` for structural-only inspection.
In `strict` mode, a supplied descriptor must validate completely. In
`tolerant` mode, descriptor drift is returned as diagnostics and every page's
`semantic_slots` array stays empty; tolerant output is not a selector source.

To request a contact sheet, set `contact_sheet` to `true` and add a distinct
`.png` `output` path. A callable LibreOffice visual provider must render the
slides. Provider absence reports `unavailable` and creates no placeholder PNG.
Dangerous input is inventoried but is never opened by the visual provider.

The result projects stable slide/object addresses, page role, layout/master/
theme references, slot kind/cardinality/capacity/type scale, notes and hidden
state, dangerous/external/embedded inventory, and catalog verification state.
Without Governance evidence, signature verification remains `not_provided` or
`not_available_without_governance`; inspection never upgrades that state.

## Fill selected pages

Use only ids and hashes returned by a successful strict semantic inspection:

```json
{
  "schema_version": "1.0",
  "operation": "pptx.create.from-template",
  "input": "template.sanitized.pptx",
  "output": "deck.pptx",
  "arguments": {
    "catalog_ref": {
      "assetId": "neutral-consulting",
      "catalogId": "synthetic",
      "sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "version": "1.0.0"
    },
    "delivery_profile": "development",
    "descriptor": {
      "contract_root": "presentation-contracts",
      "deck_ir": {
        "path": "neutral.deck-ir.json",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      },
      "semantic_slots": {
        "path": "neutral.semantic-slots.json",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      },
      "template_contract": {
        "path": "neutral.template-contract.json",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      }
    },
    "expected_input_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "pages": [
      {
        "source_slide_id": "slide_0123456789abcdef0123456789abcdef",
        "output_slide_id": "slide_fedcba9876543210fedcba9876543210",
        "bindings": [
          {
            "slot_id": "problem.title",
            "expected_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "value": {
              "type": "text",
              "text": "Why action is required now"
            }
          },
          {
            "slot_id": "problem.image",
            "expected_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "value": {
              "type": "image-ref",
              "path": "replacement.png",
              "expected_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
              "content_type": "image/png",
              "fit": "contain",
              "alt_text": "Evidence supporting the problem statement"
            }
          }
        ]
      }
    ],
    "unbound_required_slot": "reject",
    "unselected_content": "physical_purge"
  }
}
```

The `pages` array defines output order and may select or repeat a source slide;
every `output_slide_id` must be unique. Public selectors never accept a shape,
run, relationship, or ZIP part ordinal. For an A-Contract `repeated` slot,
`min`/`max` counts bindings across repeated output-page instances of its source
slide; each individual page still binds that slot at most once.

Binding value `type` must equal the slot's A-Contract data type. Supported
types are `text`, `rich-text`, `number`, `date`, `image-ref`, `table-data`, and
`chart-data`. Images are bounded local PNG/JPEG/static GIF files. An optional
`image-ref.expected_sha256` is a lowercase unprefixed digest checked against
the exact payload embedded in the candidate, closing verify-to-read races for
cross-producer bundles. Table data
must match the template table dimensions. Chart data updates the existing
native chart rather than replacing it with a picture.
Relative input/output, descriptor, contract, and binding-image paths resolve
from the public command's invocation directory, not the isolated worker's
private directory.

Creation always rejects unbound required slots and always physically purges
unselected content. Promotion is blocked by stale source/slot/catalog hashes,
capacity or placeholder lint, speaker-note leaks, unsupported bindings,
validation failures, or purge failures. The bundled runtime has no
A-Governance signature verifier, so every `commercial` delivery profile is
currently fail-closed with `DS_LICENSE_BLOCKED`, including a descriptor that
claims an `allowed` decision. After a Governance verifier is integrated, the
profile must still require a verified, explicit A-Contract `allowed` commercial
decision; absent, unknown, noncommercial, or review-required status remains
blocked.
Repeated dependency graphs, package part/byte counts, and replacement images
are checked against bounded aggregate budgets before candidate emission.

Successful diagnostics include source-to-output slide/object mapping, binding
receipt, changed/preserved objects, purge manifest with original hashes,
content-lint evidence, and delivery receipt. Core, schema, visual,
LibreOffice, and PowerPoint states remain separate; an unrun optional consumer
is never reported as passed.
