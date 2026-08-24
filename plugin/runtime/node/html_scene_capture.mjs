import fs from 'node:fs/promises';

import { bindPlatformFonts, captureBrowserEvidence } from './html_browser_evidence.mjs';
import {
  assetReason,
  captureFallback,
  finiteBox,
  imageCrop,
  importImageAsset,
  registerAsset,
  storeAsset,
} from './html_scene_assets.mjs';

const LIMITS = Object.freeze({
  slides: 100,
  dom_nodes: 20_000,
  paint_items: 8_000,
  text_bytes: 4 * 1024 * 1024,
  image_bytes: 8 * 1024 * 1024,
  image_pixels: 40_000_000,
  images: 512,
  assets: 512,
  total_asset_bytes: 32 * 1024 * 1024,
  resource_requests: 512,
  scene_bytes: 32 * 1024 * 1024,
  capture_bytes: 32 * 1024 * 1024,
});
export async function captureScene(
  page,
  sourceRoot,
  assetsDir,
  fallbackPolicy,
  blockedResources,
  captureVisuals = false,
  resourceUsage = { bytes: 0, requests: 0 },
) {
  if (
    !Number.isInteger(resourceUsage.bytes)
    || !Number.isInteger(resourceUsage.requests)
    || resourceUsage.bytes < 0
    || resourceUsage.requests < 0
    || resourceUsage.bytes > LIMITS.total_asset_bytes
    || resourceUsage.requests > LIMITS.resource_requests
  ) {
    throw new Error('asset_total_limit');
  }
  const raw = await captureDom(page);
  if (raw.slides.length === 0) throw new Error('slides_missing');
  if (raw.slides.length > LIMITS.slides || raw.dom_nodes > LIMITS.dom_nodes) {
    throw new Error('dom_limit');
  }
  const browserEvidence = await captureBrowserEvidence(page, raw);
  await fs.mkdir(assetsDir, { recursive: true, mode: 0o700 });
  const assets = new Map();
  let totalAssetBytes = 0;
  let totalResourceBytes = resourceUsage.bytes;
  let paintItems = 0;
  let textBytes = 0;
  let imageItems = 0;
  for (const slide of raw.slides) {
    if (slide.width !== 1920 || slide.height !== 1080 || !finiteBox(slide)) {
      throw new Error('slide_geometry');
    }
    if (slide.root_unsupported.length > 0) throw new Error('slide_root_unsupported');
    for (const item of slide.items) {
      const evidence = browserEvidence.get(item.capture_id);
      const paintOrder = evidence?.paint_order;
      if (!Number.isInteger(paintOrder) || paintOrder < 0) throw new Error('paint_order_missing');
      item.paint_order = paintOrder;
      item.font_evidence = bindPlatformFonts(item.font_evidence, evidence);
      paintItems += 1;
      textBytes += Buffer.byteLength(item.text ?? '', 'utf8');
      if (paintItems > LIMITS.paint_items || textBytes > LIMITS.text_bytes || !finiteBox(item)) {
        throw new Error('scene_limit');
      }
      let nativeImage = null;
      let nativeCrop = null;
      if (item.kind === 'image') {
        imageItems += 1;
        if (imageItems > LIMITS.images) throw new Error('image_count_limit');
        try {
          const asset = await importImageAsset(sourceRoot, assetsDir, item, LIMITS);
          nativeImage = asset;
          nativeCrop = imageCrop(item, asset);
        } catch (error) {
          item.unsupported.push(assetReason(error));
        }
      }
      const needsFallback = item.force_raster || item.unsupported.length > 0;
      if (needsFallback) {
        const coverage = (item.width * item.height) / (1920 * 1080);
        if (fallbackPolicy === 'fail') {
          item.capture_outcome = 'rejected';
          item.reason = item.force_raster ? 'forced_raster_disallowed' : item.unsupported.at(0);
        } else if (coverage >= 0.8 || item.editable_descendants > 30) {
          item.capture_outcome = 'rejected';
          item.reason = 'semantic_flattening_guard';
        } else {
          const asset = await captureFallback(page, assetsDir, item, LIMITS);
          const registeredBytes = registerAsset(assets, asset);
          totalAssetBytes += registeredBytes;
          totalResourceBytes += registeredBytes;
          item.asset_id = asset.id;
          item.image_crop = { left: 0, top: 0, right: 0, bottom: 0 };
          item.capture_outcome = 'rasterized';
          item.reason = item.force_raster ? 'forced_element_raster' : item.unsupported.at(0);
          // The screenshot already contains these visual effects. Applying
          // them again to the emitted picture would double them.
          item.opacity = 1;
          item.border_width = 0;
          item.radius = 0;
        }
      } else if (nativeImage !== null) {
        const registeredBytes = registerAsset(assets, nativeImage);
        totalAssetBytes += registeredBytes;
        totalResourceBytes += registeredBytes;
        item.asset_id = nativeImage.id;
        item.image_crop = nativeCrop;
      }
      if (totalResourceBytes > LIMITS.total_asset_bytes) throw new Error('asset_total_limit');
      if (assets.size > LIMITS.assets) throw new Error('asset_count_limit');
      item.image_src = null;
      delete item.capture_selector;
      delete item.capture_id;
    }
    slide.items.sort((left, right) => left.paint_order - right.paint_order || left.dom_index - right.dom_index);
    slide.items.forEach((item, index) => {
      const basePaintOrder = index * 4;
      item.paint_order = basePaintOrder + 1;
      for (const pseudo of item.pseudo) {
        pseudo.paint_order = basePaintOrder + pseudo.paint_slot;
      }
    });
  }
  const visualSources = [];
  if (captureVisuals) {
    for (let index = 0; index < raw.slides.length; index += 1) {
      const bytes = await page.locator('.slide').nth(index).screenshot({
        animations: 'disabled',
        type: 'png',
      });
      if (bytes.length <= 0 || bytes.length > LIMITS.image_bytes) {
        throw new Error('visual_source_size');
      }
      const asset = await storeAsset(
        assetsDir,
        bytes,
        'image/png',
        1920,
        1080,
        'visual-source',
      );
      const registeredBytes = registerAsset(assets, asset);
      totalAssetBytes += registeredBytes;
      totalResourceBytes += registeredBytes;
      visualSources.push({ slide: index + 1, asset_id: asset.id });
      if (totalResourceBytes > LIMITS.total_asset_bytes) throw new Error('asset_total_limit');
      if (assets.size > LIMITS.assets) throw new Error('asset_count_limit');
    }
  }
  const scene = {
    version: 1,
    canvas: { width: 1920, height: 1080 },
    limits: LIMITS,
    observed: {
      slides: raw.slides.length,
      dom_nodes: raw.dom_nodes,
      paint_items: paintItems,
      text_bytes: textBytes,
      asset_bytes: totalAssetBytes,
      total_asset_bytes: totalResourceBytes,
      resource_requests: resourceUsage.requests,
      images: imageItems,
      assets: assets.size,
      capture_bytes: 0,
    },
    blocked_resources: blockedResources,
    visual_sources: visualSources,
    slides: raw.slides,
    assets: [...assets.values()].sort((a, b) => a.id.localeCompare(b.id)),
  };
  bindCaptureBytes(scene);
  return scene;
}

