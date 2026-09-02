import { buildArtifact, validateArtifact } from './artifact.mjs';
import { runCommand } from './process.mjs';

runCommand(process.execPath, [
  '--test',
  'scripts/__tests__/readmes.test.mjs',
  'scripts/__tests__/readmes-negative.test.mjs',
  'scripts/__tests__/pytest-options.test.mjs',
]);
runCommand(process.execPath, ['scripts/verify-readmes.mjs']);
runCommand(process.execPath, ['--test', 'scripts/__tests__/reproducibility.test.mjs']);
runCommand(process.execPath, ['scripts/run-plugin-checks.mjs']);
const built = await buildArtifact();
const { artifact } = await validateArtifact();
if (built.sha256 !== artifact.sha256) throw new Error('post-build artifact validation drifted');
process.stdout.write(`verified document-skills artifact ${artifact.sha256}\n`);
