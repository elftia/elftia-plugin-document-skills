import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { pluginRoot } from './paths.mjs';
import { resolvePytestWorkers } from './lib/pytest.mjs';
import { runNpm, runUv } from './process.mjs';

runNpm(['ci', '--omit=dev', '--ignore-scripts'], { cwd: pluginRoot });
runUv(['sync', '--project', pluginRoot, '--frozen'], { cwd: pluginRoot });
// Serial execution of this suite costs ~2h47m on the packaging machine, so
// the gate runs in two phases:
//   1. everything except `slow`, parallel (`-n 4 --dist loadscope` by
//      default, whole test modules per worker; DS_PYTEST_WORKERS=N
//      overrides the worker count);
//   2. the `slow` tier (real external providers: the dotnet helper build,
//      LibreOffice, PDF rendering) SERIALLY — the dotnet helper is a shared
//      on-disk build target that multiple modules touch, and building it on
//      parallel workers deadlocks/timeouts (measured: helper build stall at
//      99% with a dotnet.exe wedged; cascade of DS_PROCESS_TIMEOUT across
//      xlsx consumer tests).
// Set DS_PYTEST_SERIAL=1 to run everything in one serial process instead.
const pytestBase = ['run', '--project', pluginRoot, '--frozen', 'python', '-m', 'pytest'];
if (process.env.DS_PYTEST_SERIAL === '1') {
  runUv(pytestBase, { cwd: pluginRoot });
} else {
  runUv(
    [
      ...pytestBase,
      '-n',
      resolvePytestWorkers(process.env.DS_PYTEST_WORKERS),
      '--dist',
      'loadscope',
      '-m',
      'not slow',
    ],
    { cwd: pluginRoot },
  );
  runUv([...pytestBase, '-m', 'slow'], { cwd: pluginRoot });
}
const bytecodeRoot = mkdtempSync(join(tmpdir(), 'elftia-document-skills-bytecode-'));
try {
  runUv(
    [
      'run',
      '--project',
      pluginRoot,
      '--frozen',
      'python',
      '-X',
      `pycache_prefix=${bytecodeRoot}`,
      '-m',
      'compileall',
      '-q',
      'src',
      'tools',
      'tests',
    ],
    { cwd: pluginRoot },
  );
} finally {
  rmSync(bytecodeRoot, { recursive: true, force: true });
}
runUv(
  ['run', '--project', pluginRoot, '--frozen', 'python', '-m', 'tools.audit', '--project-root', '.'],
  { cwd: pluginRoot },
);
