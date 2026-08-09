import { copyFile, lstat, mkdir, realpath, rename, rm } from 'node:fs/promises';
import path from 'node:path';

import { inventoriesEqual, inventoryRegularTree, inventorySelectedPaths } from './inventory.mjs';
import { artifactRoot, distRoot, pluginRoot, repositoryRoot } from './paths.mjs';
import { runUv } from './process.mjs';

const STAGE_NAME = '.document-skills-stage';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function removeOwnedDist() {
  assert(path.dirname(distRoot) === repositoryRoot, 'dist root is not repository-owned');
  try {
    const stat = await lstat(distRoot);
    if (stat.isSymbolicLink() || !stat.isDirectory()) {
      throw new Error(`refusing to remove non-directory dist root: ${distRoot}`);
    }
    const realRepository = await realpath(repositoryRoot);
    const realDist = await realpath(distRoot);
    assert(path.dirname(realDist) === realRepository, 'dist root escaped repository parent');
    await rm(distRoot, { recursive: true });
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
}

export function releasePaths() {
  const code = [
    'import json',
    'from pathlib import Path',
    'from tools.release_inventory import release_inventory',
    'print(json.dumps(release_inventory(Path.cwd())))',
  ].join('; ');
  const stdout = runUv(
    ['run', '--project', pluginRoot, '--frozen', 'python', '-c', code],
    { cwd: pluginRoot, capture: true },
  );
  const paths = JSON.parse(stdout);
  if (!Array.isArray(paths) || paths.some((item) => typeof item !== 'string')) {
    throw new Error('plugin release inventory did not return a string array');
  }
  return paths;
}

async function copyInventory(paths, stage) {
  for (const relative of paths) {
    const source = path.resolve(pluginRoot, ...relative.split('/'));
    const destination = path.resolve(stage, ...relative.split('/'));
    const relativeDestination = path.relative(stage, destination);
    assert(
      relativeDestination !== '..' &&
        !relativeDestination.startsWith(`..${path.sep}`) &&
        !path.isAbsolute(relativeDestination),
      `artifact destination escapes stage: ${relative}`,
    );
    await mkdir(path.dirname(destination), { recursive: true });
    await copyFile(source, destination);
  }
}

export async function validateArtifact() {
  const paths = releasePaths();
  const source = await inventorySelectedPaths(pluginRoot, paths);
  const artifact = await inventoryRegularTree(artifactRoot);
  assert(inventoriesEqual(source, artifact), 'artifact inventory differs from plugin release input');
  return { source, artifact };
}

export async function buildArtifact() {
  const paths = releasePaths();
  const source = await inventorySelectedPaths(pluginRoot, paths);
  await removeOwnedDist();
  await mkdir(distRoot);
  const stage = path.join(distRoot, STAGE_NAME);
  await mkdir(stage);
  await copyInventory(paths, stage);
  const staged = await inventoryRegularTree(stage);
  assert(inventoriesEqual(source, staged), 'staged artifact inventory differs from release input');
  await rename(stage, artifactRoot);
  const result = await validateArtifact();
  return result.artifact;
}

