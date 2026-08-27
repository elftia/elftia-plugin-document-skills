# Editable native Office Math

Editable equations extend the existing `pptx.create` and `pptx.edit`
operations. They do not register a raw-OMML operation and do not accept XML.
The output is native Office Math inside the slide shape tree, with no OLE
object and no whole-equation image fallback.

## Create block

Put a discriminated equation block in `deck.slides[].shapes[]`:

```json
{
  "type": "equation",
  "id": "eq-energy",
  "bbox": {"x": 1.0, "y": 2.0, "w": 6.0, "h": 0.8},
  "source": {"kind": "latex", "value": "E=mc^2"},
  "fallback": "reject",
  "z_order": 100
}
```

`bbox` uses inches and must have a non-negative origin, positive extent, and
fit inside the effective slide size. `id` must start with an ASCII letter and
contain at most 80 letters, digits, `_`, `.`, `:`, or `-`. `z_order` is an
optional integer from 0 through 10000. Template-base creation and `slide_add`
recheck the frame against the target deck's actual slide size.

## Accepted LaTeX subset

The closed parser accepts ordinary bounded text/operators plus:

- `\frac{numerator}{denominator}`;
- subscript, superscript, and combined scripts such as `x_i^2`;
- `\sum` with optional lower/upper limits;
- `\sqrt{x}` and `\sqrt[3]{x}`;
- rectangular `\begin{matrix} ... \end{matrix}` with `&` cells and `\\` rows;
- named upper/lower Greek symbols documented by the implementation;
- `\cdot`, `\times`, `\pm`, `\le`, `\ge`, `\neq`, and `\infty`.

Unknown commands are unsupported. Macro definitions, file/input commands,
raw XML-like text, and raw OMML/XML source kinds fail closed.

## Typed AST

Use `source.kind: "ast"` when a structured producer already has math nodes.
Every node rejects unknown fields. Supported node forms are:

| `type` | Required fields |
|---|---|
| `text` | non-empty `value` |
| `symbol` | supported Greek `name` |
| `row` | non-empty `items` of supported nodes |
| `fraction` | `numerator`, `denominator` |
| `superscript` | `base`, `exponent` |
| `subscript` | `base`, `subscript` |
| `subsuperscript` | `base`, `subscript`, `exponent` |
| `radical` | `radicand`, nullable `degree` |
| `nary` | `operator: "sum"`, nullable `lower` and `upper` |
| `matrix` | non-empty rectangular `rows` of supported nodes |

Typed `text.value` is canonicalized with NFKC and Unicode-minus normalization,
then restricted to one non-empty token of Unicode word characters/digits or the
documented operator punctuation. Whitespace, `_`, raw Greek characters, and
control or XML-like text are rejected; use `subscript` nodes and `symbol` nodes
instead. LaTeX text uses the same canonicalization before parsing.

## Resource limits

- LaTeX UTF-8 input or total typed text: 4096 bytes;
- canonical AST: 256 nodes and depth 32;
- matrix: at most 8 rows by 8 columns.

LaTeX is normalized through the same canonical AST budget after parsing, so
matrix cells cannot reset or evade the global node/depth limits.

## Transactional add or update

Use `equation_upsert` inside the ordinary `pptx.edit` edits array. Omit the
selector to add a new equation:

```json
{
  "type": "equation_upsert",
  "slide": 1,
  "equation": {
    "type": "equation",
    "id": "eq-root",
    "bbox": {"x": 1.0, "y": 4.5, "w": 4.0, "h": 0.7},
    "source": {"kind": "latex", "value": "\\sqrt{x}"},
    "fallback": "reject"
  }
}
```

To update, run `pptx.read` and copy its exact equation selector and object
precondition hash:

```json
{
  "type": "equation_upsert",
  "slide": 1,
  "selector": {"id": "7", "name": "eq-energy", "type": "equation"},
  "precondition_sha256": "<hash returned by pptx.read>",
  "equation": {
    "type": "equation",
    "id": "eq-energy",
    "bbox": {"x": 1.0, "y": 2.0, "w": 6.0, "h": 0.8},
    "source": {"kind": "latex", "value": "E=\\frac{mc^2}{2}"},
    "fallback": "reject"
  }
}
```

The update retains the selected shape id and participates in the same
all-or-nothing transaction as every other edit.

## Readback and consumer truth

`pptx.read` returns the canonical AST/LaTeX, bbox, native/editable flags, stable
selector, and object precondition hash. Internal reopen correspondence is
separate from application-consumer evidence. `consumer_compatibility` reports
PowerPoint and LibreOffice as `not_run` by default; only an actual consumer run
may change such evidence to rendered, unsupported, or another observed state.

The compatibility branch is element-level plain text for consumers that do not
select the Office Math choice. It is not a claim that those consumers preserve
equation editability. `fallback: "reject"` remains the only caller policy.
