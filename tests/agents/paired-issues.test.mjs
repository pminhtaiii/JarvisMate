import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runPairedIssues } from '../../scripts/agents/paired-issues.mjs';

const publicRepository = 'example/public';
const privateRepository = 'course/private';
const publicUrl = 'https://github.com/' + publicRepository;
const privateUrl = 'https://github.com/' + privateRepository;

async function workspace(t) {
  const root = await mkdtemp(join(tmpdir(), 'paired-issues-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const initialized = spawnSync('git', ['init', '--initial-branch=main'], { cwd: root, encoding: 'utf8' });
  assert.equal(initialized.status, 0, initialized.stderr);
  await writeFile(join(root, 'publication-targets.json'), JSON.stringify({
    schemaVersion: 1,
    submission: { remote: 'submission', base: 'development' },
  }));
  return root;
}

function github(options = {}) {
  const repositories = {
    [publicRepository]: {
      metadata: { nameWithOwner: publicRepository, visibility: 'PUBLIC', viewerPermission: 'WRITE', hasIssuesEnabled: true },
      issues: [],
      labels: options.publicLabels ?? [],
    },
    [privateRepository]: {
      metadata: { nameWithOwner: privateRepository, visibility: 'PRIVATE', viewerPermission: 'WRITE', hasIssuesEnabled: true },
      issues: [],
      labels: options.privateLabels ?? [],
    },
  };
  const calls = [];
  const writes = [];
  const nextNumber = { [publicRepository]: 1, [privateRepository]: 1 };
  const execute = (binary, args, cwd, timeout) => {
    assert.equal(typeof timeout, 'number', 'injected command timeouts are numeric');
    if (binary === 'git') return args[2] === 'origin' ? publicUrl + '.git' : privateUrl + '.git';
    assert.equal(binary, 'gh');
    calls.push([...args]);
    if (args[0] === 'repo' && args[1] === 'view') {
      const data = repositories[args[2]];
      if (!data) throw new Error('unknown repository');
      if (options.metadata) Object.assign(data.metadata, options.metadata[args[2]] ?? {});
      return JSON.stringify(data.metadata);
    }
    if (args[0] === 'api' && args.includes('--paginate')) {
      const endpoint = args.at(-1);
      const match = endpoint.match(/^repos\/([^?]+)\/(issues|labels)\?/);
      assert.ok(match, endpoint);
      const repository = repositories[match[1]];
      assert.ok(repository, match[1]);
      if (options.incompleteEndpoint === match[2]) return JSON.stringify([{ number: 1 }]);
      if (match[2] === 'issues') return JSON.stringify([repository.issues.map(issue => ({ ...issue }))]);
      return JSON.stringify([repository.labels.map(name => ({ name }))]);
    }
    if (args[0] === 'label' && args[1] === 'create') {
      const name = args[2];
      const repository = repositories[args[args.indexOf('--repo') + 1]];
      repository.labels.push(name);
      writes.push({ kind: 'label', repository: args[args.indexOf('--repo') + 1], name });
      return '';
    }
    if (args[0] === 'issue' && args[1] === 'create') {
      const repositoryName = args[args.indexOf('--repo') + 1];
      const repository = repositories[repositoryName];
      const title = args[args.indexOf('--title') + 1];
      const body = readFileSync(args[args.indexOf('--body-file') + 1], 'utf8');
      const label = args[args.indexOf('--label') + 1];
      const issue = {
        number: nextNumber[repositoryName]++,
        html_url: 'https://github.com/' + repositoryName + '/issues/' + nextNumber[repositoryName],
        title,
        body,
        state: 'open',
        labels: [{ name: label }],
      };
      issue.html_url = 'https://github.com/' + repositoryName + '/issues/' + issue.number;
      repository.issues.push(issue);
      writes.push({ kind: 'create', repository: repositoryName, number: issue.number, body });
      if (options.afterCreate) options.afterCreate(repositoryName, issue);
      return issue.html_url;
    }
    if (args[0] === 'issue' && args[1] === 'edit') {
      const number = Number(args[2]);
      const repositoryName = args[args.indexOf('--repo') + 1];
      const repository = repositories[repositoryName];
      const issue = repository.issues.find(candidate => candidate.number === number);
      assert.ok(issue, 'issue to update exists');
      issue.title = args[args.indexOf('--title') + 1];
      issue.body = readFileSync(args[args.indexOf('--body-file') + 1], 'utf8');
      const label = args[args.indexOf('--add-label') + 1];
      if (!issue.labels.some(existing => existing.name === label)) issue.labels.push({ name: label });
      writes.push({ kind: 'edit', repository: repositoryName, number, body: issue.body });
      return '';
    }
    throw new Error('unexpected GitHub command: ' + args.join(' '));
  };
  return { repositories, calls, writes, execute };
}

async function publish(root, bodyFile, githubClient, options = {}) {
  const args = ['publish', '--key', options.key ?? 'stable-ticket', '--title', options.title ?? 'Ticket title', '--body-file', bodyFile, '--root', root];
  if (options.label) args.push('--label', options.label);
  return runPairedIssues(args, { execute: githubClient.execute });
}

test('publishing a paired ticket recovers both issues after a lost private create response', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  await writeFile(bodyFile, 'First line\nsecond line\n');
  let lostResponse = true;
  const client = github({
    afterCreate(repositoryName) {
      if (repositoryName === privateRepository && lostResponse) {
        lostResponse = false;
        throw new Error('response lost after remote create');
      }
    },
  });

  await assert.rejects(publish(root, bodyFile, client), /response lost/);
  const result = await publish(root, bodyFile, client);

  assert.equal(client.repositories[publicRepository].issues.length, 1);
  assert.equal(client.repositories[privateRepository].issues.length, 1);
  assert.equal(result.primary.number, 1);
  assert.equal(result.submission.number, 1);
  assert.match(result.primary.url, /example\/public\/issues\/1$/);
  assert.match(result.submission.url, /course\/private\/issues\/1$/);
  assert.ok(client.repositories[publicRepository].issues[0].body.startsWith('First line\nsecond line\n'));
  assert.equal(client.writes.filter(write => write.kind === 'create').length, 2);
});

test('remote marker recovery avoids duplicate creation when the local receipt is missing', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  await writeFile(bodyFile, 'Recover by stable key.');
  const client = github();
  await publish(root, bodyFile, client);
  await rm(join(root, '.agent-work', 'paired-issues', 'stable-ticket.json'));

  const result = await publish(root, bodyFile, client);

  assert.equal(client.repositories[publicRepository].issues.length, 1);
  assert.equal(client.repositories[privateRepository].issues.length, 1);
  assert.equal(client.writes.filter(write => write.kind === 'create').length, 2);
  assert.equal(client.writes.filter(write => write.kind === 'edit').length, 2);
  assert.equal(result.primary.number, 1);
  assert.equal(result.submission.number, 1);
});

