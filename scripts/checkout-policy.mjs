import { execFileSync } from 'node:child_process';
import path from 'node:path';

import { pluginRoot, repositoryRoot } from './paths.mjs';

export const REVIEWED_CRLF_RELEASE_PATHS = new Set([
  'src/document_skills_core/formats/pdf/create.py',
  'src/document_skills_core/formats/pdf/edit.py',
  'src/document_skills_core/formats/pdf/rewrite.py',
]);

const REVIEWED_BINARY_EXTENSIONS = new Set(['.docx', '.png', '.pptx']);

function parseCheckAttrOutput(stdout) {
  const fields = stdout.toString('utf8').split('\0');
  if (fields.at(-1) === '') fields.pop();
  if (fields.length % 3 !== 0) {
    throw new Error(`git check-attr returned ${fields.length} fields instead of path triples`);
  }
  const attributes = new Map();
  for (let index = 0; index < fields.length; index += 3) {
    const [rawPath, attribute, value] = fields.slice(index, index + 3);
    const relative = rawPath.replaceAll('\\', '/').replace(/^plugin\//, '');
    const entry = attributes.get(relative) ?? {};
    entry[attribute] = value;
    attributes.set(relative, entry);
  }
  return attributes;
}

export function isReviewedBinaryReleasePath(relative) {
  return REVIEWED_BINARY_EXTENSIONS.has(path.posix.extname(relative).toLowerCase());
}

export function inspectReleaseCheckoutPolicy(relativePaths) {
  const repositoryPaths = relativePaths.map((relative) => `plugin/${relative}`);
  const stdout = execFileSync('git', ['check-attr', '--stdin', '-z', 'text', 'eol'], {
    cwd: repositoryRoot,
    input: Buffer.from(`${repositoryPaths.join('\0')}\0`, 'utf8'),
    encoding: null,
  });
  const attributes = parseCheckAttrOutput(stdout);
  return relativePaths.map((relative) => {
    const effective = attributes.get(relative);
    if (!effective) throw new Error(`git check-attr omitted release path: ${relative}`);
    return {
      path: relative,
      sourcePath: path.join(pluginRoot, ...relative.split('/')),
      kind: isReviewedBinaryReleasePath(relative) ? 'binary' : 'text',
      text: effective.text,
      eol: effective.eol,
    };
  });
}

export function assertReleaseCheckoutPolicy(relativePaths) {
  const entries = inspectReleaseCheckoutPolicy(relativePaths);
  const present = new Set(entries.map((entry) => entry.path));
  for (const relative of REVIEWED_CRLF_RELEASE_PATHS) {
    if (!present.has(relative)) throw new Error(`reviewed CRLF path left release inventory: ${relative}`);
  }
  for (const entry of entries) {
    if (entry.kind === 'binary') {
      if (entry.text !== 'unset') {
        throw new Error(`binary release path must disable text transforms: ${entry.path}`);
      }
      continue;
    }
    const expectedText = REVIEWED_CRLF_RELEASE_PATHS.has(entry.path) ? 'set' : 'auto';
    const expectedEol = REVIEWED_CRLF_RELEASE_PATHS.has(entry.path) ? 'crlf' : 'lf';
    if (entry.text !== expectedText || entry.eol !== expectedEol) {
      throw new Error(
        `release checkout policy differs for ${entry.path}: ` +
          `text=${entry.text}, eol=${entry.eol}; expected text=${expectedText}, eol=${expectedEol}`,
      );
    }
  }
  return entries;
}
