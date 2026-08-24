const PIXEL_LENGTH = /^-?(?:\d+|\d*\.\d+)px$/;

export function classifyCss(style, tagName, hasText) {
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
  if (String(tagName).toUpperCase() !== 'IMG' && [style.overflowX, style.overflowY].some((value) => (
    typeof value === 'string' && !['visible', 'unset'].includes(value)
  ))) unsupported.push('css_overflow_clip');
  if (hasText && typeof style.whiteSpace === 'string' && style.whiteSpace !== 'normal') {
    unsupported.push('css_white_space');
  }
  if (hasText && (
    (typeof style.wordBreak === 'string' && !['normal', 'unset'].includes(style.wordBreak))
    || (typeof style.overflowWrap === 'string' && !['normal', 'unset'].includes(style.overflowWrap))
  )) unsupported.push('css_word_break');
  if (hasText && typeof style.textOverflow === 'string' && !['clip', 'unset'].includes(style.textOverflow)) {
    unsupported.push('css_text_overflow');
  }
  if (hasText && style.letterSpacing !== 'normal' && pixelLength(style.letterSpacing) === null) {
    unsupported.push('css_letter_spacing');
  }
  if (['flex', 'inline-flex'].includes(style.display)) approximations.push('computed_flex_layout');
  if (['grid', 'inline-grid'].includes(style.display)) approximations.push('computed_grid_layout');
  return {
    unsupported: [...new Set(unsupported)],
    approximations: [...new Set(approximations)],
  };
}

export function textInsets(style) {
  return {
    left: nonNegativePixel(style.paddingLeft),
    top: nonNegativePixel(style.paddingTop),
    right: nonNegativePixel(style.paddingRight),
    bottom: nonNegativePixel(style.paddingBottom),
  };
}

export function pixelLength(value) {
  if (typeof value !== 'string' || !PIXEL_LENGTH.test(value)) return null;
  const result = Number.parseFloat(value);
  return Number.isFinite(result) ? result : null;
}

function nonNegativePixel(value) {
  const result = pixelLength(value);
  return result === null ? 0 : Math.max(0, result);
}