test('the same key updates both issues and adds the requested canonical label without removing existing labels', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  const client = github();
  await writeFile(bodyFile, 'Original body.');
  await publish(root, bodyFile, client);
  for (const repositoryName of [publicRepository, privateRepository]) client.repositories[repositoryName].issues[0].state = 'closed';
  await writeFile(bodyFile, 'Updated body.\n');

  const result = await publish(root, bodyFile, client, { title: 'Updated title', label: 'ready-for-agent' });

  for (const repositoryName of [publicRepository, privateRepository]) {
    const issue = client.repositories[repositoryName].issues[0];
    assert.equal(issue.title, 'Updated title');
    assert.match(issue.body, /^Updated body\./);
    assert.equal(issue.state, 'closed');
    assert.deepEqual(issue.labels.map(label => label.name).sort(), ['needs-triage', 'ready-for-agent']);
  }
  assert.equal(result.primary.number, 1);
  assert.equal(result.submission.number, 1);
});

test('the public issue body never contains the private repository identity or URL', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  await writeFile(bodyFile, 'Public description only.');
  const client = github();

  await publish(root, bodyFile, client);

  const body = client.repositories[publicRepository].issues[0].body;
  assert.doesNotMatch(body, /course\/private|github\.com\/course\/private/i);
  assert.match(client.repositories[privateRepository].issues[0].body, /https:\/\/github\.com\/example\/public\/issues\/1/);
});

