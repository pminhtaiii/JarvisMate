import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const projectManifest = JSON.parse(readFileSync(join(projectRoot, 'package.json'), 'utf8'));
const root = mkdtempSync(join(tmpdir(), 'slop-loop-package-manager-'));
const manifest = {
  name: 'slop-loop-package-manager-check',
  version: '1.0.0',
  private: true,
  packageManager: projectManifest.packageManager,
  devEngines: projectManifest.devEngines,
  scripts: {
    'check:manager': 'node -e "console.log(\'manager-check-ran\')"',
    lint: 'node -e "console.log(\'lint-ran\')"',
    test: 'node -e "console.log(\'test-ran\')"',
  },
};

assert.match(projectManifest.packageManager, /^pnpm@/);
assert.equal(projectManifest.devEngines?.packageManager?.name, 'pnpm');
writeFileSync(join(root, 'package.json'), JSON.stringify(manifest));

after(() => {
  if (dirname(resolve(root)) === resolve(tmpdir())) rmSync(root, { recursive: true, force: true });
});

function runManager(manager, action = 'run check:manager') {
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (key.toLowerCase() === 'npm_config_user_agent') delete env[key];
  }

  const args = `${manager} ${action}`;
  return process.platform === 'win32'
    ? spawnSync('cmd.exe', ['/d', '/s', '/c', args], { cwd: root, env, encoding: 'utf8', windowsHide: true })
    : spawnSync(manager, action.split(' '), { cwd: root, env, encoding: 'utf8' });
}

function runCorepackYarn(action) {
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (key.toLowerCase() === 'npm_config_user_agent') delete env[key];
  }
  return process.platform === 'win32'
    ? spawnSync('cmd.exe', ['/d', '/s', '/c', `corepack yarn ${action}`], { cwd: root, env, encoding: 'utf8', windowsHide: true })
    : spawnSync('corepack', ['yarn', ...action.split(' ')], { cwd: root, env, encoding: 'utf8' });
}

test('pnpm can run project scripts under the package manager requirement', () => {
  const result = runManager('pnpm');
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /manager-check-ran/);
});

test('npm run lint and npm test are refused with the required manager before scripts run', () => {
  for (const [action, marker] of [['run lint', 'lint-ran'], ['test', 'test-ran']]) {
    const result = runManager('npm', action);
    assert.ifError(result.error);
    assert.notEqual(result.status, 0, result.stdout);
    assert.match(result.stderr, /devEngines\.packageManager/);
    assert.match(result.stderr, /pnpm/);
    assert.doesNotMatch(result.stdout, new RegExp(marker));
  }
});

test('pnpm can install with the package manager requirement', () => {
  const result = runManager('pnpm', 'install --dry-run --lockfile=false --ignore-scripts --offline');
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
});

test('npm install is refused even when lifecycle scripts are ignored', () => {
  const result = runManager('npm', 'install --dry-run --package-lock=false --ignore-scripts --offline');
  assert.ifError(result.error);
  assert.notEqual(result.status, 0, result.stdout);
});

const corepackAvailable = process.platform === 'win32'
  ? spawnSync('cmd.exe', ['/d', '/s', '/c', 'corepack --version'], { cwd: root, windowsHide: true }).status === 0
  : spawnSync('corepack', ['--version'], { cwd: root }).status === 0;

test('Corepack refuses Yarn script and install commands for the pnpm project', { skip: !corepackAvailable }, () => {
  for (const action of ['run lint', 'install --immutable']) {
    const result = runCorepackYarn(action);
    assert.ifError(result.error);
    assert.notEqual(result.status, 0, result.stdout);
    assert.match(result.stdout + result.stderr, /configured to use pnpm/i);
    assert.doesNotMatch(result.stdout + result.stderr, /lint-ran|test-ran/);
  }
});
