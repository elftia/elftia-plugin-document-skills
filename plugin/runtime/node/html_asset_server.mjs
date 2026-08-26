import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';

const MAX_ASSET_BYTES = 8 * 1024 * 1024;
const DEFAULT_CAPTURE_LIMITS = Object.freeze({
  maxRequests: 512,
  maxTotalBytes: 32 * 1024 * 1024,
});
const TOKEN_PATTERN = /^[a-f0-9]{32,96}$/;
const MIME_TYPES = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.gif', 'image/gif'],
  ['.htm', 'text/html; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.jpeg', 'image/jpeg'],
  ['.jpg', 'image/jpeg'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.webp', 'image/webp'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
]);

export async function startAssetServer(
  sourceRoot,
  token,
  onBlocked,
  limits = DEFAULT_CAPTURE_LIMITS,
) {
  if (!TOKEN_PATTERN.test(token)) throw new Error('invalid_token');
  const budget = validateBudget(limits);
  const canonicalRoot = await fs.realpath(sourceRoot);
  if (!(await fs.stat(canonicalRoot)).isDirectory()) throw new Error('asset_root');
  let fatalReason = null;
  let requestCount = 0;
  let servedBytes = 0;
  const server = http.createServer(async (request, response) => {
    try {
      requestCount += 1;
      if (requestCount > budget.maxRequests) {
        fatalReason ??= 'asset_request_limit';
        throw new Error(fatalReason);
      }
      const file = await resolveRequest(canonicalRoot, token, request);
      const stat = await fs.stat(file);
      const mime = MIME_TYPES.get(path.extname(file).toLowerCase());
      if (!stat.isFile() || stat.size <= 0 || stat.size > MAX_ASSET_BYTES || !mime) {
        throw new Error('asset_policy');
      }
      if (servedBytes + stat.size > budget.maxTotalBytes) {
        fatalReason ??= 'asset_total_limit';
        throw new Error(fatalReason);
      }
      servedBytes += stat.size;
      const bytes = await fs.readFile(file);
      if (bytes.length !== stat.size) throw new Error('asset_changed');
      response.writeHead(200, securityHeaders(mime, bytes.length));
      response.end(bytes);
    } catch (error) {
      onBlocked(blockReason(error), request.url ?? '');
      response.writeHead(404, securityHeaders('text/plain; charset=utf-8', 0));
      response.end();
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('server_address');
  return {
    origin: `http://127.0.0.1:${address.port}/${token}`,
    close: () => new Promise((resolve) => server.close(resolve)),
    usage: () => ({ bytes: servedBytes, requests: requestCount }),
    assertWithinBudget: () => {
      if (fatalReason !== null) throw new Error(fatalReason);
    },
  };
}

function validateBudget(value) {
  if (
    value === null
    || typeof value !== 'object'
    || !Number.isInteger(value.maxRequests)
    || !Number.isInteger(value.maxTotalBytes)
    || value.maxRequests <= 0
    || value.maxRequests > DEFAULT_CAPTURE_LIMITS.maxRequests
    || value.maxTotalBytes <= 0
    || value.maxTotalBytes > DEFAULT_CAPTURE_LIMITS.maxTotalBytes
  ) {
    throw new Error('invalid_asset_budget');
  }
  return value;
}

export async function resolveLocalAsset(sourceRoot, reference) {
  if (typeof reference !== 'string' || !reference || reference.includes('\0')) {
    throw new Error('asset_reference');
  }
  const decoded = decodeURIComponent(reference.split(/[?#]/, 1).at(0));
  if (decoded.includes('\\') || path.isAbsolute(decoded)) throw new Error('asset_escape');
  const segments = decoded.split('/');
  if (segments.some((segment) => !segment || segment === '.' || segment === '..')) {
    throw new Error('asset_escape');
  }
  const canonicalRoot = await fs.realpath(sourceRoot);
  const candidate = path.join(canonicalRoot, ...segments);
  const canonical = await fs.realpath(candidate);
  if (!isDescendant(canonicalRoot, canonical)) throw new Error('asset_escape');
  await assertNoSymlink(canonicalRoot, candidate);
  return canonical;
}

async function resolveRequest(canonicalRoot, token, request) {
  if (request.method !== 'GET' || typeof request.url !== 'string') {
    throw new Error('method_blocked');
  }
  const url = new URL(request.url, 'http://127.0.0.1');
  const prefix = `/${token}/`;
  if (!url.pathname.startsWith(prefix) || url.search || url.hash) {
    throw new Error('token_blocked');
  }
  return resolveLocalAsset(canonicalRoot, url.pathname.slice(prefix.length));
}

async function assertNoSymlink(root, candidate) {
  const relative = path.relative(root, candidate);
  let current = root;
  for (const segment of relative.split(path.sep)) {
    current = path.join(current, segment);
    if ((await fs.lstat(current)).isSymbolicLink()) throw new Error('asset_symlink');
  }
}

function isDescendant(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative !== '' && !relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative);
}

function securityHeaders(contentType, length) {
  return {
    'Cache-Control': 'no-store',
    'Content-Length': String(length),
    'Content-Security-Policy': "default-src 'none'; img-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'",
    'Content-Type': contentType,
    'Cross-Origin-Resource-Policy': 'same-origin',
    'X-Content-Type-Options': 'nosniff',
  };
}

function blockReason(error) {
  const reason = error instanceof Error ? error.message : '';
  if (reason === 'asset_request_limit' || reason === 'asset_total_limit') return reason;
  if (reason === 'asset_symlink') return 'symlink_escape';
  if (reason === 'asset_escape') return 'path_escape';
  if (reason === 'token_blocked') return 'invalid_token';
  if (reason === 'method_blocked') return 'method_blocked';
  return 'asset_unavailable';
}
