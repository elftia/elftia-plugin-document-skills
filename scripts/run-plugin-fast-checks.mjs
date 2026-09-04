import { pluginRoot } from './paths.mjs';
import { resolvePytestWorkers } from './lib/pytest.mjs';
import { runUv } from './process.mjs';

const pytestArgs = [
  'run',
  '--project',
  pluginRoot,
  '--frozen',
  'python',
  '-m',
  'pytest',
  '-m',
  'not slow',
];
if (process.env.DS_PYTEST_SERIAL !== '1') {
  pytestArgs.push(
    '-n',
    resolvePytestWorkers(process.env.DS_PYTEST_WORKERS),
    '--dist',
    'loadscope',
  );
}
runUv(pytestArgs, { cwd: pluginRoot });
