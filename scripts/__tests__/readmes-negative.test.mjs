import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';

import { verifyReadmes } from '../verify-readmes.mjs';
import {
  appendUtf8,
  assertVerificationFailure,
  OPERATIONS,
  withFixture,
} from './readme-fixture.mjs';

function providerWithDocx(operation) {
  return [
    'CAPABILITIES = [',
    `    Capability("${operation}", "core"),`,
    ...Object.entries(OPERATIONS)
      .filter(([format]) => format !== 'docx')
      .map(([, value]) => `    Capability("${value}", "core"),`),
    ']',
    '',
  ].join('\n');
}

test('undefined full and collapsed reference links fail explicitly', async () => {
  for (const [link, reference] of [
    ['[Guide][missing-definition]', 'missing-definition'],
    ['[Guide][]', 'Guide'],
  ]) {
    await withFixture(async (root) => {
      await appendUtf8(root, 'README.md', `\n${link}\n`);
      await assertVerificationFailure(
        root,
        `README.md has an undefined reference link: ${reference}`,
      );
    });
  }
});

test('complex rendered reference labels cannot bypass undefined-reference checks', async () => {
  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\n[Guide `]`][missing-code-label]\n');
    await assertVerificationFailure(
      root,
      'README.md has an undefined reference link: missing-code-label',
    );
  });
});

test('literal verifier-like targets cannot activate hidden reference candidates', async () => {
  await withFixture(async (root) => {
    await appendUtf8(
      root,
      'README.md',
      [
        '',
        '[External](readme-verifier-undefined:0)',
        '`[Hidden][missing-inline-definition]`',
        '```markdown',
        '[Hidden][missing-fenced-definition]',
        '```',
        '',
      ].join('\n'),
    );
    await verifyReadmes(root);
  });
});

test('operation label with undefined reference reports the reference failure', async () => {
  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\n[`docx.future`][missing-definition]\n');
    await assertVerificationFailure(
      root,
      'README.md has an undefined reference link: missing-definition',
    );
  });
});

test('undefined full reference images fail explicitly', async () => {
  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\n![Diagram][missing-image-definition]\n');
    await assertVerificationFailure(
      root,
      'README.md has an undefined reference link: missing-image-definition',
    );
  });
});

test('literal code links and protocol-relative external links are ignored', async () => {
  await withFixture(async (root) => {
    await appendUtf8(
      root,
      'README.md',
      [
        '',
        '`[Inline](./missing-inline.md)`',
        '```markdown',
        '[Fenced](./missing-fenced.md)',
        '[Missing][definition]',
        '[definition]: ./missing-definition.md',
        '```',
        '~~~markdown',
        '[Tilde fenced](./missing-tilde.md)',
        '~~~',
        '[External](//example.com/guide)',
        '',
        '    [Indented](./missing-indented.md)',
        '    `docx.future`',
        '<!-- [Comment](./missing-comment.md) `docx.future` -->',
        '',
      ].join('\n'),
    );
    await verifyReadmes(root);
  });
});

test('fenced and HTML-comment pseudo operation sections cannot satisfy coverage', async () => {
  for (const pseudoSection of [
    ['```markdown', '## Operations and availability', '`docx.read`', '```'].join('\n'),
    '<!--\n## Operations and availability\n`docx.read`\n-->',
  ]) {
    await withFixture(async (root) => {
      const relative = 'plugin/src/document_skills_core/formats/docx/README.md';
      const absolute = path.join(root, ...relative.split('/'));
      const current = await readFile(absolute, 'utf8');
      const withoutSection = current.replace('## Operations and availability', '## Details');
      await writeFile(absolute, `${withoutSection}\n${pseudoSection}\n`, 'utf8');
      await assertVerificationFailure(
        root,
        `${relative} is missing heading "## Operations and availability"`,
      );
    });
  }
});

test('list-contained rendered links remain subject to local-target checks', async () => {
  await withFixture(async (root) => {
    await appendUtf8(
      root,
      'README.md',
      '\n- Nested documentation:\n\n    [Missing](./missing-list-target.md)\n',
    );
    await assertVerificationFailure(
      root,
      'README.md has a missing local target: ./missing-list-target.md',
    );
  });

  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\n- Nested claim:\n\n    `docx.future`\n');
    await assertVerificationFailure(
      root,
      'README.md documents unregistered operation docx.future',
    );
  });
});

test('blockquote code blocks do not create link or operation claims', async () => {
  await withFixture(async (root) => {
    await appendUtf8(
      root,
      'README.md',
      '\n>     [Literal](./missing-blockquote-target.md)\n>     `docx.future`\n',
    );
    await verifyReadmes(root);
  });
});

test('escaped HTML comment openers leave rendered links and operations visible', async () => {
  await withFixture(async (root) => {
    await appendUtf8(
      root,
      'README.md',
      '\n\\<!-- [Visible](./missing-escaped-comment.md) `docx.future` -->\n',
    );
    await assertVerificationFailure(
      root,
      'README.md has a missing local target: ./missing-escaped-comment.md',
    );
  });

  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\n\\<!-- `docx.future` -->\n');
    await assertVerificationFailure(
      root,
      'README.md documents unregistered operation docx.future',
    );
  });
});

test('Markdown link escaping follows odd and even backslash semantics', async () => {
  await withFixture(async (root) => {
    await appendUtf8(
      root,
      'README.md',
      [
        '',
        '\\[Odd](./missing-odd-target.md)',
        '\\\\[Even](./missing-even-target.md)',
        '',
      ].join('\n'),
    );
    await assertVerificationFailure(
      root,
      'README.md has a missing local target: ./missing-even-target.md',
    );
  });
});

