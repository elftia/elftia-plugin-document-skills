import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

import { chromium } from 'playwright-core';

import { startAssetServer } from './html_asset_server.mjs';
import {
  blockedResourceReason,
  containedBrowserOptions,
  isAllowedCaptureUrl,
} from './html_browser_policy.mjs';
import { captureScene, LIMITS } from './html_scene_capture.mjs';
import {
  collectDeclaredBlockedResources,
  createBlockedResourceCollector,
} from './html_resource_evidence.mjs';

const PROTOCOL_VERSION = '1.0';
const MAX_STDIN_BYTES = 64 * 1024;
const MAX_HTML_BYTES = 8 * 1024 * 1024;
const PROFILE_REMOVE_OPTIONS = Object.freeze({
  recursive: true,
  force: true,
  maxRetries: 5,
  retryDelay: 100,
});

async function readRequest() {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > MAX_STDIN_BYTES) throw new Error('request_too_large');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function validateProbeRequest(value) {
  const keys = Object.keys(value).sort();
  const expected = ['command', 'executable_path', 'profile_root', 'protocol_version'];
  if (JSON.stringify(keys) !== JSON.stringify(expected)) throw new Error('invalid_fields');
  if (value.protocol_version !== PROTOCOL_VERSION || value.command !== 'probe') {
    throw new Error('invalid_protocol');
  }
  if (!path.isAbsolute(value.executable_path) || !path.isAbsolute(value.profile_root)) {
    throw new Error('invalid_path');
  }
  return value;
}

async function validateCaptureRequest(value) {
  const keys = Object.keys(value).sort();
  const expected = [
    'assets_dir',
    'browser_executable',
    'capture_visuals',
    'command',
    'fallback_policy',
    'html_path',
    'nonce',
    'private_root',
    'profile_root',
    'protocol_version',
    'scene_path',
    'token',
  ];
  if (JSON.stringify(keys) !== JSON.stringify(expected)) throw new Error('invalid_capture_fields');
  if (value.protocol_version !== PROTOCOL_VERSION || value.command !== 'capture') {
    throw new Error('invalid_protocol');
  }
  if (!/^[a-f0-9]{32,96}$/.test(value.nonce) || !/^[a-f0-9]{32,96}$/.test(value.token)) {
    throw new Error('invalid_nonce');
  }
  if (!['element-rasterize', 'fail'].includes(value.fallback_policy)) {
    throw new Error('invalid_fallback_policy');
  }
  if (typeof value.capture_visuals !== 'boolean') throw new Error('invalid_capture_visuals');
  const paths = [
    value.assets_dir,
    value.browser_executable,
    value.html_path,
    value.private_root,
    value.profile_root,
    value.scene_path,
  ];
  for (const candidate of paths) {
    if (typeof candidate !== 'string' || !path.isAbsolute(candidate)) throw new Error('invalid_path');
  }
  const privateRoot = await fs.realpath(value.private_root);
  const cwd = await fs.realpath(process.cwd());
  if (privateRoot !== cwd) throw new Error('invalid_private_root');
  if (path.dirname(value.scene_path) !== privateRoot || path.dirname(value.assets_dir) !== privateRoot || path.dirname(value.profile_root) !== privateRoot) {
    throw new Error('private_path_escape');
  }
  const htmlPath = await fs.realpath(value.html_path);
  const stat = await fs.stat(htmlPath);
  if (!stat.isFile() || stat.size <= 0 || stat.size > MAX_HTML_BYTES || !['.html', '.htm'].includes(path.extname(htmlPath).toLowerCase())) {
    throw new Error('html_input_invalid');
  }
  return { ...value, private_root: privateRoot, html_path: htmlPath };
}

async function probe(request) {
  const profile = path.join(request.profile_root, 'profile');
  await fs.mkdir(profile, { recursive: true, mode: 0o700 });
  let context;
  try {
    context = await chromium.launchPersistentContext(
      profile,
      containedBrowserOptions(request.executable_path),
    );
    const page = context.pages().at(0) ?? await context.newPage();
    await page.setContent('<!doctype html><meta charset="utf-8"><div id="health">ok</div>');
    const healthy = await page.locator('#health').textContent() === 'ok';
    return {
      protocol_version: PROTOCOL_VERSION,
      command: 'probe',
      ok: healthy,
      browser_version: context.browser()?.version() ?? null,
      reason: healthy ? null : 'dom_health_failed',
    };
  } catch {
    return {
      protocol_version: PROTOCOL_VERSION,
      command: 'probe',
      ok: false,
      browser_version: null,
      reason: 'browser_launch_failed',
    };
  } finally {
    if (context) await context.close().catch(() => undefined);
    await fs.rm(profile, PROFILE_REMOVE_OPTIONS).catch(() => undefined);
  }
}

