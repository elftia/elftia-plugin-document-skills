import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import {
  resolveLocalAsset,
  startAssetServer,
} from '../../runtime/node/html_asset_server.mjs';

const TOKEN = 'a'.repeat(64);

test('tokenized loopback server serves only bounded allowlisted descendant files', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-assets-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const root = path.join(temporary, 'deck');
  await fs.mkdir(path.join(root, 'images'), { recursive: true });
  await fs.writeFile(path.join(root, 'deck.html'), '<section class="slide"></section>');
  await fs.writeFile(path.join(root, 'images', 'pixel.png'), tinyPng());
  await fs.writeFile(path.join(root, 'notes.txt'), 'not allowlisted');
  await fs.writeFile(path.join(root, 'too-large.png'), Buffer.alloc(8 * 1024 * 1024 + 1));
  const blocked = [];
  const server = await startAssetServer(root, TOKEN, (reason) => blocked.push(reason));
  context.after(() => server.close());

  assert.match(server.origin, /^http:\/\/127\.0\.0\.1:\d+\/[a-f0-9]{64}$/);
  const html = await fetch(`${server.origin}/deck.html`);
  assert.equal(html.status, 200);
  assert.equal(html.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.equal(html.headers.get('cache-control'), 'no-store');
  assert.match(html.headers.get('content-security-policy'), /script-src 'none'/);
  assert.equal(await html.text(), '<section class="slide"></section>');

  const image = await fetch(`${server.origin}/images/pixel.png`);
  assert.equal(image.status, 200);
  assert.equal(image.headers.get('content-type'), 'image/png');

  assert.equal((await fetch(`${server.origin}/notes.txt`)).status, 404);
  assert.equal((await fetch(`${server.origin}/images/`)).status, 404);
  assert.equal((await fetch(`${server.origin}/too-large.png`)).status, 404);
  assert.equal((await fetch(`${server.origin}/deck.html?query=1`)).status, 404);
  assert.equal((await fetch(server.origin, { method: 'POST' })).status, 404);
  assert.deepEqual(blocked, [
    'asset_unavailable',
    'path_escape',
    'asset_unavailable',
    'invalid_token',
    'method_blocked',
  ]);
});

test('server rejects a non-cryptographic origin token', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-assets-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));

  await assert.rejects(
    async () => {
      const started = await startAssetServer(temporary, 'not/a-token', () => undefined);
      await started.close();
    },
    /invalid_token/,
  );
});

test('server serves local SVG only through a tokenized bounded descendant route', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-assets-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const root = path.join(temporary, 'deck');
  await fs.mkdir(root);
  await fs.writeFile(
    path.join(root, 'vector.svg'),
    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"></svg>',
  );
  await fs.writeFile(path.join(root, 'too-large.svg'), Buffer.alloc(8 * 1024 * 1024 + 1));
  await fs.writeFile(path.join(temporary, 'outside.svg'), '<svg xmlns="http://www.w3.org/2000/svg"/>');
  const blocked = [];
  const server = await startAssetServer(root, TOKEN, (reason) => blocked.push(reason));
  context.after(() => server.close());

  const vector = await fetch(`${server.origin}/vector.svg`);
  assert.equal(vector.status, 200);
  assert.equal(vector.headers.get('content-type'), 'image/svg+xml');
  assert.match(await vector.text(), /^<svg /);

  const endpoint = new URL(server.origin);
  assert.equal((await fetch(`${endpoint.origin}/vector.svg`)).status, 404);
  assert.equal((await fetch(`${server.origin}/too-large.svg`)).status, 404);
  await assert.rejects(resolveLocalAsset(root, '../outside.svg'), /asset_escape/);
  assert.deepEqual(blocked, ['invalid_token', 'asset_unavailable']);
});

test('asset resolution rejects traversal, absolute paths, and symlink escape', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-assets-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const root = path.join(temporary, 'deck');
  const outside = path.join(temporary, 'outside.png');
  await fs.mkdir(root);
  await fs.writeFile(path.join(root, 'inside.png'), tinyPng());
  await fs.writeFile(outside, tinyPng());

  assert.equal(await resolveLocalAsset(root, 'inside.png'), await fs.realpath(path.join(root, 'inside.png')));
  for (const reference of ['../outside.png', '%2e%2e/outside.png', '/outside.png', 'C:\\outside.png', '']) {
    await assert.rejects(resolveLocalAsset(root, reference));
  }

  const link = path.join(root, 'linked.png');
  try {
    await fs.symlink(outside, link, 'file');
  } catch (error) {
    if (error?.code === 'EPERM') {
      context.diagnostic('file symlink creation is unavailable on this Windows host');
      return;
    }
    throw error;
  }
  await assert.rejects(resolveLocalAsset(root, 'linked.png'), /asset_escape|asset_symlink/);
});

