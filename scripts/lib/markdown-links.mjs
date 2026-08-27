import { randomUUID } from 'node:crypto';

import MarkdownIt from 'markdown-it';

const markdownParser = new MarkdownIt({
  html: true,
  linkify: false,
  typographer: false,
});

// Keep the parsed destination text intact so diagnostics can name malformed
// percent escapes instead of reporting markdown-it's normalized replacement.
markdownParser.normalizeLink = (target) => target;

function recordReferenceLabel(state, openingBracket) {
  const labels = state.env.referenceProbeLabels;
  if (!(labels instanceof Map)) return;
  const labelStart = openingBracket + 1;
  const labelEnd = state.md.helpers.parseLinkLabel(state, openingBracket, true);
  if (labelEnd < 0 || state.src.charCodeAt(labelEnd + 1) !== 0x5b) return;
  const referenceStart = labelEnd + 2;
  const referenceEnd = state.md.helpers.parseLinkLabel(state, labelEnd + 1);
  if (referenceEnd < 0) return;
  const reference =
    state.src.slice(referenceStart, referenceEnd) || state.src.slice(labelStart, labelEnd);
  labels.set(state.md.utils.normalizeReference(reference), reference);
}

function captureLinkReferenceLabel(state) {
  if (state.src.charCodeAt(state.pos) !== 0x5b) return false;
  recordReferenceLabel(state, state.pos);
  return false;
}

function captureImageReferenceLabel(state) {
  if (
    state.src.charCodeAt(state.pos) !== 0x21 ||
    state.src.charCodeAt(state.pos + 1) !== 0x5b
  ) {
    return false;
  }
  recordReferenceLabel(state, state.pos + 1);
  return false;
}

markdownParser.inline.ruler.before('link', 'readme_link_reference_probe', captureLinkReferenceLabel);
markdownParser.inline.ruler.before(
  'image',
  'readme_image_reference_probe',
  captureImageReferenceLabel,
);

function inlineText(children) {
  let text = '';
  for (const token of children ?? []) {
    if (token.type === 'text' || token.type === 'code_inline') text += token.content;
    else if (token.type === 'softbreak' || token.type === 'hardbreak') text += ' ';
    else if (token.type === 'image') text += inlineText(token.children);
  }
  return text.trim().replace(/\s+/g, ' ');
}

function collectInline(children, result, section, inheritedLinkTarget = null) {
  const linkTargets = inheritedLinkTarget ? [inheritedLinkTarget] : [];
  for (const token of children ?? []) {
    if (token.type === 'link_open') {
      const target = token.attrGet('href');
      if (target) {
        result.links.push({ target, unresolvedReference: null });
        linkTargets.push(target);
      } else {
        linkTargets.push(null);
      }
      continue;
    }
    if (token.type === 'link_close') {
      linkTargets.pop();
      continue;
    }
    if (token.type === 'image') {
      const target = token.attrGet('src');
      if (target) result.links.push({ target, unresolvedReference: null });
      collectInline(token.children, result, section, target);
      continue;
    }
    if (token.type === 'code_inline') {
      result.codeSpans.push({
        linkTarget: linkTargets.at(-1) ?? null,
        section,
        text: token.content,
      });
    }
  }
}

function analyzeTokens(tokens) {
  const result = { codeSpans: [], headings: [], links: [], renderedText: '' };
  let section = null;
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token.type === 'heading_open') {
      const inline = tokens[index + 1];
      const level = Number(token.tag.slice(1));
      const text = inline?.type === 'inline' ? inlineText(inline.children) : '';
      const topLevel = token.level === 0;
      result.headings.push({ level, text, topLevel });
      if (inline?.type === 'inline') collectInline(inline.children, result, section);
      result.renderedText += `${text}\n`;
      if (topLevel && level === 1) section = null;
      if (topLevel && level === 2) section = text;
      index += 2;
      continue;
    }
    if (token.type === 'inline') {
      collectInline(token.children, result, section);
      result.renderedText += `${inlineText(token.children)}\n`;
    }
    if (token.type === 'fence' || token.type === 'code_block') {
      result.renderedText += `${token.content}\n`;
    }
  }
  return result;
}

function findUndefinedReferences(markdown, genuineReferences) {
  const markers = new Map();
  const labels = new Map();
  const references = Object.assign(Object.create(null), genuineReferences);
  const nonce = randomUUID();
  const probe = new Proxy(references, {
    get(target, property) {
      if (Reflect.has(target, property)) return Reflect.get(target, property);
      if (typeof property !== 'string' || !labels.has(property)) return undefined;
      const marker = `readme-verifier-undefined-${nonce}:${markers.size}`;
      markers.set(marker, property);
      return { href: marker, title: '' };
    },
  });
  const parsed = analyzeTokens(
    markdownParser.parse(markdown, { referenceProbeLabels: labels, references: probe }),
  );
  const renderedMarkers = new Set(parsed.links.map(({ target }) => target).filter(Boolean));
  return [...markers]
    .filter(([marker]) => renderedMarkers.has(marker))
    .map(([, normalized]) => labels.get(normalized) ?? normalized.toLowerCase());
}

export function analyzeMarkdown(markdown) {
  const environment = {};
  const result = analyzeTokens(markdownParser.parse(markdown, environment));
  for (const unresolvedReference of findUndefinedReferences(
    markdown,
    environment.references ?? {},
  )) {
    result.links.push({ target: null, unresolvedReference });
  }
  return result;
}

export function parseMarkdownCodeSpans(markdown) {
  return analyzeMarkdown(markdown).codeSpans;
}

export function parseMarkdownLinks(markdown) {
  return analyzeMarkdown(markdown).links;
}

export function extractLocalMarkdownTargets(markdown) {
  return parseMarkdownLinks(markdown)
    .map(({ target }) => target)
    .filter(
      (target) =>
        target &&
        !target.startsWith('#') &&
        !target.startsWith('//') &&
        !/^[a-z][a-z0-9+.-]*:/i.test(target),
    );
}

export function isLinkedFileReference(linkTarget, token) {
  if (!linkTarget || linkTarget.startsWith('//')) return false;
  if (/^[a-z][a-z0-9+.-]*:/i.test(linkTarget)) return false;
  const rawPath = linkTarget.split('#', 1)[0].split('?', 1)[0];
  let decoded;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    return false;
  }
  const unescaped = decoded.replace(/\\([!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])/g, '$1');
  return unescaped.replace(/\\/g, '/').split('/').at(-1) === token;
}
