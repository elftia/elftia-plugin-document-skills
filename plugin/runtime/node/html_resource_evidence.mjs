import crypto from 'node:crypto';

const SAMPLE_LIMIT = 32;
const ENTRY_LIMIT = 512;

export function createBlockedResourceCollector(sampleLimit = SAMPLE_LIMIT) {
  if (!Number.isInteger(sampleLimit) || sampleLimit <= 0 || sampleLimit > SAMPLE_LIMIT) {
    throw new Error('invalid_resource_sample_limit');
  }
  const entries = new Map();
  const overflow = new Map();

  const record = (source, reason, reference, count = 1) => {
    if (!['declared', 'observed'].includes(source) || !validReason(reason) || !Number.isInteger(count) || count <= 0) {
      throw new Error('invalid_resource_evidence');
    }
    const resourceHash = hashReference(reference);
    const key = `${reason}:${resourceHash}`;
    const existing = entries.get(key);
    if (existing) {
      if (source === 'declared') existing.declared += count;
      else existing.observed += count;
      return;
    }
    if (entries.size >= ENTRY_LIMIT) {
      overflow.set(reason, (overflow.get(reason) ?? 0) + count);
      return;
    }
    entries.set(key, {
      reason,
      resource_hash: resourceHash,
      declared: source === 'declared' ? count : 0,
      observed: source === 'observed' ? count : 0,
    });
  };

  return {
    recordDeclared: (reason, reference, count = 1) => record('declared', reason, reference, count),
    recordObserved: (reason, reference, count = 1) => record('observed', reason, reference, count),
    mergeDeclared(summary) {
      for (const entry of summary.entries) {
        record('declared', entry.reason, entry.reference, entry.count);
      }
      for (const [reason, count] of Object.entries(summary.overflow_by_reason)) {
        if (!validReason(reason) || !Number.isInteger(count) || count < 0) {
          throw new Error('invalid_resource_evidence');
        }
        overflow.set(reason, (overflow.get(reason) ?? 0) + count);
      }
    },
    snapshot() {
      const aggregated = [...entries.values()]
        .map((entry) => ({
          reason: entry.reason,
          resource_hash: entry.resource_hash,
          count: Math.max(entry.declared, entry.observed),
        }))
        .filter((entry) => entry.count > 0)
        .sort((left, right) => (
          left.reason.localeCompare(right.reason)
          || left.resource_hash.localeCompare(right.resource_hash)
        ));
      const byReason = new Map(overflow);
      for (const entry of aggregated) {
        byReason.set(entry.reason, (byReason.get(entry.reason) ?? 0) + entry.count);
      }
      const samples = aggregated.slice(0, sampleLimit);
      const total = [...byReason.values()].reduce((sum, count) => sum + count, 0);
      const sampledOccurrences = samples.reduce((sum, entry) => sum + entry.count, 0);
      return {
        total,
        by_reason: Object.fromEntries([...byReason.entries()].sort(([left], [right]) => left.localeCompare(right))),
        samples,
        truncated: Math.max(0, total - sampledOccurrences),
      };
    },
  };
}

export async function collectDeclaredBlockedResources(page, allowedOrigin) {
  return page.evaluate(({ origin, entryLimit }) => {
    const entries = new Map();
    const overflowByReason = new Map();
    const allowed = new URL(origin);
    const record = (rawReference) => {
      if (typeof rawReference !== 'string' || !rawReference.trim()) return;
      let reference = rawReference.trim();
      let reason;
      try {
        const candidate = new URL(reference, document.baseURI);
        reference = candidate.href;
        if (candidate.href.startsWith(`${origin}/`)) return;
        if (candidate.protocol === 'data:') reason = 'data_url_blocked';
        else if (candidate.protocol === 'file:') reason = 'file_url_blocked';
        else if (candidate.protocol === 'http:' || candidate.protocol === 'https:') {
          reason = candidate.protocol === allowed.protocol && candidate.host === allowed.host
            ? 'path_escape'
            : 'remote_url_blocked';
        } else reason = 'custom_scheme_blocked';
      } catch {
        reason = 'path_escape';
      }
      const key = `${reason}\n${reference}`;
      if (entries.has(key)) {
        entries.get(key).count += 1;
      } else if (entries.size < entryLimit) {
        entries.set(key, { reason, reference, count: 1 });
      } else {
        overflowByReason.set(reason, (overflowByReason.get(reason) ?? 0) + 1);
      }
    };
    const recordUrls = (value) => {
      if (typeof value !== 'string') return;
      for (const match of value.matchAll(/url\(\s*(?<q>["']?)(?<url>.*?)\k<q>\s*\)/gi)) record(match.groups.url);
      for (const match of value.matchAll(/@import\s+(?:url\(\s*)?(?<q>["'])(?<url>.*?)\k<q>/gi)) record(match.groups.url);
    };
    const attributes = [
      ['img', 'src'],
      ['input[type="image"]', 'src'],
      ['source', 'src'],
      ['video', 'poster'],
      ['object', 'data'],
      ['link[rel~="stylesheet"]', 'href'],
      ['link[rel~="icon"]', 'href'],
    ];
    for (const [selector, attribute] of attributes) {
      for (const element of document.querySelectorAll(selector)) record(element.getAttribute(attribute));
    }
    for (const element of document.querySelectorAll('[srcset]')) {
      for (const candidate of (element.getAttribute('srcset') ?? '').split(',')) {
        record(candidate.trim().split(/\s+/, 1).at(0));
      }
    }
    for (const element of document.querySelectorAll('[style]')) recordUrls(element.getAttribute('style'));
    for (const element of document.querySelectorAll('style')) recordUrls(element.textContent);
    for (const sheet of document.styleSheets) {
      if (sheet.ownerNode?.tagName === 'STYLE') continue;
      try {
        for (const rule of sheet.cssRules) recordUrls(rule.cssText);
      } catch {
        // A blocked or cross-origin stylesheet is already represented by its link element.
      }
    }
    return {
      entries: [...entries.values()],
      overflow_by_reason: Object.fromEntries(overflowByReason),
    };
  }, { origin: allowedOrigin, entryLimit: ENTRY_LIMIT });
}

function hashReference(reference) {
  const bounded = typeof reference === 'string' ? reference.slice(0, 4096) : '';
  return crypto.createHash('sha256').update(bounded, 'utf8').digest('hex');
}

function validReason(value) {
  return typeof value === 'string' && /^[a-z][a-z0-9_]{0,79}$/.test(value);
}