test('the private repository preflight is checked before any label or issue writes', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  await writeFile(bodyFile, 'Request.');
  const client = github({ metadata: { [privateRepository]: { visibility: 'PUBLIC' } } });

  await assert.rejects(publish(root, bodyFile, client), /must be private/);

  assert.equal(client.calls.filter(args => args[0] === 'repo' && args[1] === 'view').length, 2);
  assert.equal(client.writes.length, 0);
});

test('write permission and enabled issues are required in both repositories', async t => {
  for (const invalid of [
    { repository: publicRepository, metadata: { viewerPermission: 'READ' }, message: /Write permission/ },
    { repository: privateRepository, metadata: { hasIssuesEnabled: false }, message: /Issues must be enabled/ },
  ]) {
    const root = await workspace(t);
    const bodyFile = join(root, 'request.md');
    await writeFile(bodyFile, 'Request.');
    const client = github({ metadata: { [invalid.repository]: invalid.metadata } });

    await assert.rejects(publish(root, bodyFile, client), invalid.message);

    assert.equal(client.calls.filter(args => args[0] === 'repo' && args[1] === 'view').length, 2);
    assert.equal(client.writes.length, 0);
  }
});

test('duplicate remote markers fail before any writes', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  await writeFile(bodyFile, 'Request.');
  const client = github();
  await publish(root, bodyFile, client);
  const issue = client.repositories[publicRepository].issues[0];
  client.repositories[publicRepository].issues.push({ ...issue, number: 99, html_url: publicUrl + '/issues/99' });
  client.writes.length = 0;

  await assert.rejects(publish(root, bodyFile, client), /multiple issues/i);

  assert.equal(client.writes.length, 0);
});

test('a saved receipt that conflicts with the marker fails before writes', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  await writeFile(bodyFile, 'Request.');
  const client = github();
  await publish(root, bodyFile, client);
  const recordPath = join(root, '.agent-work', 'paired-issues', 'stable-ticket.json');
  const record = JSON.parse(readFileSync(recordPath, 'utf8'));
  record.receipts.primary = { number: 99, url: publicUrl + '/issues/99' };
  await writeFile(recordPath, JSON.stringify(record));
  client.writes.length = 0;

  await assert.rejects(publish(root, bodyFile, client), /receipt no longer matches/);

  assert.equal(client.writes.length, 0);
});

test('changed local target identity and incomplete issue pagination fail before writes', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  await writeFile(bodyFile, 'Request.');
  const client = github();
  await publish(root, bodyFile, client);
  client.writes.length = 0;
  const configPath = join(root, 'publication-targets.json');
  await writeFile(configPath, JSON.stringify({
    schemaVersion: 1,
    submission: { remote: 'submission', base: 'development' },
  }));
  const changedClient = { ...client, execute: (binary, args, cwd, timeout) => {
    if (binary === 'git' && args[2] === 'submission') return 'https://github.com/course/changed.git';
    return client.execute(binary, args, cwd, timeout);
  } };
  await assert.rejects(publish(root, bodyFile, changedClient), /targets changed/);
  assert.equal(client.writes.length, 0);

  const incomplete = github({ incompleteEndpoint: 'issues' });
  await assert.rejects(publish(root, bodyFile, incomplete), /pagination|complete/i);
  assert.equal(incomplete.writes.length, 0);
});

test('invalid labels and public bodies containing private identity are rejected before remote calls', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  await writeFile(bodyFile, 'See https://github.com/course/private/issues/4.');
  const client = github();

  await assert.rejects(publish(root, bodyFile, client), /private repository identity/);
  assert.equal(client.calls.length, 0);

  await writeFile(bodyFile, 'Safe body.');
  await assert.rejects(publish(root, bodyFile, client, { label: 'priority' }), /canonical triage label/);
  assert.equal(client.calls.length, 0);
});

test('invalid keys, titles, and empty bodies are rejected before GitHub calls', async t => {
  const root = await workspace(t);
  const bodyFile = join(root, 'request.md');
  await writeFile(bodyFile, 'Safe body.');
  const client = github();

  await assert.rejects(publish(root, bodyFile, client, { key: 'Unstable Key' }), /stable slug/);
  await assert.rejects(publish(root, bodyFile, client, { title: ' title ' }), /Issue title/);
  await writeFile(bodyFile, ' \n\t ');
  await assert.rejects(publish(root, bodyFile, client), /Issue body must contain/);
  assert.equal(client.calls.length, 0);
});
