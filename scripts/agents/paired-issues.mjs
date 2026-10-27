import { spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, unlink } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { atomicWrite, dataDirectory, readJson, repository, withLock } from './agent-store.mjs';
import { publicationTargets } from './publication-targets.mjs';

const labels = {
  'needs-triage': { color: 'fbca04', description: 'Maintainer needs to evaluate this issue.' },
  'needs-info': { color: 'd876e3', description: 'Waiting on the reporter for more information.' },
  'ready-for-agent': { color: '0e8a16', description: 'Fully specified and ready for an agent.' },
  'ready-for-human': { color: '0052cc', description: 'Requires human implementation.' },
  wontfix: { color: 'ffffff', description: 'Will not be actioned.' },
};
const usage = 'Usage: node scripts/agents/paired-issues.mjs publish --key <stable-slug> --title <title> --body-file <file> [--label <canonical-label>] [--root <checkout>]';
const sides = ['primary', 'submission'];
const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

function execute(binary, args, cwd, timeout = 30_000) {
  const result = spawnSync(binary, args, { cwd, encoding: 'utf8', windowsHide: true, timeout, maxBuffer: 64 * 1024 * 1024 });
  if (result.error || result.status !== 0) throw new Error(result.error?.message || result.stderr || result.stdout || binary + ' failed (' + result.status + ')');
  return result.stdout.trim();
}

function parseArgs(args) {
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) return { help: true };
  const [command, ...rest] = args;
  if (command !== 'publish') throw new Error(usage);
  const allowed = new Set(['key', 'title', 'body-file', 'label', 'root']);
  const values = {};
  for (let index = 0; index < rest.length; index += 2) {
    const option = rest[index];
    const value = rest[index + 1];
    const name = option?.slice(2);
    if (!option?.startsWith('--') || !allowed.has(name) || Object.hasOwn(values, name) || !value || value.startsWith('--')) throw new Error(usage);
    values[name] = value;
  }
  if (!values.key || !values.title || !values['body-file']) throw new Error(usage);
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(values.key) || values.key.length > 80) throw new Error('Provide --key as a lowercase stable slug of at most 80 characters.');
  if (values.title !== values.title.trim() || values.title.length > 256 || /[\r\n\0]/.test(values.title)) throw new Error('Issue title must contain 1-256 characters on one line without surrounding whitespace.');
  if (values.label && !Object.hasOwn(labels, values.label)) throw new Error('Use one of the five canonical triage labels for --label.');
  values.label ??= 'needs-triage';
  return values;
}

