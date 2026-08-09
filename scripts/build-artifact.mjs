import { buildArtifact } from './artifact.mjs';

const inventory = await buildArtifact();
process.stdout.write(`${JSON.stringify({
  fileCount: inventory.fileCount,
  inventorySha256: inventory.sha256,
})}\n`);

