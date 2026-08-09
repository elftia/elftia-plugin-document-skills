import { validateArtifact } from './artifact.mjs';

const { artifact } = await validateArtifact();
process.stdout.write(`${JSON.stringify({
  fileCount: artifact.fileCount,
  inventorySha256: artifact.sha256,
})}\n`);

