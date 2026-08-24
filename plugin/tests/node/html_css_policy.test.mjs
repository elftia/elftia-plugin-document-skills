import assert from 'node:assert/strict';
import test from 'node:test';

import { classifyCss, pixelLength, textInsets } from '../../runtime/node/html_css_policy.mjs';

const BASE = Object.freeze({
  backgroundImage: 'none',
  boxShadow: 'none',
  filter: 'none',
  clipPath: 'none',
  maskImage: 'none',
  mixBlendMode: 'normal',
  overflowX: 'visible',
  overflowY: 'visible',
  whiteSpace: 'normal',
  wordBreak: 'normal',
  overflowWrap: 'normal',
  textOverflow: 'clip',
  letterSpacing: 'normal',
  display: 'block',
  paddingLeft: '10px',
  paddingTop: '20px',
  paddingRight: '30px',
  paddingBottom: '40px',
});

test('CSS policy keeps native text spacing bounded and records computed flex/grid layout', () => {
  assert.deepEqual(classifyCss(BASE, 'DIV', true), { unsupported: [], approximations: [] });
  assert.deepEqual(classifyCss({ ...BASE, display: 'flex', letterSpacing: '1.5px' }, 'DIV', true), {
    unsupported: [],
    approximations: ['computed_flex_layout'],
  });
  assert.deepEqual(classifyCss({ ...BASE, display: 'grid' }, 'DIV', false), {
    unsupported: [],
    approximations: ['computed_grid_layout'],
  });
  assert.equal(pixelLength('-1.25px'), -1.25);
  assert.deepEqual(textInsets(BASE), { left: 10, top: 20, right: 30, bottom: 40 });
});

test('CSS policy routes unsupported effects, clipping, text flow, and active media to fallback', () => {
  const result = classifyCss({
    ...BASE,
    backgroundImage: 'linear-gradient(red, blue)',
    boxShadow: '1px 1px 2px black',
    filter: 'blur(2px)',
    clipPath: 'circle(50%)',
    maskImage: 'url(mask.png)',
    mixBlendMode: 'multiply',
    overflowX: 'hidden',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
    overflowWrap: 'anywhere',
    textOverflow: 'ellipsis',
    letterSpacing: 'calc(1px + 1em)',
  }, 'CANVAS', true);
  assert.deepEqual(result.unsupported, [
    'html_canvas',
    'css_background_image',
    'css_box_shadow',
    'css_filter',
    'css_clip_path',
    'css_mask',
    'css_blend_mode',
    'css_overflow_clip',
    'css_white_space',
    'css_word_break',
    'css_text_overflow',
    'css_letter_spacing',
  ]);
  for (const [tag, reason] of [
    ['VIDEO', 'html_video'],
    ['SVG', 'html_inline_svg'],
    ['IFRAME', 'html_embedded_content'],
  ]) {
    assert.deepEqual(classifyCss(BASE, tag, false).unsupported, [reason]);
  }
});
