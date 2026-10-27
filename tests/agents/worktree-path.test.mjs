import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, realpath, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { realDirectoryWithoutLinks } from '../../scripts/agents/worktree-path.mjs';

function alternateCase(path) {
  const start = path.indexOf('\\', 2) + 1;
  const offset = path.slice(start).search(/[a-z]/i);
  if (offset === -1) return path;
  const index = start + offset;
  const letter = path[index];
  return path.slice(0, index) + (letter === letter.toLowerCase() ? letter.toUpperCase() : letter.toLowerCase()) + path.slice(index + 1);
}

function shortPath(path) {
  if (process.platform !== 'win32') return null;
  const typeDefinition = [
    'using System.Runtime.InteropServices;',
    'using System.Text;',
    'public static class NativePathAlias {',
    '  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]',
    '  public static extern uint GetShortPathName(string longPath, StringBuilder shortPath, uint length);',
    '}',
  ].join('\n');
  const command = `Add-Type -TypeDefinition @'\n${typeDefinition}\n'@\n$buffer = New-Object System.Text.StringBuilder(32768)\n[void][NativePathAlias]::GetShortPathName($env:WORKTREE_PATH_FOR_TEST, $buffer, [uint32]$buffer.Capacity)\n$buffer.ToString()`;
  const result = spawnSync('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command], {
    encoding: 'utf8', windowsHide: true, env: { ...process.env, WORKTREE_PATH_FOR_TEST: path },
  });
  const candidate = result.status === 0 ? result.stdout.trim() : '';
  return candidate && candidate.toLowerCase() !== path.toLowerCase() ? candidate : null;
}

async function fixture(t) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'worktree-path-')));
  t.after(() => rm(root, { recursive: true, force: true }));
  const directory = join(root, 'a long worker directory');
  await mkdir(directory);
  return { root, directory };
}

test('accepts a canonical directory path', async (t) => {
  const { directory } = await fixture(t);
  assert.equal(await realDirectoryWithoutLinks(directory), await realpath(directory));
});

test('accepts a valid case-variant directory path on Windows', async (t) => {
  if (process.platform !== 'win32') return t.skip('Windows path casing is required for this regression.');
  const { directory } = await fixture(t);
  assert.equal(await realDirectoryWithoutLinks(alternateCase(directory)), await realpath(directory));
});

test('accepts a valid Windows 8.3 short-name directory path when the volume provides one', async (t) => {
  if (process.platform !== 'win32') return t.skip('Windows 8.3 alias not run locally; Windows CI validation is required.');
  const { directory } = await fixture(t);
  const alias = shortPath(directory);
  if (!alias) return t.skip('No local 8.3 alias is available; Windows CI validation is required.');
  assert.equal(await realDirectoryWithoutLinks(alias), await realpath(directory));
});

test('rejects a final directory junction or symbolic link', async (t) => {
  const { root, directory } = await fixture(t);
  const link = join(root, 'final-link');
  await symlink(directory, link, process.platform === 'win32' ? 'junction' : 'dir');
  await assert.rejects(realDirectoryWithoutLinks(link), /symbolic link/i);
});

test('rejects a junction or symbolic link in an intermediate directory component', async (t) => {
  const { root } = await fixture(t);
  const realParent = join(root, 'real-parent');
  const linkedParent = join(root, 'linked-parent');
  await mkdir(join(realParent, 'child'), { recursive: true });
  await symlink(realParent, linkedParent, process.platform === 'win32' ? 'junction' : 'dir');
  await assert.rejects(realDirectoryWithoutLinks(join(linkedParent, 'child')), /symbolic link/i);
});
