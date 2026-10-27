import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { githubRepository, publicationTargets } from '../../scripts/agents/publication-targets.mjs';

test('publication targets require two explicit GitHub remotes without exposing private names in config', async t => {
  const root = await mkdtemp(join(tmpdir(), 'publication-targets-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  let calls = 0;
  const execute = (binary, args) => { calls++; assert.equal(binary, 'git'); return args[2] === 'origin' ? 'https://github.com/example/public.git' : 'git@github.com:course/private.git'; };
  assert.equal(await publicationTargets({ root }, execute), null);
  assert.equal(calls, 0, 'legacy checkouts without configuration stay single-target');
  const config = { schemaVersion: 1, submission: { remote: 'submission', base: 'development' } };
  await writeFile(join(root, 'publication-targets.json'), JSON.stringify(config));
  assert.deepEqual(await publicationTargets({ root }, execute), { primary: { remote: 'origin', base: 'development', repository: 'example/public' }, submission: { remote: 'submission', base: 'development', repository: 'course/private' } });
  await assert.rejects(publicationTargets({ root }, () => 'https://github.com/example/public.git'), /different/);
  await writeFile(join(root, 'publication-targets.json'), JSON.stringify({ ...config, submission: { remote: 'origin', base: 'development' } }));
  await assert.rejects(publicationTargets({ root }, execute), /requires/);
  assert.throws(() => githubRepository('https://other.example/private.git'), /GitHub/);
});

test('historical main configuration remains readable but unsupported bases are refused', async t => {
  const root = await mkdtemp(join(tmpdir(), 'publication-targets-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const execute = (binary, args) => args[2] === 'origin' ? 'https://github.com/example/public.git' : 'https://github.com/course/private.git';
  await writeFile(join(root, 'publication-targets.json'), JSON.stringify({ schemaVersion: 1, submission: { remote: 'submission', base: 'main' } }));
  assert.equal((await publicationTargets({ root }, execute)).submission.base, 'main');
  await writeFile(join(root, 'publication-targets.json'), JSON.stringify({ schemaVersion: 1, submission: { remote: 'submission', base: 'other' } }));
  await assert.rejects(publicationTargets({ root }, execute), /requires/);
});