async function readBody(path) {
  const bytes = await readFile(resolve(path));
  if (bytes.length > 65_536) throw new Error('Issue body exceeds 65536 bytes.');
  let body;
  try { body = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
  catch { throw new Error('Issue body file must contain valid UTF-8.'); }
  if (!body.trim() || body.includes('\0')) throw new Error('Issue body must contain 1-65536 bytes and no NUL characters.');
  if (/<!-- paired-issue:sha256:[a-f0-9]{64} -->/i.test(body)) throw new Error('Issue body must not contain a paired-issue identity marker.');
  return body;
}

function json(output, description) {
  try { return JSON.parse(output); }
  catch { throw new Error('GitHub returned invalid ' + description + ' JSON.'); }
}

function pages(output, description) {
  const result = json(output, description);
  if (!Array.isArray(result) || result.some(page => !Array.isArray(page))) throw new Error('Could not confirm complete ' + description + ' pagination.');
  return result.flat();
}

function markerFor(publicRepository, key) {
  const digest = createHash('sha256').update(publicRepository.toLowerCase() + '\0' + key).digest('hex');
  return '<!-- paired-issue:sha256:' + digest + ' -->';
}

function markerMatches(issue, marker) {
  return typeof issue.body === 'string' && issue.body.split(/\r\n|\n|\r/).includes(marker);
}

function issueUrl(repositoryName, issue) {
  if (!Number.isSafeInteger(issue.number) || issue.number < 1 || typeof issue.html_url !== 'string') throw new Error('A marker-matched issue has an invalid identity.');
  let url;
  try { url = new URL(issue.html_url); }
  catch { throw new Error('A marker-matched issue has an invalid URL.'); }
  const expectedPath = '/' + repositoryName + '/issues/' + issue.number;
  if (url.protocol !== 'https:' || url.hostname !== 'github.com' || url.pathname.toLowerCase() !== expectedPath.toLowerCase() || url.search || url.hash) throw new Error('A marker-matched issue belongs to a different identity.');
  return { number: issue.number, url: url.toString(), state: issue.state };
}

function validateRecord(record, key, marker, targets) {
  if (!record || typeof record !== 'object' || Array.isArray(record) || record.schemaVersion !== 1 || record.key !== key || record.marker !== marker) throw new Error('Paired issue record has a mismatched stable-key identity.');
  if (!record.targets || sides.some(side => typeof record.targets[side] !== 'string')) throw new Error('Paired issue record has invalid target identities.');
  if (sides.some(side => record.targets[side].toLowerCase() !== targets[side].repository.toLowerCase())) throw new Error('Paired publication targets changed; restore their configuration or reconcile the retained record.');
  if (!record.receipts || sides.some(side => !Object.hasOwn(record.receipts, side))) throw new Error('Paired issue record has invalid receipts.');
}

function validatePreflight(side, target, data) {
  const expectedVisibility = side === 'primary' ? 'PUBLIC' : 'PRIVATE';
  if (!data || typeof data !== 'object' || data.nameWithOwner?.toLowerCase() !== target.repository.toLowerCase()) throw new Error('GitHub repository identity does not match the configured ' + side + ' target.');
  if (data.visibility !== expectedVisibility) throw new Error('The ' + side + ' repository must be ' + expectedVisibility.toLowerCase() + '.');
  if (data.hasIssuesEnabled !== true) throw new Error('Issues must be enabled for the ' + side + ' repository.');
  if (!['WRITE', 'MAINTAIN', 'ADMIN'].includes(data.viewerPermission)) throw new Error('Write permission is required for the ' + side + ' repository.');
}

function containsPrivateIdentity(text, repositoryName) {
  const normalized = text.toLowerCase();
  return normalized.includes(repositoryName.toLowerCase()) || normalized.includes(encodeURIComponent(repositoryName).toLowerCase());
}

function ensureReceipt(recorded, discovered, side) {
  if (!recorded) return discovered;
  if (!discovered || recorded.number !== discovered.number || typeof recorded.url !== 'string' || recorded.url.toLowerCase() !== discovered.url.toLowerCase()) {
    throw new Error('The saved ' + side + ' receipt no longer matches its stable marker.');
  }
  return discovered;
}

function joinedBody(body, sections, marker) {
  const newline = body.match(/\r\n|\n|\r/)?.[0] ?? '\n';
  const separator = body.endsWith('\n') || body.endsWith('\r') ? newline : newline + newline;
  return body + separator + [...sections, marker].join(newline);
}

async function withBodyFile(directory, body, operation) {
  const path = resolve(directory, '.body-' + randomUUID() + '.md');
  try {
    await atomicWrite(path, body);
    return await operation(path);
  } finally {
    await unlink(path).catch(error => { if (error.code !== 'ENOENT') throw error; });
  }
}

function issueList(call, target) {
  const endpoint = 'repos/' + target.repository + '/issues?state=all&per_page=100';
  return pages(call('gh', ['api', '--paginate', '--slurp', '--method', 'GET', endpoint], 60_000), target.repository + ' issue');
}

function labelList(call, target) {
  const endpoint = 'repos/' + target.repository + '/labels?per_page=100';
  return pages(call('gh', ['api', '--paginate', '--slurp', '--method', 'GET', endpoint], 60_000), target.repository + ' label');
}

function createReceipt(output, repositoryName) {
  const escaped = repositoryName.split('/').map(part => part.replaceAll('.', '\\.')).join('/');
  const matches = [...String(output ?? '').matchAll(new RegExp('https://github\\.com/' + escaped + '/issues/(\\d+)(?:\\b|$)', 'gi'))];
  if (matches.length !== 1) throw new Error('GitHub issue creation returned no unambiguous issue URL; retry to recover by stable marker.');
  const number = Number(matches[0][1]);
  return { number, url: 'https://github.com/' + repositoryName + '/issues/' + number };
}

export async function runPairedIssues(args, dependencies = {}) {
  const values = parseArgs(args);
  if (values.help) return { usage };
  const body = await readBody(values['body-file']);
  const repo = await repository(values.root ?? defaultRoot);
  const call = (binary, argv, timeout = 30_000) => (dependencies.execute ?? execute)(binary, argv, repo.root, timeout);
  const targetExecute = (binary, argv, cwd, timeout) => (dependencies.execute ?? execute)(binary, argv, cwd, timeout);
  const targets = await publicationTargets(repo, targetExecute);
  if (!targets) throw new Error('Paired issue publication requires publication-targets.json.');
  if (containsPrivateIdentity(body, targets.submission.repository) || containsPrivateIdentity(values.title, targets.submission.repository)) {
    throw new Error('Public issue content must not include the private repository identity.');
  }
  const marker = markerFor(targets.primary.repository, values.key);
  const store = await dataDirectory(repo, 'paired-issues');
  const recordPath = resolve(store, values.key + '.json');
  const lockPath = resolve(store, values.key + '.lock');

  return withLock(lockPath, async () => {
    let record;
    try {
      record = await readJson(recordPath);
      validateRecord(record, values.key, marker, targets);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      record = {
        schemaVersion: 1,
        key: values.key,
        marker,
        targets: { primary: targets.primary.repository, submission: targets.submission.repository },
        receipts: { primary: null, submission: null },
      };
    }

    const metadata = Object.fromEntries(await Promise.all(sides.map(async side => [
      side,
      json(call('gh', ['repo', 'view', targets[side].repository, '--json', 'nameWithOwner,visibility,viewerPermission,hasIssuesEnabled']), targets[side].repository + ' repository'),
    ])));
    for (const side of sides) validatePreflight(side, targets[side], metadata[side]);

    const found = Object.fromEntries(sides.map(side => {
      const matches = issueList(call, targets[side]).filter(issue => !issue.pull_request && markerMatches(issue, marker));
      if (matches.length > 1) throw new Error('Multiple issues contain the stable marker in the ' + side + ' repository.');
      return [side, matches[0] ? issueUrl(targets[side].repository, matches[0]) : null];
    }));
    for (const side of sides) record.receipts[side] = ensureReceipt(record.receipts[side], found[side], side);

    const availableLabels = Object.fromEntries(sides.map(side => [side, labelList(call, targets[side])]));
    const labelInfo = labels[values.label];
    record.intent = { title: values.title, label: values.label, bodySha256: createHash('sha256').update(body).digest('hex') };
    record.updatedAt = new Date().toISOString();
    await atomicWrite(recordPath, JSON.stringify(record, null, 2) + '\n');

    for (const side of sides) {
      if (!availableLabels[side].some(label => label?.name === values.label)) {
        call('gh', ['label', 'create', values.label, '--repo', targets[side].repository, '--color', labelInfo.color, '--description', labelInfo.description]);
      }
    }

    const publishOne = async (side, issueBody) => {
      const target = targets[side];
      let receipt = record.receipts[side];
      await withBodyFile(store, issueBody, async bodyPath => {
        if (receipt) {
          call('gh', ['issue', 'edit', String(receipt.number), '--repo', target.repository, '--title', values.title, '--body-file', bodyPath, '--add-label', values.label]);
        } else {
          receipt = createReceipt(call('gh', ['issue', 'create', '--repo', target.repository, '--title', values.title, '--body-file', bodyPath, '--label', values.label]), target.repository);
        }
      });
      record.receipts[side] = receipt;
      record.updatedAt = new Date().toISOString();
      await atomicWrite(recordPath, JSON.stringify(record, null, 2) + '\n');
      return receipt;
    };

    const primary = await publishOne('primary', joinedBody(body, [], marker));
    const submission = await publishOne('submission', joinedBody(body, ['Public counterpart: ' + primary.url], marker));
    return {
      status: 'PUBLISHED',
      key: values.key,
      primary: { repository: targets.primary.repository, ...primary },
      submission: { repository: targets.submission.repository, ...submission },
    };
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPairedIssues(process.argv.slice(2)).then(result => {
    console.log(result.usage ?? JSON.stringify(result, null, 2));
  }).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
