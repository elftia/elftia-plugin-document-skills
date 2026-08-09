import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { captureScene } from '../../runtime/node/html_scene_capture.mjs';

test('scene capture uses Chromium paint order instead of DOM or z-index guesses', async (context) => {
  const assets = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-scene-'));
  context.after(() => fs.rm(assets, { recursive: true, force: true }));
  const raw = rawDeck([
    item('front-in-dom', 'capture-front', 0, 100),
    item('back-in-dom', 'capture-back', 1, -100),
  ]);
  const page = fakePage(raw, snapshot([
    ['capture-front', 20],
    ['capture-back', 10],
  ]));

  const scene = await captureScene(page, assets, path.join(assets, 'private'), 'fail', []);

  assert.deepEqual(scene.slides[0].items.map((entry) => entry.source_id), [
    'back-in-dom',
    'front-in-dom',
  ]);
  assert.deepEqual(scene.slides[0].items.map((entry) => entry.paint_order), [1, 5]);
  assert.ok(scene.slides[0].items.every((entry) => !('capture_id' in entry)));
  assert.ok(scene.slides[0].items.every((entry) => !('capture_selector' in entry)));
});

test('scene capture fails closed when Chromium omits paint evidence', async (context) => {
  const assets = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-scene-'));
  context.after(() => fs.rm(assets, { recursive: true, force: true }));
  const raw = rawDeck([item('missing', 'capture-missing', 0, 0)]);
  const page = fakePage(raw, snapshot([]));

  await assert.rejects(
    captureScene(page, assets, path.join(assets, 'private'), 'fail', []),
    /paint_order_missing/,
  );
});

test('scene capture imports and deduplicates hash-bound local and data images with crop evidence', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-scene-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const bytes = tinyPng();
  await fs.writeFile(path.join(temporary, 'pixel.png'), bytes);
  const items = [
    imageItem('local', 'capture-local', 0, 'pixel.png'),
    imageItem('data', 'capture-data', 1, `data:image/png;base64,${bytes.toString('base64')}`),
  ];
  const page = fakePage(rawDeck(items), snapshot([
    ['capture-local', 1],
    ['capture-data', 2],
  ]));

  const scene = await captureScene(
    page,
    temporary,
    path.join(temporary, 'private'),
    'fail',
    [],
  );

  assert.equal(scene.assets.length, 1);
  assert.equal(scene.assets[0].mime, 'image/png');
  assert.equal(scene.assets[0].bytes, bytes.length);
  assert.equal(scene.assets[0].width, 1);
  assert.equal(scene.assets[0].height, 1);
  assert.equal(scene.assets[0].purpose, 'source-image');
  assert.match(scene.assets[0].id, /^[a-f0-9]{64}$/);
  assert.equal(scene.slides[0].items[0].asset_id, scene.assets[0].id);
  assert.equal(scene.slides[0].items[1].asset_id, scene.assets[0].id);
  assert.deepEqual(scene.slides[0].items[0].image_crop, {
    left: 0,
    top: 0.25,
    right: 0,
    bottom: 0.25,
  });
  assert.equal(scene.observed.asset_bytes, bytes.length);
  assert.equal(scene.observed.total_asset_bytes, bytes.length);
  assert.equal(scene.observed.resource_requests, 0);
});

test('scene capture uses the requested element only for raster fallback', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-scene-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const fallback = item('fallback', 'capture-fallback', 0, 0);
  fallback.unsupported = ['css_filter'];
  const screenshotSelectors = [];
  const page = fakePage(
    rawDeck([fallback]),
    snapshot([['capture-fallback', 1]]),
    screenshotSelectors,
  );

  const scene = await captureScene(
    page,
    temporary,
    path.join(temporary, 'private'),
    'element-rasterize',
    [],
  );

  assert.deepEqual(screenshotSelectors, ['[data-elftia-capture-id="capture-fallback"]']);
  assert.equal(scene.slides[0].items[0].capture_outcome, 'rasterized');
  assert.equal(scene.slides[0].items[0].reason, 'css_filter');
  assert.equal(scene.assets[0].purpose, 'element-fallback');
});

