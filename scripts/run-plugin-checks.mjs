import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { pluginRoot } from './paths.mjs';
import { runNpm, runUv } from './process.mjs';

runNpm(['ci', '--omit=dev', '--ignore-scripts'], { cwd: pluginRoot });
runUv(['sync', '--project', pluginRoot, '--frozen'], { cwd: pluginRoot });
// Serial execution of this suite costs ~2h47m on the packaging machine;
// -n auto with loadscope distribution runs whole test modules per worker, so
// provider modules that share on-disk state (the dotnet helper build, the
// LibreOffice detector) stay serial within their module while the other
// ~190 modules parallelize. Set DS_PYTEST_SERIAL=1 to fall back.
const pytestArgs = ['run', '--project', pluginRoot, '--frozen', 'python', '-m', 'pytest'];
if (process.env.DS_PYTEST_SERIAL !== '1') pytestArgs.push('-n', 'auto', '--dist', 'loadscope');
runUv(pytestArgs, {
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
