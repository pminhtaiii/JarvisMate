import { resolve } from 'node:path';
import { dataDirectory, readJson } from './agent-store.mjs';
import { featureBranch } from './pr-conventions.mjs';

export function assertBranch(branch) {
  if (!featureBranch.test(branch ?? '')) throw new Error('Submission publication requires a feat/scope-description branch (historical numbered names remain readable).');
}

export function normalizeTargets(targets) {
  const normalized = {
    primary: { remote: targets?.primary?.remote, repository: targets?.primary?.repository, base: targets?.primary?.base },
    submission: { remote: targets?.submission?.remote, repository: targets?.submission?.repository, base: targets?.submission?.base },
  };
  if (normalized.primary.remote !== 'origin' || normalized.primary.base !== 'development' || normalized.submission.remote !== 'submission' || !['development', 'main'].includes(normalized.submission.base) || typeof normalized.primary.repository !== 'string' || typeof normalized.submission.repository !== 'string') throw new Error('Submission targets must be public origin/development and private submission/development (or historical main).');
  if (normalized.primary.repository.toLowerCase() === normalized.submission.repository.toLowerCase()) throw new Error('Public and submission repositories must be different.');
  return normalized;
}

function recordSlug(branch) { return branch.replaceAll('/', '-'); }

async function recordPath(repo, branch) {
  const directory = await dataDirectory(repo, 'paired-prs');
  return resolve(directory, `${recordSlug(branch)}.json`);
}

export async function readRecord(repo, branch) {
  const path = await recordPath(repo, branch);
  try { return { path, record: await readJson(path) }; }
  catch (error) { if (error.code === 'ENOENT') return { path, record: null }; throw error; }
}