test('server rejects traversal and absolute-form proxy requests without disclosure', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-assets-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const root = path.join(temporary, 'deck');
  await fs.mkdir(root);
  await fs.writeFile(path.join(root, 'deck.html'), '<html></html>');
  const blocked = [];
  const server = await startAssetServer(root, TOKEN, (reason) => blocked.push(reason));
  context.after(() => server.close());
  const endpoint = new URL(server.origin);

  const traversal = await rawRequest(endpoint, `/${TOKEN}/%2e%2e/outside.html`);
  const proxy = await rawRequest(endpoint, 'http://example.invalid/deck.html');
  assert.equal(traversal.statusCode, 404);
  assert.equal(proxy.statusCode, 404);
  assert.deepEqual(blocked, ['invalid_token', 'invalid_token']);
  assert.equal(traversal.body, '');
  assert.equal(proxy.body, '');
});

test('server fails closed when cumulative HTML CSS and font bytes exceed the capture budget', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-assets-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  await fs.writeFile(path.join(temporary, 'deck.html'), '1234');
  await fs.writeFile(path.join(temporary, 'first.css'), '5678');
  await fs.writeFile(path.join(temporary, 'second.css'), '90ab');
  await fs.writeFile(path.join(temporary, 'font.woff2'), 'cdef');
  const blocked = [];
  const server = await startAssetServer(
    temporary,
    TOKEN,
    (reason) => blocked.push(reason),
    { maxRequests: 8, maxTotalBytes: 12 },
  );
  context.after(() => server.close());

  assert.equal((await fetch(`${server.origin}/deck.html`)).status, 200);
  assert.equal((await fetch(`${server.origin}/first.css`)).status, 200);
  assert.equal((await fetch(`${server.origin}/second.css`)).status, 200);
  assert.equal((await fetch(`${server.origin}/font.woff2`)).status, 404);
  assert.deepEqual(server.usage(), { bytes: 12, requests: 4 });
  assert.throws(server.assertWithinBudget, /asset_total_limit/);
  assert.equal(blocked.at(-1), 'asset_total_limit');
});

test('server fails closed when multi-asset CSS and font requests exceed the capture budget', async (context) => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'document-skills-assets-'));
  context.after(() => fs.rm(temporary, { recursive: true, force: true }));
  for (const filename of ['deck.html', 'first.css', 'second.css', 'font.woff2']) {
    await fs.writeFile(path.join(temporary, filename), 'x');
  }
  const blocked = [];
  const server = await startAssetServer(
    temporary,
    TOKEN,
    (reason) => blocked.push(reason),
    { maxRequests: 3, maxTotalBytes: 32 },
  );
  context.after(() => server.close());

  assert.equal((await fetch(`${server.origin}/deck.html`)).status, 200);
  assert.equal((await fetch(`${server.origin}/first.css`)).status, 200);
  assert.equal((await fetch(`${server.origin}/second.css`)).status, 200);
  assert.equal((await fetch(`${server.origin}/font.woff2`)).status, 404);
  assert.deepEqual(server.usage(), { bytes: 3, requests: 4 });
  assert.throws(server.assertWithinBudget, /asset_request_limit/);
  assert.equal(blocked.at(-1), 'asset_request_limit');
});

function rawRequest(endpoint, requestPath) {
  return new Promise((resolve, reject) => {
    const request = http.request({
      host: endpoint.hostname,
      port: endpoint.port,
      method: 'GET',
      path: requestPath,
    }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => resolve({
        statusCode: response.statusCode,
        body: Buffer.concat(chunks).toString('utf8'),
      }));
    });
    request.on('error', reject);
    request.end();
  });
}

function tinyPng() {
  return Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z9ZcAAAAASUVORK5CYII=',
    'base64',
  );
}
