import assert from 'node:assert/strict';
import test from 'node:test';

import {
  blockedResourceReason,
  containedBrowserOptions,
  isAllowedCaptureUrl,
} from '../../runtime/node/html_browser_policy.mjs';

test('browser policy retains sandbox and cannot be weakened by caller options', () => {
  const options = containedBrowserOptions('C:\\Browser\\chrome.exe', {
    chromiumSandbox: false,
    javaScriptEnabled: true,
    serviceWorkers: 'allow',
    args: ['--no-sandbox'],
    viewport: { width: 1920, height: 1080 },
  });

  assert.equal(options.chromiumSandbox, true);
  assert.equal(options.javaScriptEnabled, false);
  assert.equal(options.serviceWorkers, 'block');
  assert.equal(options.headless, true);
  assert.deepEqual(options.viewport, { width: 1920, height: 1080 });
  assert.ok(options.args.includes('--disable-background-networking'));
  assert.ok(options.args.includes('--disable-extensions'));
  assert.ok(!options.args.some((argument) => argument.includes('no-sandbox')));
  assert.ok(!options.args.some((argument) => argument.includes('disable-setuid-sandbox')));
});

test('capture request policy allows only the exact token origin', () => {
  const origin = `http://127.0.0.1:43123/${'a'.repeat(64)}`;

  assert.equal(isAllowedCaptureUrl(origin, `${origin}/deck.html`), true);
  assert.equal(isAllowedCaptureUrl(origin, `${origin}/images/pixel.png`), true);
  assert.equal(isAllowedCaptureUrl(origin, 'data:image/png;base64,AA=='), false);
  assert.equal(isAllowedCaptureUrl(origin, 'data:image/jpeg;base64,AA=='), false);
  assert.equal(isAllowedCaptureUrl(origin, `${origin}x/deck.html`), false);
  assert.equal(isAllowedCaptureUrl(origin, 'data:image/svg+xml,<svg/>'), false);
  assert.equal(isAllowedCaptureUrl(origin, 'file:///private/deck.html'), false);
  assert.equal(isAllowedCaptureUrl(origin, 'https://example.invalid/deck.html'), false);
  assert.equal(isAllowedCaptureUrl(origin, 'custom:payload'), false);
});

test('blocked request diagnostics classify schemes without returning target details', () => {
  const origin = 'http://127.0.0.1:1234/' + 'a'.repeat(64);
  assert.equal(blockedResourceReason(origin, 'file:///private/deck.html'), 'file_url_blocked');
  assert.equal(blockedResourceReason(origin, 'data:image/png;base64,AA=='), 'data_url_blocked');
  assert.equal(blockedResourceReason(origin, 'HTTPS://example.invalid/deck.html'), 'remote_url_blocked');
  assert.equal(blockedResourceReason(origin, 'custom:payload'), 'custom_scheme_blocked');
  assert.equal(blockedResourceReason(origin, 'not a url'), 'custom_scheme_blocked');
  assert.equal(blockedResourceReason(origin, 'http://127.0.0.1:1234/outside.png'), 'path_escape');
});
