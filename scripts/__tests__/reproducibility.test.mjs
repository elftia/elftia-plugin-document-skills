import assert from 'node:assert/strict';
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
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
import { pythonCompileallArgs, runUv } from '../process.mjs';

test('Python compilation excludes executable fixture sources cross-platform', async (context) => {
  const args = pythonCompileallArgs();
  const excludeIndex = args.indexOf('-x');
  assert.notEqual(excludeIndex, -1);
  const excluded = new RegExp(args[excludeIndex + 1]);
  assert.match('tests/fixtures/pdf-worker-failures/worker.py', excluded);
  assert.match(String.raw`tests\fixtures\pdf-worker-failures\worker.py`, excluded);
  assert.doesNotMatch('tests/test_pdf_public_worker_failures.py', excluded);
  assert.doesNotMatch('src/document_skills_core/worker/main.py', excluded);
  assert.deepEqual(args.slice(-3), ['src', 'tools', 'tests']);

  const root = await mkdtemp(path.join(os.tmpdir(), 'elftia-compileall-'));
  context.after(() => rm(root, { recursive: true, force: true }));
  for (const directory of ['src', 'tools', 'tests', 'tests/fixtures/pdf-worker-failures']) {
    await mkdir(path.join(root, ...directory.split('/')), { recursive: true });
  }
  await Promise.all([
    writeFile(path.join(root, 'src', 'module.py'), 'VALUE = 1\n'),
    writeFile(path.join(root, 'tools', 'tool.py'), 'VALUE = 2\n'),
    writeFile(path.join(root, 'tests', 'test_module.py'), 'VALUE = 3\n'),
    writeFile(
      path.join(root, 'tests', 'fixtures', 'pdf-worker-failures', 'worker.py'),
      'VALUE = 4\n',
    ),
  ]);

  runUv(['run', '--project', pluginRoot, '--frozen', ...args], { cwd: root, capture: true });
  await access(path.join(root, 'src', '__pycache__'));
  await access(path.join(root, 'tests', '__pycache__'));
  await assert.rejects(
    access(path.join(root, 'tests', 'fixtures', 'pdf-worker-failures', '__pycache__')),
  );
});

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
  assert.equal(binaryPaths.length, 27);
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
