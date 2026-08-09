import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';

import { buildArtifact, releasePaths } from '../artifact.mjs';
import {
  assertReleaseCheckoutPolicy,
  isReviewedBinaryReleasePath,
  REVIEWED_CRLF_RELEASE_PATHS,
} from '../checkout-policy.mjs';
import * as inventory from '../inventory.mjs';
import { artifactRoot, pluginRoot } from '../paths.mjs';

test('every release path has the reviewed effective checkout policy', () => {
  const entries = assertReleaseCheckoutPolicy(releasePaths());
  assert.deepEqual(
    entries.filter((entry) => entry.eol === 'crlf').map((entry) => entry.path),
    [...REVIEWED_CRLF_RELEASE_PATHS],
  );
});

test('artifact construction preserves every reviewed binary payload byte-for-byte', async () => {
  const paths = releasePaths();
  await buildArtifact();
  const binaryPaths = paths.filter(isReviewedBinaryReleasePath);
  assert.equal(binaryPaths.length, 16);
  for (const relative of binaryPaths) {
    const source = await readFile(path.join(pluginRoot, ...relative.split('/')));
    const artifact = await readFile(path.join(artifactRoot, ...relative.split('/')));
    assert.deepEqual(artifact, source, relative);
  }
});

test('inventory mismatch diagnostics name the first path and differing field', () => {
  const expected = {
    fileCount: 2,
    sha256: 'expected-aggregate',
    entries: [
      { path: 'a.txt', length: 3, sha256: 'same' },
      { path: 'b.txt', length: 4, sha256: 'expected-path-sha' },
    ],
  };
  const observed = {
    fileCount: 2,
    sha256: 'observed-aggregate',
    entries: [
      { path: 'a.txt', length: 3, sha256: 'same' },
      { path: 'b.txt', length: 5, sha256: 'observed-path-sha' },
    ],
  };
  assert.throws(
    () => inventory.assertInventoriesEqual(expected, observed, 'focused regression'),
    /focused regression.*path=b\.txt.*field=length.*expected=4.*observed=5/,
  );
  assert.throws(
    () =>
      inventory.assertInventoriesEqual(
        expected,
        { fileCount: 1, sha256: 'missing', entries: observed.entries.slice(0, 1) },
        'missing regression',
      ),
    /missing regression.*path=b\.txt.*field=type.*expected=file.*observed=absent/,
  );
  assert.throws(
    () =>
      inventory.assertInventoriesEqual(
        expected,
        {
          ...observed,
          entries: [observed.entries[0], { ...observed.entries[1], length: 4 }],
        },
        'digest regression',
      ),
    /digest regression.*path=b\.txt.*field=sha256.*expected=expected-path-sha.*observed=observed-path-sha/,
  );
});