function bindCaptureBytes(scene) {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const total = Buffer.byteLength(JSON.stringify(scene), 'utf8') + 1 + scene.observed.asset_bytes;
    if (total > LIMITS.capture_bytes) throw new Error('capture_bytes_limit');
    if (scene.observed.capture_bytes === total) return;
    scene.observed.capture_bytes = total;
  }
  throw new Error('capture_bytes_binding');
}

async function captureDom(page) {
  return page.evaluate(() => {
    const HINTS = new Set(['data-pptx-id', 'data-pptx-ignore', 'data-pptx-raster', 'data-pptx-role']);
    const ROLES = new Set(['rectangle', 'rounded-rectangle', 'ellipse', 'line', 'text', 'image']);
    const finite = (...values) => values.every(Number.isFinite);
    const colorVisible = (value) => value && value !== 'rgba(0, 0, 0, 0)' && value !== 'transparent';
    const pixelLength = (value) => {
      if (typeof value !== 'string' || !/^-?(?:\d+|\d*\.\d+)px$/.test(value)) return null;
      const parsed = Number.parseFloat(value);
      return Number.isFinite(parsed) ? parsed : null;
    };
    const textInsets = (style) => ({
      left: Math.max(0, pixelLength(style.paddingLeft) ?? 0),
      top: Math.max(0, pixelLength(style.paddingTop) ?? 0),
      right: Math.max(0, pixelLength(style.paddingRight) ?? 0),
      bottom: Math.max(0, pixelLength(style.paddingBottom) ?? 0),
    });
    // Keep this browser-context policy aligned with html_css_policy.mjs,
    // whose pure Node tests pin the supported/fallback classification table.
    const classifyCss = (style, tagName, hasText) => {
      const unsupported = [];
      const approximations = [];
      const tag = String(tagName ?? '').toUpperCase();
      if (tag === 'CANVAS') unsupported.push('html_canvas');
      if (tag === 'VIDEO') unsupported.push('html_video');
      if (tag === 'SVG') unsupported.push('html_inline_svg');
      if (['IFRAME', 'OBJECT', 'EMBED'].includes(tag)) unsupported.push('html_embedded_content');
      if (style.backgroundImage !== 'none') unsupported.push('css_background_image');
      if (style.boxShadow !== 'none') unsupported.push('css_box_shadow');
      if (style.filter !== 'none') unsupported.push('css_filter');
      if (style.clipPath !== 'none') unsupported.push('css_clip_path');
      if (style.maskImage && style.maskImage !== 'none') unsupported.push('css_mask');
      if (style.mixBlendMode !== 'normal') unsupported.push('css_blend_mode');
      if (tag !== 'IMG' && [style.overflowX, style.overflowY].some((value) => !['visible', 'unset'].includes(value))) {
        unsupported.push('css_overflow_clip');
      }
      if (hasText && style.whiteSpace !== 'normal') unsupported.push('css_white_space');
      if (hasText && (
        !['normal', 'unset'].includes(style.wordBreak)
        || !['normal', 'unset'].includes(style.overflowWrap)
      )) unsupported.push('css_word_break');
      if (hasText && !['clip', 'unset'].includes(style.textOverflow)) unsupported.push('css_text_overflow');
      if (hasText && style.letterSpacing !== 'normal' && pixelLength(style.letterSpacing) === null) {
        unsupported.push('css_letter_spacing');
      }
      if (['flex', 'inline-flex'].includes(style.display)) approximations.push('computed_flex_layout');
      if (['grid', 'inline-grid'].includes(style.display)) approximations.push('computed_grid_layout');
      return {
        unsupported: [...new Set(unsupported)],
        approximations: [...new Set(approximations)],
      };
    };
    const textStyle = (style) => ({
      font_family: style.fontFamily,
      font_size: Number.parseFloat(style.fontSize),
      font_weight: style.fontWeight,
      font_style: style.fontStyle,
      text_decoration: style.textDecorationLine,
      color: style.color,
      text_align: style.textAlign,
      line_height: style.lineHeight,
      letter_spacing: style.letterSpacing,
    });
    const sameStyle = (left, right) => JSON.stringify(left) === JSON.stringify(right);
    const captureTextFlow = (element) => {
      const paragraphs = [{ runs: [] }];
      const append = (rawText, parent) => {
        const style = getComputedStyle(parent);
        let content = rawText;
        if (!['pre', 'pre-wrap', 'break-spaces'].includes(style.whiteSpace)) {
          content = content.replace(/\s+/g, ' ');
        }
        if (!content) return;
        const runs = paragraphs.at(-1).runs;
        const runStyle = textStyle(style);
        const previous = runs.at(-1);
        if (previous && sameStyle(previous.style, runStyle)) previous.text += content;
        else runs.push({ text: content, style: runStyle });
      };
      const nextParagraph = () => {
        if (paragraphs.at(-1).runs.length > 0) paragraphs.push({ runs: [] });
      };
      const visit = (node, root) => {
        if (node.nodeType === Node.TEXT_NODE) {
          append(node.textContent ?? '', node.parentElement ?? root);
          return;
        }
        if (!(node instanceof Element)) return;
        if (node.tagName === 'BR') {
          nextParagraph();
          return;
        }
        if (node !== root) {
          const display = getComputedStyle(node).display;
          if (!display.startsWith('inline') && display !== 'contents') return;
        }
        for (const child of node.childNodes) visit(child, root);
      };
      visit(element, element);
      for (const paragraph of paragraphs) {
        while (paragraph.runs.length > 0 && !paragraph.runs.at(0).text.trim()) paragraph.runs.shift();
        while (paragraph.runs.length > 0 && !paragraph.runs.at(-1).text.trim()) paragraph.runs.pop();
        if (paragraph.runs.length > 0) {
          paragraph.runs.at(0).text = paragraph.runs.at(0).text.replace(/^\s+/, '');
          paragraph.runs.at(-1).text = paragraph.runs.at(-1).text.replace(/\s+$/, '');
        }
      }
      const rootStyle = getComputedStyle(element);
      return paragraphs
        .filter((paragraph) => paragraph.runs.length > 0)
        .map((paragraph) => ({
          runs: paragraph.runs,
          alignment: rootStyle.textAlign,
          line_height: rootStyle.lineHeight,
        }));
    };
    const fontEvidence = (style) => {
      const requested = style.fontFamily.split(',')
        .map((family) => family.trim().replace(/^["']|["']$/g, ''))
        .filter(Boolean)
        .slice(0, 8);
      return {
        requested_families: requested,
        computed_family: style.fontFamily,
      };
    };
    const resolvedGeometry = (element, style, rect, slideRect) => {
      const fallback = {
        x: rect.left - slideRect.left,
        y: rect.top - slideRect.top,
        width: rect.width,
        height: rect.height,
        rotation: 0,
        unsupported: null,
      };
      if (style.transform === 'none') return fallback;
      try {
        const matrix = new DOMMatrixReadOnly(style.transform);
        const scaleX = Math.hypot(matrix.a, matrix.b);
        const scaleY = Math.hypot(matrix.c, matrix.d);
        const orthogonality = matrix.a * matrix.c + matrix.b * matrix.d;
        const determinant = matrix.a * matrix.d - matrix.b * matrix.c;
        if (
          !matrix.is2D
          || !finite(scaleX, scaleY, orthogonality, determinant)
          || scaleX <= 0
          || scaleY <= 0
          || determinant <= 0
          || Math.abs(orthogonality) > 0.0001
        ) return { ...fallback, unsupported: 'css_transform' };
        const width = element.offsetWidth * scaleX;
        const height = element.offsetHeight * scaleY;
        const centerX = rect.left + rect.width / 2 - slideRect.left;
        const centerY = rect.top + rect.height / 2 - slideRect.top;
        return {
          x: centerX - width / 2,
          y: centerY - height / 2,
          width,
          height,
          rotation: Math.atan2(matrix.b, matrix.a) * 180 / Math.PI,
          unsupported: null,
        };
      } catch {
        return { ...fallback, unsupported: 'css_transform' };
      }
    };
    const pseudoRecord = (element, pseudo, sourceId, slideRect) => {
      const style = getComputedStyle(element, pseudo);
      const rawContent = style.content;
      if (!rawContent || rawContent === 'none' || rawContent === 'normal') return null;
      const quoted = (rawContent.startsWith('"') && rawContent.endsWith('"'))
        || (rawContent.startsWith("'") && rawContent.endsWith("'"));
      const content = quoted ? rawContent.slice(1, -1) : rawContent;
      const containerRect = element.getBoundingClientRect();
      const elementStyle = getComputedStyle(element);
      const borderLeft = pixelLength(elementStyle.borderLeftWidth) ?? 0;
      const borderTop = pixelLength(elementStyle.borderTopWidth) ?? 0;
      const borderRight = pixelLength(elementStyle.borderRightWidth) ?? 0;
      const borderBottom = pixelLength(elementStyle.borderBottomWidth) ?? 0;
      const containerWidth = containerRect.width - borderLeft - borderRight;
      const containerHeight = containerRect.height - borderTop - borderBottom;
      const left = pixelLength(style.left);
      const right = pixelLength(style.right);
      const top = pixelLength(style.top);
      const bottom = pixelLength(style.bottom);
      const explicitWidth = pixelLength(style.width);
      const explicitHeight = pixelLength(style.height);
      const fontSize = Number.parseFloat(style.fontSize);
      const lineHeight = pixelLength(style.lineHeight) ?? fontSize * 1.2;
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      if (context) context.font = style.font;
      const measuredWidth = (context?.measureText(content).width ?? fontSize * content.length)
        + Math.max(0, content.length - 1) * (pixelLength(style.letterSpacing) ?? 0);
      const width = explicitWidth ?? (left !== null && right !== null
        ? containerWidth - left - right
        : measuredWidth);
      const height = explicitHeight ?? (top !== null && bottom !== null
        ? containerHeight - top - bottom
        : lineHeight);
      const x = left !== null
        ? containerRect.left + borderLeft + left - slideRect.left
        : right !== null
          ? containerRect.right - borderRight - right - width - slideRect.left
          : Number.NaN;
      const y = top !== null
        ? containerRect.top + borderTop + top - slideRect.top
        : bottom !== null
          ? containerRect.bottom - borderBottom - bottom - height - slideRect.top
          : Number.NaN;
      const noOwnBoxEffects = !colorVisible(style.backgroundColor)
        && [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth]
          .every((value) => (pixelLength(value) ?? 0) === 0)
        && style.backgroundImage === 'none'
        && style.filter === 'none'
        && style.clipPath === 'none'
        && (!style.maskImage || style.maskImage === 'none')
        && style.transform === 'none';
      const simple = quoted
        && !content.includes('\n')
        && style.position === 'absolute'
        && noOwnBoxEffects
        && finite(x, y, width, height)
        && width > 0
        && height > 0
        && x >= 0
        && y >= 0
        && x + width <= 1920.01
        && y + height <= 1080.01;
      return {
        source_id: `${sourceId.slice(0, 72)}:${pseudo.slice(2)}`,
        content,
        simple,
        reason: simple ? null : 'complex_pseudo_element',
        x: simple ? x : 0,
        y: simple ? y : 0,
        width: simple ? width : 0,
        height: simple ? height : 0,
        paint_slot: pseudo === '::before' ? 2 : 4,
        paint_order: null,
        opacity: Number.parseFloat(style.opacity),
        color: style.color,
        font_family: style.fontFamily,
        font_size: Number.parseFloat(style.fontSize),
        font_weight: style.fontWeight,
        font_style: style.fontStyle,
        text_decoration: style.textDecorationLine,
        text_align: style.textAlign,
        line_height: style.lineHeight,
        letter_spacing: style.letterSpacing,
      };
    };
    const slides = [...document.querySelectorAll('.slide')];
    const allNodes = document.querySelectorAll('*').length;
    return {
      dom_nodes: allNodes,
      slides: slides.map((slide, slideIndex) => {
        const usedSourceIds = new Set();
        const slideRect = slide.getBoundingClientRect();
        const slideStyle = getComputedStyle(slide);
        const rootUnsupported = [];
        if (slideStyle.backgroundImage !== 'none') rootUnsupported.push('slide_background_image');
        const elements = [...slide.querySelectorAll('*')];
        const metadata = new Map();
        elements.forEach((element, domIndex) => {
          const generatedId = `s${slideIndex + 1}-n${domIndex + 1}`;
          const hintedId = element.getAttribute('data-pptx-id');
          const hintDiagnostics = [];
          const validHintedId = hintedId && /^[A-Za-z0-9_.-]{1,80}$/.test(hintedId);
          if (hintedId !== null && !validHintedId) hintDiagnostics.push('data-pptx-id:invalid-value');
          let sourceId = validHintedId ? hintedId : generatedId;
          if (usedSourceIds.has(sourceId)) {
            hintDiagnostics.push('data-pptx-id:duplicate-value');
            sourceId = generatedId;
            let suffix = 1;
            while (usedSourceIds.has(sourceId)) {
              sourceId = `${generatedId}-${suffix}`;
              suffix += 1;
            }
          }
          usedSourceIds.add(sourceId);
          element.setAttribute('data-elftia-capture-id', generatedId);
          element.setAttribute('data-elftia-source-id', sourceId);
          metadata.set(element, { domIndex, generatedId, hintDiagnostics, sourceId });
        });
        const records = [];
        elements.forEach((element) => {
          const {
            domIndex,
            generatedId,
            hintDiagnostics,
            sourceId,
          } = metadata.get(element);
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          if (
            style.display === 'none'
            || style.visibility !== 'visible'
            || Number.parseFloat(style.opacity) <= 0
            || rect.width <= 0
            || rect.height <= 0
          ) return;
          const domAncestorIds = [];
          let ancestor = element.parentElement;
          while (ancestor && ancestor !== slide) {
            const ancestorMetadata = metadata.get(ancestor);
            if (ancestorMetadata) domAncestorIds.push(ancestorMetadata.sourceId);
            ancestor = ancestor.parentElement;
          }
          const hints = [...element.attributes]
            .filter((attribute) => attribute.name.startsWith('data-pptx-'))
            .map((attribute) => attribute.name);
          const unknownHints = [
            ...hints.filter((name) => !HINTS.has(name)),
            ...hintDiagnostics,
          ];
          const hintedRole = element.getAttribute('data-pptx-role');
          const role = hintedRole && ROLES.has(hintedRole) ? hintedRole : null;
          if (hintedRole !== null && role === null) unknownHints.push('data-pptx-role:invalid-value');
          const ignoreHint = element.getAttribute('data-pptx-ignore');
          if (ignoreHint !== null && !['true', 'false'].includes(ignoreHint)) {
            unknownHints.push('data-pptx-ignore:invalid-value');
          }
          const rasterHint = element.getAttribute('data-pptx-raster');
          if (rasterHint !== null && !['true', 'false'].includes(rasterHint)) {
            unknownHints.push('data-pptx-raster:invalid-value');
          }
          const paragraphs = captureTextFlow(element);
          const text = paragraphs
            .map((paragraph) => paragraph.runs.map((run) => run.text).join(''))
            .join('\n');
          const hasFill = colorVisible(style.backgroundColor);
          const hasBorder = [
            style.borderTopWidth,
            style.borderRightWidth,
            style.borderBottomWidth,
            style.borderLeftWidth,
          ].some((width) => Number.parseFloat(width) > 0);
          const isImage = element.tagName === 'IMG' || role === 'image';
          const classification = classifyCss(style, element.tagName, Boolean(text));
          const unsupported = classification.unsupported;
          {
            const borderWidths = [
              style.borderTopWidth,
              style.borderRightWidth,
              style.borderBottomWidth,
              style.borderLeftWidth,
            ];
            const borderColors = [
              style.borderTopColor,
              style.borderRightColor,
              style.borderBottomColor,
              style.borderLeftColor,
            ];
            const borderStyles = [
              style.borderTopStyle,
              style.borderRightStyle,
              style.borderBottomStyle,
              style.borderLeftStyle,
            ];
            if (
              new Set(borderWidths).size > 1
              || (hasBorder && new Set(borderColors).size > 1)
              || new Set(borderStyles).size > 1
              || (hasBorder && style.borderTopStyle !== 'solid')
            ) unsupported.push(isImage ? 'image_border_unsupported' : 'shape_border_unsupported');
            const radii = [
              style.borderTopLeftRadius,
              style.borderTopRightRadius,
              style.borderBottomRightRadius,
              style.borderBottomLeftRadius,
            ];
            if (
              new Set(radii).size > 1
              || radii.some((value) => !/^(?:0|\d+(?:\.\d+)?)px$/.test(value))
            ) unsupported.push(isImage ? 'image_radius_unsupported' : 'shape_radius_unsupported');
          }
          const approximations = classification.approximations;
          const pseudo = [
            pseudoRecord(element, '::before', sourceId, slideRect),
            pseudoRecord(element, '::after', sourceId, slideRect),
          ].filter(Boolean);
          if (pseudo.some((item) => !item.simple)) unsupported.push('complex_pseudo_element');
          const relevant = text || hasFill || hasBorder || isImage || unsupported.length || pseudo.length || role;
          if (!relevant) return;
          if (
            text
            && style.display.startsWith('inline')
            && !hasFill
            && !hasBorder
            && !isImage
            && unsupported.length === 0
            && pseudo.length === 0
            && !role
          ) return;
          const geometry = resolvedGeometry(element, style, rect, slideRect);
          if (geometry.unsupported) unsupported.push(geometry.unsupported);
          if (!finite(geometry.x, geometry.y, geometry.width, geometry.height, geometry.rotation)) {
            unsupported.push('non_finite_geometry');
          }
          const radius = Number.parseFloat(style.borderTopLeftRadius) || 0;
          const kind = isImage ? 'image'
            : role ?? (text && !hasFill && !hasBorder ? 'text' : radius > 0 ? 'rounded-rectangle' : 'rectangle');
          const capturedTextStyle = textStyle(style);
          records.push({
            source_id: sourceId,
            parent_source_id: null,
            dom_ancestor_ids: domAncestorIds,
            capture_id: generatedId,
            capture_selector: `[data-elftia-capture-id="${generatedId}"]`,
            dom_index: domIndex,
            z_index: Number.isFinite(Number.parseInt(style.zIndex, 10)) ? Number.parseInt(style.zIndex, 10) : 0,
            kind,
            x: geometry.x,
            y: geometry.y,
            width: geometry.width,
            height: geometry.height,
            rotation: geometry.rotation,
            opacity: Number.parseFloat(style.opacity),
            fill: style.backgroundColor,
            border_color: style.borderTopColor,
            border_width: Number.parseFloat(style.borderTopWidth) || 0,
            radius,
            text,
            text_style: capturedTextStyle,
            text_insets: textInsets(style),
            paragraphs,
            requested_font: style.fontFamily.split(',', 1).at(0).trim().replace(/^["']|["']$/g, '') || null,
            font_evidence: fontEvidence(style),
            pseudo,
            image_src: isImage ? element.getAttribute('src') : null,
            image_width: isImage ? element.naturalWidth : null,
            image_height: isImage ? element.naturalHeight : null,
            object_fit: style.objectFit,
            object_position: style.objectPosition,
            image_crop: null,
            force_raster: rasterHint === 'true',
            ignored: ignoreHint === 'true',
            unknown_hints: unknownHints,
            unsupported,
            approximations,
            editable_descendants: element.querySelectorAll('*').length,
            capture_outcome: null,
            reason: null,
            asset_id: null,
          });
        });
        const emittedIds = new Set(records.map((record) => record.source_id));
        for (const record of records) {
          record.parent_source_id = record.dom_ancestor_ids.find((sourceId) => emittedIds.has(sourceId)) ?? null;
        }
        return {
          index: slideIndex + 1,
          width: slideRect.width,
          height: slideRect.height,
          x: 0,
          y: 0,
          root_fill: slideStyle.backgroundColor,
          root_unsupported: rootUnsupported,
          items: records,
        };
      }),
    };
  });
}

export { LIMITS };
