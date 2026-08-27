import { readdir, readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { analyzeMarkdown, isLinkedFileReference } from './lib/markdown-links.mjs';
import {
  extractCapabilityOperations,
  isPublicOperation,
} from './lib/python-capabilities.mjs';

export { extractLocalMarkdownTargets } from './lib/markdown-links.mjs';
export { extractCapabilityOperations } from './lib/python-capabilities.mjs';

export const REQUIRED_READMES = [
  'README.md',
  'e2e/README.md',
  'plugin/README.md',
  'plugin/consumer_validation/README.md',
  'plugin/provenance/README.md',
  'plugin/runtime/node/README.md',
  'plugin/schemas/README.md',
  'plugin/skills/README.md',
  'plugin/src/document_skills_core/README.md',
  'plugin/src/document_skills_core/formats/docx/README.md',
  'plugin/src/document_skills_core/formats/pdf/README.md',
  'plugin/src/document_skills_core/formats/pptx/README.md',
  'plugin/src/document_skills_core/formats/xlsx/README.md',
  'plugin/src/document_skills_core/providers/README.md',
  'plugin/tests/README.md',
  'plugin/tools/README.md',
  'scripts/README.md',
];

const COMMON_HEADINGS = [
  '## Purpose',
  '## Ownership and boundaries',
  '## Entry points',
  '## Safety and failure semantics',
  '## Verification',
  '## Related documentation',
];

const FORMAT_READMES = new Map(
  ['docx', 'xlsx', 'pptx', 'pdf'].map((format) => [
    format,
    `plugin/src/document_skills_core/formats/${format}/README.md`,
  ]),
);

const IGNORED_DIRECTORIES = new Set([
  '.document-skills-tmp',
  '.git',
  '.pytest_cache',
  '.rasen',
  '.ruff_cache',
  '.venv',
  '__pycache__',
  'dist',
  'node_modules',
  'release',
]);

const UTF8_DECODER = new TextDecoder('utf-8', { fatal: true });

function fail(message) {
  throw new Error(`README verification failed: ${message}`);
}

async function listFiles(root, predicate) {
  const files = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (entry.isDirectory() && IGNORED_DIRECTORIES.has(entry.name)) continue;
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) await visit(absolute);
      else if (entry.isFile() && predicate(absolute)) files.push(absolute);
    }
  }
  await visit(root);
  return files.sort((left, right) => left.localeCompare(right, 'en'));
}

export async function readStrictUtf8(file) {
  const bytes = await readFile(file);
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    fail(`${file} has a UTF-8 BOM`);
  }
  try {
    return UTF8_DECODER.decode(bytes);
  } catch {
    fail(`${file} is not strict UTF-8`);
  }
}

function requireHeading(relative, analysis, heading) {
  const expected = heading.replace(/^## /, '');
  const present = analysis.headings.some(
    (candidate) => candidate.topLevel && candidate.level === 2 && candidate.text === expected,
  );
  if (!present) {
    fail(`${relative} is missing heading "${heading}"`);
  }
}

function resolveLocalTarget(repoRoot, readme, rawTarget) {
  const withoutFragment = rawTarget.split('#', 1)[0].split('?', 1)[0];
  let decoded;
  try {
    decoded = decodeURIComponent(withoutFragment).replace(
      /\\([!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])/g,
      '$1',
    );
  } catch {
    fail(`${path.relative(repoRoot, readme)} has invalid URL encoding in ${rawTarget}`);
  }
  const candidate = decoded.startsWith('/')
    ? path.resolve(repoRoot, decoded.slice(1))
    : path.resolve(path.dirname(readme), decoded);
  const relative = path.relative(repoRoot, candidate);
  if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    fail(`${path.relative(repoRoot, readme)} link escapes the repository: ${rawTarget}`);
  }
  return candidate;
}

async function verifyLocalLinks(repoRoot, analyses) {
  let count = 0;
  for (const [readme, analysis] of analyses) {
    const relative = path.relative(repoRoot, readme);
    for (const link of analysis.links) {
      if (link.unresolvedReference) {
        fail(`${relative} has an undefined reference link: ${link.unresolvedReference}`);
      }
      const { target } = link;
      if (!target || target.startsWith('#')) continue;
      if (target.startsWith('//') || /^[a-z][a-z0-9+.-]*:/i.test(target)) continue;
      const candidate = resolveLocalTarget(repoRoot, readme, target);
      try {
        await stat(candidate);
      } catch {
        fail(`${relative} has a missing local target: ${target}`);
      }
      count += 1;
    }
  }
  return count;
}

