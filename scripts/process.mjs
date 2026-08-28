import { spawnSync } from 'node:child_process';

function commandLabel(executable, args) {
  return [executable, ...args].join(' ');
}

export function runCommand(executable, args, options = {}) {
  const result = spawnSync(executable, args, {
    cwd: options.cwd,
    env: options.env ?? process.env,
    encoding: 'utf8',
    shell: false,
    stdio: options.capture ? ['ignore', 'pipe', 'pipe'] : 'inherit',
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const output = options.capture ? `${result.stderr ?? ''}${result.stdout ?? ''}`.trim() : '';
    throw new Error(
      `${commandLabel(executable, args)} exited ${result.status}${output ? `: ${output}` : ''}`,
    );
  }
  return options.capture ? (result.stdout ?? '') : '';
}

export function runNpm(args, options = {}) {
  const npmCli = process.env.npm_execpath;
  if (!npmCli) throw new Error('npm_execpath is unavailable; run this command through npm');
  return runCommand(process.execPath, [npmCli, ...args], options);
}

export function runUv(args, options = {}) {
  const executable = process.platform === 'win32' ? 'uv.exe' : 'uv';
  return runCommand(executable, args, options);
}

export function pythonCompileallArgs() {
  const excludeFixtures = String.raw`(^|[\\/])tests[\\/]fixtures([\\/]|$)`;
  return ['python', '-m', 'compileall', '-q', '-x', excludeFixtures, 'src', 'tools', 'tests'];
}
