// Contributor rules: docs/agents/pr-conventions.md. Legacy identity readers stay permissive.
const numberedBranch = /^feat\/(?!000-)\d{3}-[a-z][a-z0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*$/;
const scopedBranch = /^feat\/[a-z][a-z0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const featureBranch = /^feat\/(?:\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*|[a-z][a-z0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*)$/;
const action = /^(?:add|implement|fix|refactor|standardize|document|update|remove|preserve|prevent|support|configure|migrate|validate|test|improve|tighten|enforce|restore|repair|freeze|gate)\s+\S/;

export function assertNewBranch(branch, version = 2) {
  if (version === 1) {
    if (!numberedBranch.test(branch ?? '')) throw new Error('Version 1 work requires feat/NNN-scope-short-description with a nonzero unique NNN.');
  } else if (!scopedBranch.test(branch ?? '')) throw new Error('New work requires feat/scope-short-description without a numeric prefix.');
}

export function assertNewDescription(body) {
  let fence;
  const lines = [];
  for (const line of body.replace(/\r\n/g, '\n').split('\n')) {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (fence) {
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = undefined;
      continue;
    }
    if (marker) { fence = marker[1]; continue; }
    lines.push(line);
  }
  const text = lines.join('\n');
  const sections = [...text.matchAll(/^## (.+)$/gm)];
  if (sections.map(s => s[1]).join('|') !== 'Summary|Evidence|Merge Danger' || sections.some((s, i) => !text.slice(s.index + s[0].length, sections[i + 1]?.index).trim())) {
    throw new Error('PR description requires nonempty Summary, Evidence and Merge Danger sections in that order.');
  }
  const danger = text.slice(sections[2].index);
  if (!/\*\*Door:\*\*\s*\S/.test(danger) || !/\*\*Blast Radius:\*\*\s*\S/.test(danger)) throw new Error('Merge Danger requires Door and Blast Radius, including rollback and integration risk.');
}

// Read-only inventory: fetch-independent live heads and paginated PR history include deleted branches.
export function assertAvailableNumber({ branch, targets, execute, root, fresh = false, hasPr = false }) {
  assertNewBranch(branch, 1);
  if (hasPr) return;
  const call = (binary, args) => execute(binary, args, root, 60_000);
  const names = new Set(call('git', ['for-each-ref', '--format=%(refname:short)', 'refs/heads']).split(/\r?\n/));
  let priorPr = false;
  for (const target of Object.values(targets)) {
    const heads = call('git', ['ls-remote', '--heads', target.remote]);
    for (const line of heads.split(/\r?\n/).filter(Boolean)) {
      const match = line.match(/^(?:[a-f0-9]{40}|[a-f0-9]{64})\s+refs\/heads\/(.+)$/i);
      if (!match) throw new Error('Invalid remote branch inventory; cannot verify unique NNN.');
      names.add(match[1]);
      if (fresh && match[1] === branch) throw new Error('New branch already exists on a publication remote.');
    }
    const pages = JSON.parse(call('gh', ['api', '--paginate', '--slurp', `repos/${target.repository}/pulls?state=all&per_page=100`]));
    if (!Array.isArray(pages) || pages.some(page => !Array.isArray(page) || page.some(pr => typeof pr.head?.ref !== 'string'))) throw new Error('Incomplete PR history; cannot verify unique NNN.');
    for (const pr of pages.flat()) { names.add(pr.head.ref); if (pr.head.ref === branch) priorPr = true; }
  }
  const number = branch.slice(5, 8);
  if ([...names].some(name => name !== branch && name.startsWith(`feat/${number}-`)) || (fresh && priorPr)) throw new Error(`Feature number ${number} was already used; select a unique NNN.`);
}

export function assertAvailableBranch({ branch, targets, execute, root, fresh = false, hasPr = false }) {
  assertNewBranch(branch);
  if (hasPr) return;
  const call = (binary, args) => execute(binary, args, root, 60_000);
  const local = call('git', ['for-each-ref', '--format=%(refname:short)', 'refs/heads']).split(/\r?\n/);
  if (fresh && local.includes(branch)) {
    const current = call('git', ['branch', '--show-current']);
    if (current !== branch) throw new Error('New branch already exists locally.');
  }
  for (const target of Object.values(targets)) {
    const heads = call('git', ['ls-remote', '--heads', target.remote]);
    for (const line of heads.split(/\r?\n/).filter(Boolean)) {
      const match = line.match(/^(?:[a-f0-9]{40}|[a-f0-9]{64})\s+refs\/heads\/(.+)$/i);
      if (!match) throw new Error('Invalid remote branch inventory; cannot verify unique branch name.');
      if (fresh && match[1] === branch) throw new Error('New branch already exists on a publication remote.');
    }
    const pages = JSON.parse(call('gh', ['api', '--paginate', '--slurp', `repos/${target.repository}/pulls?state=all&per_page=100`]));
    if (!Array.isArray(pages) || pages.some(page => !Array.isArray(page) || page.some(pr => typeof pr.head?.ref !== 'string'))) throw new Error('Incomplete PR history; cannot verify unique branch name.');
    if (pages.flat().some(pr => pr.head.ref === branch)) throw new Error('Branch name was already used by a PR; select a unique full name or restore its accounting.');
  }
}

export function assertNewSummary(summary) {
  if (!action.test(summary)) throw new Error('New PR summary must start with a clear action verb (add, fix, standardize, document, update, ...).');
}
