import { pluginRoot } from './paths.mjs';
import { runNpm, runUv } from './process.mjs';

runNpm(['ci', '--omit=dev', '--ignore-scripts'], { cwd: pluginRoot });
runUv(['sync', '--project', pluginRoot, '--frozen'], { cwd: pluginRoot });
runUv(['run', '--project', pluginRoot, '--frozen', 'python', '-m', 'pytest'], {
  cwd: pluginRoot,
});
runUv(
  ['run', '--project', pluginRoot, '--frozen', 'python', '-m', 'compileall', '-q', 'src', 'tools', 'tests'],
  { cwd: pluginRoot },
);
runUv(
  ['run', '--project', pluginRoot, '--frozen', 'python', '-m', 'tools.audit', '--project-root', '.'],
  { cwd: pluginRoot },
);