test('external same-basename links do not exempt operation claims', async () => {
  for (const target of [
    'https://example.com/docx.future',
    '//example.com/docx.future',
  ]) {
    await withFixture(async (root) => {
      await appendUtf8(root, 'README.md', `\n[\`docx.future\`](${target})\n`);
      await assertVerificationFailure(root, 'documents unregistered operation docx.future');
    });
  }
});

test('repository-escaping link reports the exact target', async () => {
  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\n[Escape](../outside.md)\n');
    await assertVerificationFailure(
      root,
      'README.md link escapes the repository: ../outside.md',
    );
  });
});

test('invalid URL encoding reports the exact target', async () => {
  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\n[Bad encoding](./bad-%ZZ.md)\n');
    await assertVerificationFailure(
      root,
      'README.md has invalid URL encoding in ./bad-%ZZ.md',
    );
  });
});

test('missing required root command reports the exact command', async () => {
  await withFixture(async (root) => {
    const absolute = path.join(root, 'README.md');
    const current = await readFile(absolute, 'utf8');
    await writeFile(
      absolute,
      current.replace('`npm run verify:repro`', 'the reproducibility gate'),
      'utf8',
    );
    await assertVerificationFailure(root, 'README.md does not document npm run verify:repro');
  });
});

test('HTML comments cannot satisfy or invalidate root command documentation', async () => {
  await withFixture(async (root) => {
    const absolute = path.join(root, 'README.md');
    const current = await readFile(absolute, 'utf8');
    const withoutVisibleCommands = current.replace(
      'Run `npm run verify:docs`, `npm run verify`, and `npm run verify:repro`.',
      'Use the documented verification workflow.',
    );
    await writeFile(
      absolute,
      `${withoutVisibleCommands}\n<!-- npm run verify:docs; npm run verify; npm run verify:repro -->\n`,
      'utf8',
    );
    await assertVerificationFailure(root, 'README.md does not document npm run verify:docs');
  });

  await withFixture(async (root) => {
    await appendUtf8(root, 'README.md', '\n<!-- npm run verify:future -->\n');
    await verifyReadmes(root);
  });
});

test('malformed format-prefixed README operations fail the public grammar', async () => {
  for (const operation of [
    'docx.future_name',
    'docx.Future',
    'docx.future name',
    'docx..future',
    'docx.-future',
    'docx.future.',
    'docx.future-',
  ]) {
    await withFixture(async (root) => {
      await appendUtf8(
        root,
        'plugin/src/document_skills_core/formats/docx/README.md',
        `\nMalformed claim: \`${operation}\`.\n`,
      );
      await assertVerificationFailure(root, `documents invalid operation ${operation}`);
    });
  }
});

test('multi-backtick malformed operation claims cannot bypass validation', async () => {
  await withFixture(async (root) => {
    await appendUtf8(
      root,
      'plugin/src/document_skills_core/formats/docx/README.md',
      '\nMalformed claim: ``docx.future_name``.\n',
    );
    await assertVerificationFailure(root, 'documents invalid operation docx.future_name');
  });
});

test('malformed static Capability operations fail the public grammar', async () => {
  for (const operation of [
    'docx.future_name',
    'docx.Future',
    'docx.future name',
    'docx..future',
    'docx.-future',
    'docx.future.',
    'docx.future-',
  ]) {
    await withFixture(async (root) => {
      await assertVerificationFailure(root, `has an invalid Capability operation: ${operation}`);
    }, providerWithDocx(operation));
  }
});

test('no discovered document operations fails closed by format', async () => {
  const provider = 'CAPABILITIES = [Capability("libreoffice.convert-pdf", "enhanced")]\n';
  await withFixture(async (root) => {
    await assertVerificationFailure(root, 'no registered DOCX operations were discovered');
  }, provider);
});

test('valid hyphenated operation is accepted and section-bound', async () => {
  await withFixture(async (root) => {
    const relative = 'plugin/src/document_skills_core/formats/docx/README.md';
    const absolute = path.join(root, ...relative.split('/'));
    const current = await readFile(absolute, 'utf8');
    await writeFile(absolute, current.replace('`docx.read`', '`docx.future-name`'), 'utf8');
    await verifyReadmes(root);
  }, providerWithDocx('docx.future-name'));
});

test('operation length matches the public schema 128-character boundary', async () => {
  const validOperation = `docx.${'a'.repeat(123)}`;
  const invalidOperation = `docx.${'a'.repeat(124)}`;
  assert.equal(validOperation.length, 128);
  assert.equal(invalidOperation.length, 129);

  await withFixture(async (root) => {
    const relative = 'plugin/src/document_skills_core/formats/docx/README.md';
    const absolute = path.join(root, ...relative.split('/'));
    const current = await readFile(absolute, 'utf8');
    await writeFile(absolute, current.replace('`docx.read`', `\`${validOperation}\``), 'utf8');
    await verifyReadmes(root);
  }, providerWithDocx(validOperation));

  await withFixture(async (root) => {
    await appendUtf8(
      root,
      'plugin/src/document_skills_core/formats/docx/README.md',
      `\nToo long: \`${invalidOperation}\`.\n`,
    );
    await assertVerificationFailure(root, `documents invalid operation ${invalidOperation}`);
  });

  await withFixture(async (root) => {
    await assertVerificationFailure(
      root,
      `has an invalid Capability operation: ${invalidOperation}`,
    );
  }, providerWithDocx(invalidOperation));
});
