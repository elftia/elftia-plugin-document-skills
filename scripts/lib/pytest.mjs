export const DEFAULT_PYTEST_WORKERS = 4;

export function resolvePytestWorkers(rawValue) {
  const value = rawValue?.trim();
  if (!value) return String(DEFAULT_PYTEST_WORKERS);
  if (!/^\d+$/.test(value)) {
    throw new Error('DS_PYTEST_WORKERS must be a positive integer');
  }

  const workers = Number(value);
  if (!Number.isSafeInteger(workers) || workers < 1) {
    throw new Error('DS_PYTEST_WORKERS must be a positive integer');
  }
  return String(workers);
}
