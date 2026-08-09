import assert from 'node:assert/strict';
import test from 'node:test';

import { createBlockedResourceCollector } from '../../runtime/node/html_resource_evidence.mjs';

test('blocked resource evidence merges declared and observed views of one occurrence', () => {
  const collector = createBlockedResourceCollector();
  const reference = 'https://example.invalid/private/path.css';
  collector.recordObserved('remote_url_blocked', reference);
  collector.recordDeclared('remote_url_blocked', reference);

  const evidence = collector.snapshot();

  assert.equal(evidence.total, 1);
  assert.deepEqual(evidence.by_reason, { remote_url_blocked: 1 });
  assert.equal(evidence.samples.length, 1);
  assert.equal(evidence.samples[0].reason, 'remote_url_blocked');
  assert.match(evidence.samples[0].resource_hash, /^[a-f0-9]{64}$/);
  assert.ok(!JSON.stringify(evidence).includes('example.invalid'));
  assert.equal(evidence.truncated, 0);
});

test('blocked resource totals and truncated occurrences are independent of sample storage', () => {
  const collector = createBlockedResourceCollector();
  for (let index = 0; index < 40; index += 1) {
    collector.recordDeclared('remote_url_blocked', `https://example.invalid/${index}.css`);
  }

  const evidence = collector.snapshot();

  assert.equal(evidence.total, 40);
  assert.deepEqual(evidence.by_reason, { remote_url_blocked: 40 });
  assert.equal(evidence.samples.length, 32);
  assert.equal(evidence.truncated, 8);
});
