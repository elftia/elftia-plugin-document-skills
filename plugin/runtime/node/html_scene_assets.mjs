import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

import { resolveLocalAsset } from './html_asset_server.mjs';

const NATIVE_IMAGE_MIMES = new Map([
  ['image/jpeg', 'jpg'],
  ['image/png', 'png'],
]);

export async function importImageAsset(sourceRoot, assetsDir, item, limits) {
  if (!item.image_src || !item.image_width || !item.image_height) throw new Error('image_invalid');
  if (item.image_width * item.image_height > limits.image_pixels) throw new Error('image_pixel_limit');
  let bytes;
  let mime;
  if (item.image_src.startsWith('data:')) {
    const match = /^data:(image\/(?:png|jpeg));base64,([A-Za-z0-9+/=]+)$/.exec(item.image_src);
    if (!match) throw new Error('data_url_invalid');
    mime = match.at(1);
    bytes = Buffer.from(match.at(2), 'base64');
    if (bytes.toString('base64') !== match.at(2) || sniffImage(bytes) !== mime) {
      throw new Error('data_url_invalid');
    }
  } else {
    if (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(item.image_src) || item.image_src.startsWith('//')) {
      throw new Error('image_scheme_blocked');
    }
    const file = await resolveLocalAsset(sourceRoot, item.image_src);
    bytes = await fs.readFile(file);
    mime = sniffImage(bytes);
  }
  if (bytes.length <= 0 || bytes.length > limits.image_bytes || !NATIVE_IMAGE_MIMES.has(mime)) {
    throw new Error('image_type_or_size');
  }
  return storeAsset(assetsDir, bytes, mime, item.image_width, item.image_height, 'source-image');
}

export function imageCrop(item, asset) {
  if (item.object_fit === 'fill') return { left: 0, top: 0, right: 0, bottom: 0 };
  if (item.object_fit !== 'cover') throw new Error('image_object_fit');
  const position = objectPosition(item.object_position);
  const sourceRatio = asset.width / asset.height;
  const targetRatio = item.width / item.height;
  if (sourceRatio > targetRatio) {
    const total = 1 - targetRatio / sourceRatio;
    return { left: total * position.x, top: 0, right: total * (1 - position.x), bottom: 0 };
  }
  const total = 1 - sourceRatio / targetRatio;
  return { left: 0, top: total * position.y, right: 0, bottom: total * (1 - position.y) };
}

function objectPosition(value) {
  const parts = String(value ?? '').trim().split(/\s+/);
  if (parts.length !== 2) throw new Error('image_object_position');
  const keywords = new Map([
    ['left', 0], ['top', 0], ['center', 0.5], ['right', 1], ['bottom', 1],
  ]);
  const fraction = (part) => {
    if (keywords.has(part)) return keywords.get(part);
    if (!/^\d+(?:\.\d+)?%$/.test(part)) throw new Error('image_object_position');
    const result = Number.parseFloat(part) / 100;
    if (!Number.isFinite(result) || result < 0 || result > 1) throw new Error('image_object_position');
    return result;
  };
  return { x: fraction(parts.at(0)), y: fraction(parts.at(1)) };
}

export async function captureFallback(page, assetsDir, item, limits) {
  const bytes = await page.locator(item.capture_selector).screenshot({ animations: 'disabled', type: 'png' });
  if (bytes.length > limits.image_bytes) throw new Error('fallback_size');
  return storeAsset(assetsDir, bytes, 'image/png', Math.ceil(item.width), Math.ceil(item.height), 'element-fallback');
}

export async function storeAsset(assetsDir, bytes, mime, width, height, purpose) {
  const id = crypto.createHash('sha256').update(bytes).digest('hex');
  const extension = NATIVE_IMAGE_MIMES.get(mime);
  const filename = `asset-${id}.${extension}`;
  await fs.writeFile(path.join(assetsDir, filename), bytes, { flag: 'wx', mode: 0o600 }).catch((error) => {
    if (error.code !== 'EEXIST') throw error;
  });
  return { id, filename, mime, bytes: bytes.length, width, height, purpose };
}

export function registerAsset(assets, asset) {
  if (assets.has(asset.id)) return 0;
  assets.set(asset.id, asset);
  return asset.bytes;
}

export function finiteBox(value) {
  return [value.x, value.y, value.width, value.height].every(Number.isFinite);
}

export function assetReason(error) {
  const reason = error instanceof Error ? error.message : 'image_invalid';
  return `image_${reason}`.slice(0, 80);
}

function sniffImage(bytes) {
  if (bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) return 'image/png';
  if (bytes.at(0) === 0xff && bytes.at(1) === 0xd8 && bytes.at(-2) === 0xff && bytes.at(-1) === 0xd9) return 'image/jpeg';
  throw new Error('image_magic');
}
