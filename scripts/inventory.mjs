import { createHash } from 'node:crypto';
import { lstat, readFile, readdir, realpath } from 'node:fs/promises';
import path from 'node:path';

export function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

export function normalizeRelativePath(value, label = 'path') {
  if (typeof value !== 'string' || value.length === 0 || value.includes('\0')) {
    throw new Error(`${label} must be a non-empty string without NUL bytes`);
  }
  if (path.isAbsolute(value) || /^[a-zA-Z]:[\\/]/.test(value)) {
    throw new Error(`${label} must be relative: ${value}`);
  }
  const normalized = value.replaceAll('\\', '/').replace(/^\.\//, '');
  const parts = normalized.split('/');
  if (parts.some((part) => part === '' || part === '.' || part === '..')) {
    throw new Error(`${label} escapes or is not normalized: ${value}`);
  }
  return parts.join('/');
}

export function isContainedPath(root, candidate) {
  const relative = path.relative(root, candidate);
  return (
    relative === '' ||
    (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative))
  );
}

function bytewisePathCompare(left, right) {
  return Buffer.compare(Buffer.from(left.path, 'utf8'), Buffer.from(right.path, 'utf8'));
}

function inventoryDigest(entries) {
  const lines = entries.map((entry) => `${entry.path}\t${entry.sha256}\n`).join('');
  return sha256(Buffer.from(lines, 'utf8'));
}

function assertInventoryPaths(entries) {
  const exact = new Set();
  const folded = new Map();
  for (const entry of entries) {
    const normalized = normalizeRelativePath(entry.path, 'inventory path');
    if (exact.has(normalized)) throw new Error(`duplicate inventory path: ${normalized}`);
    exact.add(normalized);
    const key = normalized.toLocaleLowerCase('en-US');
    const prior = folded.get(key);
    if (prior && prior !== normalized) {
      throw new Error(`case-fold-colliding inventory paths: ${prior} and ${normalized}`);
    }
    folded.set(key, normalized);
  }
}

async function assertOrdinaryDirectory(directory, label) {
  const stat = await lstat(directory);
  if (stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new Error(`${label} must be an ordinary directory: ${directory}`);
  }
  return realpath(directory);
}

async function regularFileEntry(root, realRoot, rawPath) {
  const relative = normalizeRelativePath(rawPath, 'selected path');
  const absolute = path.resolve(root, ...relative.split('/'));
  if (!isContainedPath(root, absolute)) throw new Error(`selected path escapes root: ${relative}`);
  const stat = await lstat(absolute);
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw new Error(`selected path must be an ordinary file: ${relative}`);
  }
  const resolved = await realpath(absolute);
  if (!isContainedPath(realRoot, resolved)) throw new Error(`selected path escapes root: ${relative}`);
  const bytes = await readFile(absolute);
  return { path: relative, length: bytes.length, sha256: sha256(bytes) };
}

function completedInventory(root, realRoot, entries) {
  entries.sort(bytewisePathCompare);
  assertInventoryPaths(entries);
  return {
    root,
    realRoot,
    fileCount: entries.length,
    sha256: inventoryDigest(entries),
    entries,
  };
}

export async function inventorySelectedPaths(root, relativePaths) {
  const absoluteRoot = path.resolve(root);
  const realRoot = await assertOrdinaryDirectory(absoluteRoot, 'selected tree root');
  const entries = [];
  for (const relative of relativePaths) {
    entries.push(await regularFileEntry(absoluteRoot, realRoot, relative));
  }
  return completedInventory(absoluteRoot, realRoot, entries);
}

export async function inventoryRegularTree(root) {
  const absoluteRoot = path.resolve(root);
  const realRoot = await assertOrdinaryDirectory(absoluteRoot, 'tree root');
  const entries = [];
  async function visit(directory) {
    for (const dirent of await readdir(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, dirent.name);
      const relative = normalizeRelativePath(path.relative(absoluteRoot, absolute), 'tree path');
      const stat = await lstat(absolute);
      if (stat.isSymbolicLink()) throw new Error(`symlink or junction is forbidden: ${relative}`);
      const resolved = await realpath(absolute);
      if (!isContainedPath(realRoot, resolved)) throw new Error(`reparse escape: ${relative}`);
      if (stat.isDirectory()) await visit(absolute);
      else if (stat.isFile()) entries.push(await regularFileEntry(absoluteRoot, realRoot, relative));
      else throw new Error(`special file is forbidden: ${relative}`);
    }
  }
  await visit(absoluteRoot);
  return completedInventory(absoluteRoot, realRoot, entries);
}

export function inventoriesEqual(left, right) {
  if (left.fileCount !== right.fileCount || left.sha256 !== right.sha256) return false;
  return left.entries.every((entry, index) => {
    const other = right.entries[index];
    return (
      other &&
      entry.path === other.path &&
      entry.length === other.length &&
      entry.sha256 === other.sha256
    );
  });
}