test('scene capture rejects malformed data image and decoded-pixel overflow with stable reasons', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-scene-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const malformed = imageItem('malformed', 'capture-malformed', 0, 'data:image/png;base64,AAAAA===');
  const excessive = imageItem('excessive', 'capture-excessive', 1, `data:image/png;base64,${tinyPng().toString('base64')}`);
  excessive.image_width = 10_000;
  excessive.image_height = 10_000;
  const page = fakePage(rawDeck([malformed, excessive]), snapshot([
    ['capture-malformed', 1],
    ['capture-excessive', 2],
  ]));

  const scene = await captureScene(
    page,
    temporary,
    path.join(temporary, 'private'),
    'fail',
    [],
  );

  assert.deepEqual(scene.slides[0].items.map((entry) => entry.reason), [
    'image_data_url_invalid',
    'image_image_pixel_limit',
  ]);
  assert.ok(scene.slides[0].items.every((entry) => entry.capture_outcome === 'rejected'));
  assert.equal(scene.assets.length, 0);
});

test('scene capture never rasterizes a slide-sized semantic subtree', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-scene-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const flattening = item('flattening', 'capture-flattening', 0, 0);
  flattening.force_raster = true;
  flattening.width = 1900;
  flattening.height = 1000;
  flattening.editable_descendants = 40;
  const screenshotSelectors = [];
  const page = fakePage(
    rawDeck([flattening]),
    snapshot([['capture-flattening', 1]]),
    screenshotSelectors,
  );

  const scene = await captureScene(
    page,
    temporary,
    path.join(temporary, 'private'),
    'element-rasterize',
    [],
  );

  assert.equal(scene.slides[0].items[0].capture_outcome, 'rejected');
  assert.equal(scene.slides[0].items[0].reason, 'semantic_flattening_guard');
  assert.deepEqual(screenshotSelectors, []);
  assert.equal(scene.assets.length, 0);
});

test('scene capture writes optional slide screenshots only as bounded private visual sources', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-scene-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const screenshotSelectors = [];
  const page = fakePage(
    rawDeck([item('native', 'capture-native', 0, 0)]),
    snapshot([['capture-native', 1]]),
    screenshotSelectors,
  );

  const scene = await captureScene(
    page,
    temporary,
    path.join(temporary, 'private'),
    'fail',
    [],
    true,
  );

  assert.deepEqual(screenshotSelectors, ['.slide:nth(0)']);
  assert.equal(scene.visual_sources.length, 1);
  assert.equal(scene.visual_sources[0].slide, 1);
  assert.equal(scene.visual_sources[0].asset_id, scene.assets[0].id);
  assert.equal(scene.assets[0].purpose, 'visual-source');
  assert.equal(scene.observed.assets, 1);
  assert.equal(scene.observed.asset_bytes, tinyPng().length);
});

test('scene capture rejects DOM, text, image-count, and non-finite geometry ceilings', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-scene-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const native = item('bounded', 'capture-bounded', 0, 0);

  const excessiveDom = rawDeck([native]);
  excessiveDom.dom_nodes = 20_001;
  await assert.rejects(
    captureScene(fakePage(excessiveDom, snapshot([['capture-bounded', 1]])), temporary, path.join(temporary, 'dom'), 'fail', []),
    /dom_limit/,
  );

  const excessiveTextItem = item('text-limit', 'capture-text', 0, 0);
  excessiveTextItem.text = 'x'.repeat(4 * 1024 * 1024 + 1);
  await assert.rejects(
    captureScene(fakePage(rawDeck([excessiveTextItem]), snapshot([['capture-text', 1]])), temporary, path.join(temporary, 'text'), 'fail', []),
    /scene_limit/,
  );

  const nonFinite = item('non-finite', 'capture-non-finite', 0, 0);
  nonFinite.x = Number.NaN;
  await assert.rejects(
    captureScene(fakePage(rawDeck([nonFinite]), snapshot([['capture-non-finite', 1]])), temporary, path.join(temporary, 'finite'), 'fail', []),
    /scene_limit/,
  );

  const imageSource = `data:image/png;base64,${tinyPng().toString('base64')}`;
  const images = Array.from({ length: 513 }, (_value, index) => (
    imageItem(`image-${index}`, `capture-image-${index}`, index, imageSource)
  ));
  const imagePaint = images.map((_value, index) => [`capture-image-${index}`, index + 1]);
  await assert.rejects(
    captureScene(fakePage(rawDeck(images), snapshot(imagePaint)), temporary, path.join(temporary, 'images'), 'fail', []),
    /image_count_limit/,
  );
});

