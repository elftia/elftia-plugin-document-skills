import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_PYTEST_WORKERS,
  resolvePytestWorkers,
} from '../lib/pytest.mjs';

test('pytest workers default to a bounded count', () => {
  assert.equal(DEFAULT_PYTEST_WORKERS, 4);
  assert.equal(resolvePytestWorkers(undefined), '4');
  assert.equal(resolvePytestWorkers(''), '4');
});

test('pytest workers accept positive integer overrides', () => {
  assert.equal(resolvePytestWorkers(' 2 '), '2');
  assert.equal(resolvePytestWorkers('004'), '4');
});

test('pytest workers reject non-positive and unsafe overrides', () => {
  for (const value of ['0', '-1', 'auto', '1.5', '9'.repeat(32)]) {
    assert.throws(
      () => resolvePytestWorkers(value),
      /DS_PYTEST_WORKERS must be a positive integer/,
    );
  }
});
