import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { buildArtifact } from './artifact.mjs';
import { artifactRoot, repositoryRoot } from './paths.mjs';
import { runUv } from './process.mjs';

const temporaryRoot = mkdtempSync(path.join(tmpdir(), 'elftia-xlsx-dist-e2e-'));
try {
  Object.assign(process.env, {
    DOTNET_ADD_GLOBAL_TOOLS_TO_PATH: '0',
    PYTHONPYCACHEPREFIX: path.join(temporaryRoot, 'pycache'),
    UV_PROJECT_ENVIRONMENT: path.join(temporaryRoot, 'venv'),
  });
  const artifact = await buildArtifact();
  const environment = {
    ...process.env,
    DOCUMENT_SKILLS_DIST_BUILD_SHA256: artifact.sha256,
    DOCUMENT_SKILLS_DIST_ROOT: artifactRoot,
  };
  runUv(['sync', '--project', artifactRoot, '--frozen', '--group', 'dev'], {
    cwd: artifactRoot,
    env: environment,
  });
  runUv(
    [
      'run',
      '--project',
      artifactRoot,
      '--frozen',
      'python',
      '-m',
      'pytest',
      '-q',
      path.join(repositoryRoot, 'e2e', 'xlsx_dist', 'test_xlsx_dist_e2e.py'),
      '--basetemp',
      path.join(temporaryRoot, 'pytest'),
    ],
    { cwd: repositoryRoot, env: environment },
  );
  process.stdout.write(`xlsx dist e2e passed for artifact ${artifact.sha256}\n`);
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
}
