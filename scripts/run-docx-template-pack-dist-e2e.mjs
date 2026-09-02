import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { buildArtifact } from './artifact.mjs';
import { artifactRoot, repositoryRoot } from './paths.mjs';
import { runNpm, runUv } from './process.mjs';

const temporaryRoot = mkdtempSync(path.join(tmpdir(), 'elftia-docx-template-pack-dist-e2e-'));
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
    PYTHONPATH: path.join(artifactRoot, 'src'),
  };
  runNpm(['ci', '--omit=dev', '--ignore-scripts'], {
    cwd: artifactRoot,
    env: environment,
  });
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
      path.join(
        repositoryRoot,
        'e2e',
        'docx_template_pack_dist',
        'test_docx_template_pack_dist_e2e.py',
      ),
      '--basetemp',
      path.join(temporaryRoot, 'pytest'),
    ],
    { cwd: artifactRoot, env: environment },
  );
  process.stdout.write(`DOCX template-pack dist e2e passed for artifact ${artifact.sha256}\n`);
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
  // `npm ci` installs the artifact's runtime dependencies in place, which
  // dirties the staged artifact and would make a subsequent
  // `validate:artifact` fail on the node_modules it created. Restore the
  // staged artifact so the e2e leaves the dist tree exactly as built.
  rmSync(path.join(artifactRoot, 'node_modules'), { recursive: true, force: true });
}
