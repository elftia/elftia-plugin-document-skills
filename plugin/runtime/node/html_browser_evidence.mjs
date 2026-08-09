const MAX_FONT_EVIDENCE_ITEMS = 256;

export async function captureBrowserEvidence(page, raw) {
  const session = await page.context().newCDPSession(page);
  try {
    const captured = await session.send('DOMSnapshot.captureSnapshot', {
      computedStyles: [],
      includePaintOrder: true,
      includeDOMRects: false,
      includeBlendedBackgroundColors: false,
      includeTextColorOpacities: false,
    });
    const result = snapshotEvidence(captured);
    const textItems = raw.slides.flatMap((slide) => slide.items)
      .filter((item) => item.text && result.get(item.capture_id)?.backend_node_id);
    const selected = textItems.slice(0, MAX_FONT_EVIDENCE_ITEMS);
    for (const item of textItems.slice(MAX_FONT_EVIDENCE_ITEMS)) {
      result.get(item.capture_id).font_truncated = true;
    }
    if (selected.length > 0) {
      await session.send('DOM.getDocument', { depth: 0, pierce: false });
      await session.send('CSS.enable');
      const pushed = await session.send('DOM.pushNodesByBackendIdsToFrontend', {
        backendNodeIds: selected.map((item) => result.get(item.capture_id).backend_node_id),
      });
      for (let index = 0; index < selected.length; index += 1) {
        const itemEvidence = result.get(selected.at(index).capture_id);
        const nodeId = pushed.nodeIds?.at(index);
        if (!Number.isInteger(nodeId) || nodeId <= 0) {
          itemEvidence.font_truncated = true;
          continue;
        }
        try {
          const response = await session.send('CSS.getPlatformFontsForNode', { nodeId });
          itemEvidence.platform_fonts = (response.fonts ?? []).slice(0, 8).map((font) => ({
            family: String(font.familyName).slice(0, 128),
            postscript: String(font.postScriptName).slice(0, 128),
            custom: font.isCustomFont === true,
            glyphs: Math.max(0, Number.isInteger(font.glyphCount) ? font.glyphCount : 0),
          }));
        } catch {
          itemEvidence.font_truncated = true;
        }
      }
    }
    return result;
  } finally {
    await session.detach().catch(() => undefined);
  }
}

function snapshotEvidence(captured) {
  const result = new Map();
  for (const document of captured.documents ?? []) {
    const attributes = document.nodes?.attributes ?? [];
    const backendNodeIds = document.nodes?.backendNodeId ?? [];
    const nodeIndices = document.layout?.nodeIndex ?? [];
    const paintOrders = document.layout?.paintOrders ?? [];
    for (let index = 0; index < nodeIndices.length; index += 1) {
      const nodeIndex = nodeIndices.at(index);
      if (!Number.isInteger(nodeIndex) || nodeIndex < 0) continue;
      const pairs = attributes.at(nodeIndex) ?? [];
      for (let attribute = 0; attribute + 1 < pairs.length; attribute += 2) {
        const nameIndex = pairs.at(attribute);
        const captureIdIndex = pairs.at(attribute + 1);
        if (!Number.isInteger(nameIndex) || !Number.isInteger(captureIdIndex)) continue;
        const name = captured.strings?.at(nameIndex);
        if (name !== 'data-elftia-capture-id') continue;
        const captureId = captured.strings?.at(captureIdIndex);
        const paintOrder = paintOrders.at(index);
        if (typeof captureId === 'string' && Number.isInteger(paintOrder)) {
          result.set(captureId, {
            paint_order: paintOrder,
            backend_node_id: backendNodeIds.at(nodeIndex) ?? null,
            platform_fonts: [],
            font_truncated: false,
          });
        }
      }
    }
  }
  return result;
}

export function bindPlatformFonts(captured, browserEvidence) {
  const platformFonts = browserEvidence?.platform_fonts ?? [];
  const requested = captured.requested_families ?? [];
  const actual = platformFonts.at(0)?.family ?? null;
  const substitution = requested.length > 0
    && actual !== null
    && actual.localeCompare(requested.at(0), undefined, { sensitivity: 'base' }) !== 0
    ? { requested: requested.at(0), actual }
    : null;
  return {
    requested_families: requested,
    computed_family: captured.computed_family,
    platform_fonts: platformFonts,
    substitution,
    truncated: browserEvidence?.font_truncated === true,
  };
}
