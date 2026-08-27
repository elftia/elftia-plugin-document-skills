import assert from 'node:assert/strict';
import { readFile, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { analyzeMarkdown } from '../lib/markdown-links.mjs';
import {
  collectRegisteredOperations,
  extractLocalMarkdownTargets,
  REQUIRED_READMES,
  verifyReadmes,
} from '../verify-readmes.mjs';
import {
  appendUtf8,
  assertVerificationFailure,
  OPERATIONS,
  withFixture,
  writeFixtureFile,
} from './readme-fixture.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

test('the required module inventory stays explicit and unique', () => {
  assert.equal(new Set(REQUIRED_READMES).size, REQUIRED_READMES.length);
  assert.ok(REQUIRED_READMES.includes('README.md'));
  assert.ok(REQUIRED_READMES.includes('plugin/src/document_skills_core/formats/pptx/README.md'));
});

test('local Markdown targets support references and balanced parentheses', () => {
  const targets = extractLocalMarkdownTargets(
    '[local](guide_(draft).md#start) [guide][g] [root](/README.md)\n' +
      '[anchor](#here) [web](https://example.com)\n\n[g]: ./reference_(guide).md',
  );
  assert.deepEqual(targets, [
    'guide_(draft).md#start',
    './reference_(guide).md',
    '/README.md',
  ]);
});

test('large unmatched bracket runs stay inert under the parser-native reference probe', () => {
  const analysis = analyzeMarkdown('['.repeat(32_768));
  assert.deepEqual(analysis.links, []);
  assert.deepEqual(analysis.codeSpans, []);
});

test('defined references and literal shortcut brackets remain valid Markdown', async () => {
  await withFixture(async (root) => {
    await appendUtf8(
      root,
      'README.md',
      [
        '',
        '[Guide][g]',
        '[Guide][]',
        '![Diagram][diagram]',
        'Use [brackets] literally.',
        '![not-an-image]',
        '',
        '[g]: README.md',
        '[Guide]: README.md',
        '[diagram]: README.md',
        '',
      ].join('\n'),
    );
    await verifyReadmes(root);
  });
});

test('registered operations are discovered across all four formats', async () => {
  const operations = await collectRegisteredOperations(repoRoot);
  for (const operation of Object.values(OPERATIONS)) {
    assert.ok(operations.has(operation), `missing ${operation}`);
  }
});

test('Capability scanning ignores comments and accepts keyword strings', async () => {
  const provider = [
    '# Capability("docx.comment-only", "core")',
    '"""Capability("xlsx.docstring-only", "core")"""',
    'CAPABILITIES = [',
    ...Object.values(OPERATIONS).map(
      (operation) => `    Capability(operation="${operation}", fidelity="core"),`,
    ),
    ']',
    '',
  ].join('\n');
  await withFixture(async (root) => {
    const operations = await collectRegisteredOperations(root);
    assert.deepEqual([...operations].sort(), Object.values(OPERATIONS).sort());
  }, provider);
});

test('Capability scanning fails closed for unresolved operations', async () => {
  const provider = [
    'DOCX_READ = "docx.read"',
    'CAPABILITIES = [',
    '    Capability(DOCX_READ, "core"),',
    '    Capability("xlsx.read", "core"),',
    '    Capability("pptx.read", "core"),',
    '    Capability("pdf.read", "core"),',
    ']',
    '',
  ].join('\n');
  await withFixture(async (root) => {
    const relative = path.join(
      'plugin',
      'src',
      'document_skills_core',
      'providers',
      'defaults.py:3 has an unresolved Capability operation',
    );
    await assertVerificationFailure(root, relative);
  }, provider);
});

test('repository README hierarchy and executable references agree', async () => {
  const result = await verifyReadmes(repoRoot);
  assert.equal(result.requiredReadmeCount, REQUIRED_READMES.length);
  assert.ok(result.operationCount > 0);
  assert.ok(result.localLinkCount > 0);
});

test('missing required README reports the exact module', async () => {
  await withFixture(async (root) => {
    await unlink(path.join(root, 'e2e', 'README.md'));
    await assertVerificationFailure(root, 'required module document is missing: e2e/README.md');
  });
});

test('missing required heading reports the exact module and heading', async () => {
  await withFixture(async (root) => {
    const relative = 'plugin/tools/README.md';
    const absolute = path.join(root, ...relative.split('/'));
    const current = await readFile(absolute, 'utf8');
    await writeFile(absolute, current.replace('## Purpose', '## Intent'), 'utf8');
    await assertVerificationFailure(root, `${relative} is missing heading "## Purpose"`);
  });
});

test('UTF-8 BOM and invalid UTF-8 report the exact file', async (context) => {
  await context.test('BOM', async () => {
    await withFixture(async (root) => {
      const absolute = path.join(root, 'README.md');
      const current = await readFile(absolute);
      await writeFile(absolute, Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), current]));
      await assertVerificationFailure(root, `${absolute} has a UTF-8 BOM`);
    });
  });
  await context.test('invalid sequence', async () => {
    await withFixture(async (root) => {
      const absolute = path.join(root, 'README.md');
      await writeFile(absolute, Buffer.from([0xff]));
      await assertVerificationFailure(root, `${absolute} is not strict UTF-8`);
    });
  });
});

test('reference-style missing target reports the balanced target', async () => {
  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\n[guide][g]\n\n[g]: ./missing_(guide).md\n');
    await assertVerificationFailure(
      root,
      'README.md has a missing local target: ./missing_(guide).md',
    );
  });
});

test('stale root command reports the exact package script', async () => {
  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\nRun `npm run verify:future`.\n');
    await assertVerificationFailure(
      root,
      'README.md documents missing package script: npm run verify:future',
    );
  });
});

test('registered operations must appear in their operations section', async () => {
  await withFixture(async (root) => {
    const relative = 'plugin/src/document_skills_core/formats/docx/README.md';
    const absolute = path.join(root, ...relative.split('/'));
    const current = await readFile(absolute, 'utf8');
    const withoutOperation = current
      .replace('`docx.read`', 'No operation')
      .replace('## Safety and failure semantics', '<!-- `docx.read` -->\n\n## Safety and failure semantics');
    await writeFile(absolute, `${withoutOperation}\nOutside: \`docx.read\`.\n`);
    await assertVerificationFailure(root, `${relative} does not document registered operation docx.read`);
  });
});

test('suffix-shaped unregistered operation fails while linked files remain valid', async () => {
  await withFixture(async (root) => {
    await writeFixtureFile(root, 'plugin/consumer_validation/docx.py', '# fixture\n');
    await appendUtf8(
      root,
      'plugin/consumer_validation/README.md',
      '\n[`docx.py`](docx.py) is an implementation file.\n',
    );
    await verifyReadmes(root);
    await appendUtf8(
      root,
      'plugin/src/document_skills_core/formats/docx/README.md',
      '\nUnsupported claim: `docx.future.json`.\n',
    );
    await assertVerificationFailure(root, 'documents unregistered operation docx.future.json');
  });
});