async function capture(request) {
  const blocked = createBlockedResourceCollector();
  const server = await startAssetServer(path.dirname(request.html_path), request.token, (reason, reference) => {
    blocked.recordObserved(reason, reference);
  });
  let context;
  try {
    await fs.mkdir(request.profile_root, { recursive: true, mode: 0o700 });
    context = await chromium.launchPersistentContext(
      request.profile_root,
      containedBrowserOptions(request.browser_executable, {
        viewport: { width: 1920, height: 1080 },
      }),
    );
    const page = context.pages().at(0) ?? await context.newPage();
    await page.route('**/*', async (route) => {
      const url = route.request().url();
      if (isAllowedCaptureUrl(server.origin, url)) {
        await route.continue();
      } else {
        blocked.recordObserved(blockedResourceReason(server.origin, url), url);
        await route.abort('blockedbyclient');
      }
    });
    const deckUrl = `${server.origin}/${encodeURIComponent(path.basename(request.html_path))}`;
    // The static contract includes local images and stylesheets. Waiting for
    // `load` binds their decoded dimensions before DOM capture and avoids a
    // timing-dependent native-image versus fallback classification.
    try {
      await page.goto(deckUrl, { waitUntil: 'load', timeout: 15_000 });
    } catch (error) {
      server.assertWithinBudget();
      throw error;
    }
    server.assertWithinBudget();
    blocked.mergeDeclared(await collectDeclaredBlockedResources(page, server.origin));
    const blockedEvidence = blocked.snapshot();
    const usage = server.usage();
    const resourceRequests = usage.requests + blockedEvidence.total;
    if (resourceRequests > LIMITS.resource_requests) throw new Error('asset_request_limit');
    const scene = await captureScene(
      page,
      path.dirname(request.html_path),
      request.assets_dir,
      request.fallback_policy,
      blockedEvidence,
      request.capture_visuals,
      { bytes: usage.bytes, requests: resourceRequests },
    );
    const bytes = Buffer.from(`${JSON.stringify(scene)}\n`, 'utf8');
    if (bytes.length > LIMITS.scene_bytes) throw new Error('scene_bytes_limit');
    if (bytes.length + scene.observed.asset_bytes !== scene.observed.capture_bytes) {
      throw new Error('capture_bytes_binding');
    }
    const temporary = `${request.scene_path}.${request.nonce}.tmp`;
    await fs.writeFile(temporary, bytes, { flag: 'wx', mode: 0o600 });
    await fs.rename(temporary, request.scene_path);
    return {
      protocol_version: PROTOCOL_VERSION,
      command: 'capture',
      nonce: request.nonce,
      ok: true,
      scene_bytes: bytes.length,
      asset_bytes: scene.observed.asset_bytes,
      reason: null,
    };
  } finally {
    if (context) await context.close().catch(() => undefined);
    await server.close().catch(() => undefined);
    await fs.rm(request.profile_root, PROFILE_REMOVE_OPTIONS).catch(() => undefined);
  }
}

async function main() {
  let response;
  let requestedCommand = 'probe';
  try {
    const raw = await readRequest();
    requestedCommand = raw.command;
    if (raw.command === 'probe') {
      response = await probe(validateProbeRequest(raw));
    } else {
      const request = await validateCaptureRequest(raw);
      try {
        response = await capture(request);
      } catch (error) {
        response = captureFailure(request.nonce, error);
      }
    }
  } catch (error) {
    response = requestedCommand === 'capture'
      ? captureFailure('', error)
      : {
          protocol_version: PROTOCOL_VERSION,
          command: 'probe',
          ok: false,
          browser_version: null,
          reason: 'invalid_probe_request',
        };
  }
  process.stdout.write(`${JSON.stringify(response)}\n`);
}

function captureFailure(nonce, error) {
  const allowed = new Set([
    'asset_total_limit',
    'asset_request_limit',
    'asset_count_limit',
    'capture_bytes_limit',
    'dom_limit',
    'html_input_invalid',
    'scene_bytes_limit',
    'scene_limit',
    'image_count_limit',
    'slide_geometry',
    'slide_root_unsupported',
    'slides_missing',
    'visual_source_size',
  ]);
  const raw = error instanceof Error ? error.message : '';
  return {
    protocol_version: PROTOCOL_VERSION,
    command: 'capture',
    nonce,
    ok: false,
    scene_bytes: 0,
    asset_bytes: 0,
    reason: allowed.has(raw) ? raw : 'capture_failed',
  };
}

await main();
