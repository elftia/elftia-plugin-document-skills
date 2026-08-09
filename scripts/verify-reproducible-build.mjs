import { buildArtifact } from './artifact.mjs';
import { inventoriesEqual } from './inventory.mjs';

const first = await buildArtifact();
const second = await buildArtifact();
if (!inventoriesEqual(first, second)) {
  throw new Error('repeated artifact builds produced different inventories');
}
process.stdout.write(`reproducible document-skills artifact ${second.sha256}\n`);