function fakePage(raw, capturedSnapshot, screenshotSelectors = []) {
  return {
    evaluate: async () => structuredClone(raw),
    context: () => ({
      newCDPSession: async () => ({
        send: async (command, options) => {
          assert.equal(command, 'DOMSnapshot.captureSnapshot');
          assert.equal(options.includePaintOrder, true);
          return capturedSnapshot;
        },
        detach: async () => undefined,
      }),
    }),
    locator: (selector) => ({
      screenshot: async () => {
        screenshotSelectors.push(selector);
        return tinyPng();
      },
      nth: (index) => ({
        screenshot: async () => {
          screenshotSelectors.push(`${selector}:nth(${index})`);
          return tinyPng();
        },
      }),
    }),
  };
}

function snapshot(entries) {
  const strings = ['data-elftia-capture-id'];
  const attributes = [];
  const nodeIndex = [];
  const paintOrders = [];
  for (const [captureId, paintOrder] of entries) {
    strings.push(captureId);
    attributes.push([0, strings.length - 1]);
    nodeIndex.push(attributes.length - 1);
    paintOrders.push(paintOrder);
  }
  return {
    strings,
    documents: [{
      nodes: { attributes },
      layout: { nodeIndex, paintOrders },
    }],
  };
}

function rawDeck(items) {
  return {
    dom_nodes: items.length + 1,
    slides: [{
      index: 1,
      width: 1920,
      height: 1080,
      x: 0,
      y: 0,
      root_fill: 'rgb(255, 255, 255)',
      root_unsupported: [],
      items,
    }],
  };
}

function item(sourceId, captureId, domIndex, zIndex) {
  const style = {
    font_family: 'Arial',
    font_size: 32,
    font_weight: '400',
    font_style: 'normal',
    text_decoration: 'none',
    color: 'rgb(0, 0, 0)',
    text_align: 'left',
    line_height: 'normal',
  };
  return {
    source_id: sourceId,
    parent_source_id: null,
    capture_id: captureId,
    capture_selector: `[data-elftia-capture-id="${captureId}"]`,
    dom_index: domIndex,
    z_index: zIndex,
    kind: 'text',
    x: 10,
    y: 20,
    width: 300,
    height: 100,
    rotation: 0,
    opacity: 1,
    fill: 'rgba(0, 0, 0, 0)',
    border_color: 'rgb(0, 0, 0)',
    border_width: 0,
    radius: 0,
    text: sourceId,
    text_style: style,
    paragraphs: [{ runs: [{ text: sourceId, style }] }],
    requested_font: 'Arial',
    font_evidence: {
      requested_families: ['Arial'],
      computed_family: 'Arial',
    },
    pseudo: [],
    image_src: null,
    image_width: null,
    image_height: null,
    object_fit: 'fill',
    object_position: '50% 50%',
    image_crop: null,
    force_raster: false,
    ignored: false,
    unknown_hints: [],
    unsupported: [],
    approximations: [],
    editable_descendants: 0,
    capture_outcome: null,
    reason: null,
    asset_id: null,
  };
}

function imageItem(sourceId, captureId, domIndex, imageSource) {
  return {
    ...item(sourceId, captureId, domIndex, 0),
    kind: 'image',
    width: 200,
    height: 100,
    text: '',
    paragraphs: [],
    image_src: imageSource,
    image_width: 1,
    image_height: 1,
    object_fit: 'cover',
    object_position: '50% 50%',
  };
}

function tinyPng() {
  return Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z9ZcAAAAASUVORK5CYII=',
    'base64',
  );
}
