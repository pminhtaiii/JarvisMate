import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { syncBuiltinESMExports } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { backupLegacyViews } from '../../scripts/agents/active-task-legacy.mjs';

async function fixture(t) {
  const store = await fs.realpath(await fs.mkdtemp(join(tmpdir(), 'legacy-backup-')));
  t.after(() => fs.rm(store, { recursive: true, force: true }));
  t.after(() => { t.mock.restoreAll(); syncBuiltinESMExports(); });
  return { store, directory: join(store, 'legacy-active-task'), views: [{ checkout: store, source: '<!-- active-task:start -->\nlegacy data\n<!-- active-task:end -->\n' }] };
}

test('an interrupted backup write leaves no partial published backup', async (t) => {
  const { store, directory, views } = await fixture(t);
  const open = fs.open;
  t.mock.method(fs, 'open', async (...args) => {
    const handle = await open(...args);
    const writeFile = handle.writeFile.bind(handle);
    t.mock.method(handle, 'writeFile', async () => {
      await writeFile('partial backup', 'utf8');
      throw new Error('injected write failure');
    });
    return handle;
  });
  syncBuiltinESMExports();

  await assert.rejects(backupLegacyViews(store, views), /injected write failure/);
  assert.deepEqual(await fs.readdir(directory), []);
});

test('a concurrently published identical backup is accepted unchanged', async (t) => {
  const { store, directory, views } = await fixture(t);
  const link = fs.link;
  let published;
  t.mock.method(fs, 'link', async (temporary, path) => {
    published = await fs.readFile(temporary, 'utf8');
    await fs.writeFile(path, published, { flag: 'wx' });
    return link(temporary, path);
  });
  syncBuiltinESMExports();

  assert.equal(await backupLegacyViews(store, views), 1);
  const files = await fs.readdir(directory);
  assert.equal(files.length, 1);
  assert.equal(await fs.readFile(join(directory, files[0]), 'utf8'), published);
  assert.equal(JSON.parse(published).content, views[0].source);
});

test('a concurrently published conflicting backup is preserved and rejected', async (t) => {
  const { store, directory, views } = await fixture(t);
  const link = fs.link;
  t.mock.method(fs, 'link', async (temporary, path) => {
    await fs.writeFile(path, 'Keep this conflicting backup.\n', { flag: 'wx' });
    return link(temporary, path);
  });
  syncBuiltinESMExports();

  await assert.rejects(backupLegacyViews(store, views), /Legacy backup already exists with different content/);
  const files = await fs.readdir(directory);
  assert.equal(files.length, 1);
  assert.equal(await fs.readFile(join(directory, files[0]), 'utf8'), 'Keep this conflicting backup.\n');
});

test('the existing collision check still accepts identical backups and preserves conflicts', async (t) => {
  const { store, directory, views } = await fixture(t);
  assert.equal(await backupLegacyViews(store, views), 1);
  assert.equal(await backupLegacyViews(store, views), 1);
  const [file] = await fs.readdir(directory);
  const path = join(directory, file);
  await fs.writeFile(path, 'Keep this existing backup.\n');

  await assert.rejects(backupLegacyViews(store, views), /Legacy backup already exists with different content/);
  assert.equal(await fs.readFile(path, 'utf8'), 'Keep this existing backup.\n');
  assert.deepEqual(await fs.readdir(directory), [file]);
});

test('publication errors other than EEXIST propagate and remove temporary files', async (t) => {
  const { store, directory, views } = await fixture(t);
  const error = Object.assign(new Error('injected publication failure'), { code: 'EACCES' });
  t.mock.method(fs, 'link', async () => { throw error; });
  syncBuiltinESMExports();

  await assert.rejects(backupLegacyViews(store, views), (actual) => actual === error);
  assert.deepEqual(await fs.readdir(directory), []);
});
