import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { pluginRoot } from './paths.mjs';
import { runNpm, runUv } from './process.mjs';

runNpm(['ci', '--omit=dev', '--ignore-scripts'], { cwd: pluginRoot });
runUv(['sync', '--project', pluginRoot, '--frozen'], { cwd: pluginRoot });
runUv(['run', '--project', pluginRoot, '--frozen', 'python', '-m', 'pytest'], {
  cwd: pluginRoot,
});
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
