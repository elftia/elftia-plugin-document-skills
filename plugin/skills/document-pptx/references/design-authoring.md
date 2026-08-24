# Master, layout, and theme authoring

Use these closed `pptx.edit` primitives only when the presentation design
graph itself must change. Read `pptx.inspect.structure` first and select exact
`ppt/slideMasters/slideMasterN.xml` or
`ppt/slideLayouts/slideLayoutN.xml` part names from
`diagnostics.operation_result.template_lint`.

| Primitive | Contract |
|---|---|
| `master_add` | `master.name`, a typed `master.theme`, and one authored `master.layout` |
| `master_copy` | Exact `master` part; deep-copies its layouts, theme, and contained dependencies |
| `master_delete` | Exact unused `master` part; at least one registered master must remain |
| `layout_add` | Exact target `master` plus a typed `layout` |
| `layout_copy` | Exact source `layout` and target `master`; preserves layout XML and rewires inheritance |
| `layout_delete` | Exact unused `layout` part; its master must retain another layout |
| `theme_update` | Exact `master` plus the typed theme contract; shared themes use clone-on-write |

All primitives participate in the ordinary all-or-nothing edit transaction.
They maintain presentation/master/layout relationship IDs, content types, and
inverse layout-to-master inheritance. A used layout/master cannot be deleted.

## Authored layout contract

A layout accepts:

- `name` and closed PresentationML `type`: `blank`, `cust`, `obj`, `title`, or
  `twoObj`;
- optional six-digit `background`; omission inherits the master background;
- `show_master_shapes`;
- up to 64 placeholders with a unique `type`/`idx`, exact `name`, and bounded
  EMU `frame` (`x`, `y`, `cx`, `cy`);
- `footer`, `date`, and `slide_number` slots with `enabled`, optional `text`,
  and optional bounded `frame`.

Supported content placeholder types are `title`, `ctrTitle`, `subTitle`,
`body`, `obj`, `pic`, `tbl`, `chart`, `dgm`, `media`, and `clipArt`. Footer,
date, and slide-number placeholders are created only through their dedicated
slots. Every frame must fit the current deck slide size; content is never
silently scaled.

```json
{
  "type": "master_add",
  "master": {
    "name": "Brand Master",
    "theme": {
      "name": "Brand Theme",
      "palette": {"accent1": "006D77"},
      "fonts": {"major": "Aptos Display", "minor": "Aptos"},
      "effects": {
        "shadow": {
          "enabled": true,
          "blur": 60000,
          "distance": 40000,
          "direction": 315,
          "color": "112233",
          "opacity": 0.35
        }
      }
    },
    "layout": {
      "name": "Brand Content",
      "type": "obj",
      "background": "F7FAFC",
      "show_master_shapes": true,
      "placeholders": [
        {
          "type": "title",
          "idx": 0,
          "name": "Brand title",
          "frame": {"x": 457200, "y": 365760, "cx": 8229600, "cy": 914400}
        }
      ],
      "footer": {"enabled": true, "text": "Confidential"},
      "date": {"enabled": true},
      "slide_number": {"enabled": true}
    }
  }
}
```

## Template lint

`pptx.inspect.structure` returns a read-only `template_lint` report. It lists
registered masters, layouts, theme/layout inheritance issues, per-layout
background/footer/placeholder metadata, and slide-placeholder direct-format
contamination. A contamination finding names the slide, shape, and explicit
fill/line/effect/text properties that override inheritance. Inspection never
repairs or mutates the template.
