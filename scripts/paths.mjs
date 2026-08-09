import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));

export const repositoryRoot = path.resolve(scriptsDir, '..');
export const pluginRoot = path.join(repositoryRoot, 'plugin');
export const distRoot = path.join(repositoryRoot, 'dist');
export const artifactRoot = path.join(distRoot, 'document-skills');

