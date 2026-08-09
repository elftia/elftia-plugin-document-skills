import { buildArtifact, releasePaths } from './artifact.mjs';
import { assertReleaseCheckoutPolicy } from './checkout-policy.mjs';
import { assertInventoriesEqual } from './inventory.mjs';

assertReleaseCheckoutPolicy(releasePaths());
const first = await buildArtifact();
const second = await buildArtifact();
assertInventoriesEqual(first, second, 'repeated artifact builds produced different inventories');
process.stdout.write(`reproducible document-skills artifact ${second.sha256}\n`);
