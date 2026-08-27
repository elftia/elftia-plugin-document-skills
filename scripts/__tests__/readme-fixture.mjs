import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { REQUIRED_READMES, verifyReadmes } from '../verify-readmes.mjs';

export const OPERATIONS = {
  docx: 'docx.read',
  pdf: 'pdf.read',
  pptx: 'pptx.read',
  xlsx: 'xlsx.read',
};

function fixtureReadme(relative) {
  const format = Object.keys(OPERATIONS).find((candidate) =>
    relative.includes(`/formats/${candidate}/`),
  );
  const sections = [
    '# Fixture module',
    '',
    '## Purpose',
    '',
    'Fixture purpose.',
    '',
    '## Ownership and boundaries',
    '',
    'Fixture boundaries.',
    '',
    '## Entry points',
    '',
    relative === 'README.md'
      ? 'Run `npm run verify:docs`, `npm run verify`, and `npm run verify:repro`.'
      : 'Fixture entry point.',
  ];
  if (format) {
    sections.push(
      '',
      '## Operations and availability',
      '',
      `| Operation | Availability |\n| --- | --- |\n| \`${OPERATIONS[format]}\` | Core |`,
    );
  }
  sections.push(
    '',
    '## Safety and failure semantics',
    '',
    'Fixture failure boundary.',
    '',
    '## Verification',
    '',
    'Fixture verification.',
    '',
    '## Related documentation',
    '',
    'No related fixture documents.',
    '',
  );
  return sections.join('\n');
}

export async function writeFixtureFile(root, relative, contents) {
  const absolute = path.join(root, ...relative.split('/'));
  await mkdir(path.dirname(absolute), { recursive: true });
  await writeFile(absolute, contents);
  return absolute;
}

async function createFixture(providerSource) {
  const root = await mkdtemp(path.join(tmpdir(), 'document-readmes-'));
  await Promise.all(
    REQUIRED_READMES.map((relative) => writeFixtureFile(root, relative, fixtureReadme(relative))),
  );
  await writeFixtureFile(
    root,
    'package.json',
    `${JSON.stringify({ scripts: { verify: 'true', 'verify:docs': 'true', 'verify:repro': 'true' } })}\n`,
  );
  await writeFixtureFile(
    root,
    'plugin/src/document_skills_core/providers/defaults.py',
    providerSource ??
      [
        'CAPABILITIES = [',
        ...Object.values(OPERATIONS).map((operation) => `    Capability("${operation}", "core"),`),
        ']',
        '',
      ].join('\n'),
  );
  return root;
}

export async function withFixture(run, providerSource) {
  const root = await createFixture(providerSource);
  try {
    await run(root);
  } finally {
    await rm(root, { force: true, recursive: true });
  }
}

export async function appendUtf8(root, relative, addition) {
  const absolute = path.join(root, ...relative.split('/'));
  const current = await readFile(absolute, 'utf8');
  await writeFile(absolute, `${current}${addition}`, 'utf8');
}

export async function assertVerificationFailure(root, detail) {
  await assert.rejects(
    () => verifyReadmes(root),
    (error) => {
      assert.match(error.message, /^README verification failed:/);
      assert.ok(error.message.includes(detail), `${error.message} does not include ${detail}`);
      return true;
    },
  );
}