export async function collectRegisteredOperations(repoRoot) {
  const providerRoot = path.join(repoRoot, 'plugin', 'src', 'document_skills_core', 'providers');
  const files = await listFiles(providerRoot, (file) => file.endsWith('.py'));
  const operations = new Set();
  for (const file of files) {
    const source = await readStrictUtf8(file);
    const relative = path.relative(repoRoot, file);
    try {
      for (const operation of extractCapabilityOperations(source, relative)) operations.add(operation);
    } catch (error) {
      fail(error instanceof Error ? error.message : String(error));
    }
  }
  for (const format of FORMAT_READMES.keys()) {
    if (![...operations].some((operation) => operation.startsWith(`${format}.`))) {
      fail(`no registered ${format.toUpperCase()} operations were discovered`);
    }
  }
  return operations;
}

function verifyRootCommands(packageJson, rootAnalysis) {
  const commands = new Set(
    [...rootAnalysis.renderedText.matchAll(/\bnpm run ([a-zA-Z0-9:_-]+)/g)].map(
      (match) => match[1],
    ),
  );
  for (const required of ['verify:docs', 'verify', 'verify:repro']) {
    if (!commands.has(required)) fail(`README.md does not document npm run ${required}`);
  }
  for (const command of commands) {
    if (!Object.hasOwn(packageJson.scripts ?? {}, command)) {
      fail(`README.md documents missing package script: npm run ${command}`);
    }
  }
  return commands.size;
}

function verifyOperationCoverage(repoRoot, analyses, registeredOperations) {
  for (const [format, relative] of FORMAT_READMES) {
    const analysis = analyses.get(path.join(repoRoot, ...relative.split('/')));
    requireHeading(relative, analysis, '## Operations and availability');
    const documentedOperations = new Set(
      analysis.codeSpans
        .filter((span) => span.section === 'Operations and availability')
        .map((span) => span.text.trim())
        .filter((operation) => isPublicOperation(operation)),
    );
    for (const operation of registeredOperations) {
      if (operation.startsWith(`${format}.`) && !documentedOperations.has(operation)) {
        fail(`${relative} does not document registered operation ${operation}`);
      }
    }
  }
  for (const [readme, analysis] of analyses) {
    for (const span of analysis.codeSpans) {
      const operation = span.text.trim();
      if (!/^(?:docx|xlsx|pptx|pdf)\./i.test(operation)) continue;
      if (isLinkedFileReference(span.linkTarget, operation)) continue;
      if (!isPublicOperation(operation)) {
        fail(`${path.relative(repoRoot, readme)} documents invalid operation ${operation}`);
      }
      if (!registeredOperations.has(operation)) {
        fail(`${path.relative(repoRoot, readme)} documents unregistered operation ${operation}`);
      }
    }
  }
}

export async function verifyReadmes(repoRoot) {
  const resolvedRoot = path.resolve(repoRoot);
  const allReadmePaths = await listFiles(resolvedRoot, (file) => path.basename(file) === 'README.md');
  const readmes = new Map();
  const analyses = new Map();
  for (const file of allReadmePaths) {
    const text = await readStrictUtf8(file);
    readmes.set(file, text);
    analyses.set(file, analyzeMarkdown(text));
  }

  for (const relative of REQUIRED_READMES) {
    const absolute = path.join(resolvedRoot, ...relative.split('/'));
    const analysis = analyses.get(absolute);
    if (analysis == null) fail(`required module document is missing: ${relative}`);
    for (const heading of COMMON_HEADINGS) requireHeading(relative, analysis, heading);
  }

  const packageJson = JSON.parse(await readStrictUtf8(path.join(resolvedRoot, 'package.json')));
  const packageCommandCount = verifyRootCommands(
    packageJson,
    analyses.get(path.join(resolvedRoot, 'README.md')),
  );
  const registeredOperations = await collectRegisteredOperations(resolvedRoot);
  const localLinkCount = await verifyLocalLinks(resolvedRoot, analyses);
  verifyOperationCoverage(resolvedRoot, analyses, registeredOperations);

  return {
    localLinkCount,
    operationCount: registeredOperations.size,
    packageCommandCount,
    readmeCount: readmes.size,
    requiredReadmeCount: REQUIRED_READMES.length,
  };
}

const scriptPath = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  const repoRoot = path.resolve(path.dirname(scriptPath), '..');
  const result = await verifyReadmes(repoRoot);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}
