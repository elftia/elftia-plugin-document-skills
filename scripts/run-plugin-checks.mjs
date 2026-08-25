import { pluginRoot } from './paths.mjs';
import { pythonCompileallArgs, runNpm, runUv } from './process.mjs';

runNpm(['ci', '--omit=dev', '--ignore-scripts'], { cwd: pluginRoot });
runUv(['sync', '--project', pluginRoot, '--frozen'], { cwd: pluginRoot });
runUv(['run', '--project', pluginRoot, '--frozen', 'python', '-m', 'pytest'], {
  cwd: pluginRoot,
});
runUv(
  ['run', '--project', pluginRoot, '--frozen', ...pythonCompileallArgs()],
  { cwd: pluginRoot },
);
runUv(
  ['run', '--project', pluginRoot, '--frozen', 'python', '-m', 'tools.audit', '--project-root', '.'],
  { cwd: pluginRoot },
);
