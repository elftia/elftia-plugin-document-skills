const CONTAINED_ARGUMENTS = Object.freeze([
  '--disable-background-mode',
  '--disable-background-networking',
  '--disable-component-update',
  '--disable-default-apps',
  '--disable-extensions',
  '--disable-sync',
  '--metrics-recording-only',
  '--mute-audio',
  '--no-default-browser-check',
  '--no-first-run',
]);
export function containedBrowserOptions(executablePath, callerOptions = {}) {
  return {
    ...callerOptions,
    executablePath,
    headless: true,
    chromiumSandbox: true,
    javaScriptEnabled: false,
    serviceWorkers: 'block',
    args: [...CONTAINED_ARGUMENTS],
  };
}

export function isAllowedCaptureUrl(origin, url) {
  return url.startsWith(`${origin}/`);
}

export function blockedResourceReason(origin, url) {
  try {
    const expected = new URL(origin);
    const candidate = new URL(url);
    const protocol = candidate.protocol.toLowerCase();
    if (protocol === 'data:') return 'data_url_blocked';
    if (protocol === 'file:') return 'file_url_blocked';
    if (protocol === 'http:' || protocol === 'https:') {
      if (protocol === expected.protocol && candidate.host === expected.host) return 'path_escape';
      return 'remote_url_blocked';
    }
  } catch {
    // Invalid or relative requests are outside the exact tokenized origin.
  }
  return 'custom_scheme_blocked';
}
