import { validateOwnedPaths } from './owned-handoff.mjs';
import { samePath } from './agent-store.mjs';
import { startBinding, verifyAssignmentBinding } from './active-task-binding.mjs';

export async function reassign(entries, index, values, repo) {
  if (index === -1) throw new Error('No entry matches that owner and task.');
  const source = entries[index];
  if (!['active', 'blocked'].includes(source.status)) throw new Error('Only active or blocked assignments can be explicitly reassigned.');
  if (source.reservation) throw new Error(source.binding
    ? 'Reserved assignments cannot continue through in-place reassignment; resolve the old worker and create a fresh reservation.'
    : 'An unbound reservation cannot be reassigned; bind its actual worktree first.');
  if (values['new-owner'] === source.owner || entries.some((entry) => entry.owner === values['new-owner'] && entry.task === source.task)) throw new Error('The new owner/task assignment already exists or matches the source.');
  if (source.session && values.session === source.session) throw new Error('Reassignment requires a distinct session identity.');
  const inheritedPaths = validateOwnedPaths(source.ownedPaths ?? []);
  const suppliedPaths = validateOwnedPaths(values['owned-path'] ?? []);
  if (inheritedPaths.length && suppliedPaths.length && inheritedPaths.join('\0') !== suppliedPaths.join('\0')) throw new Error('Reassignment must retain the source owned paths.');
  const ownedPaths = inheritedPaths.length ? inheritedPaths : suppliedPaths;
  const role = values.role ?? source.role ?? 'coordinator';
  if (role === 'worker' && !ownedPaths.length) throw new Error('Reassigning a worker requires declared --owned-path values for a legacy assignment.');
  if (role === 'worker') {
    if (!source.checkout || !(await samePath(source.checkout, repo.root))) throw new Error('Worker reassignment must continue in the source checkout.');
    if (source.binding) {
      if (source.binding.base.ref !== 'existing-checkout') throw new Error('Only existing-checkout workers can continue through in-place reassignment.');
      await verifyAssignmentBinding(source, repo, repo.root);
    }
  }
  const priorStatus = source.status;
  const priorUpdatedAt = source.updatedAt;
  const reassignedAt = new Date().toISOString();
  const event = { owner: values['new-owner'], task: source.task, session: values.session, reason: values.reason, at: reassignedAt };
  const successor = {
    owner: values['new-owner'], task: source.task, checkout: source.checkout ?? repo.root,
    session: values.session, role, summary: source.summary,
    next: `Resume from checkpoint: ${source.next}. Confirm the source agent's state with the host before acting.`,
    status: 'active', verification: '', ...(ownedPaths.length ? { ownedPaths } : {}),
    reassignedFrom: { owner: source.owner, task: source.task, session: source.session ?? null, status: priorStatus, next: source.next, verification: source.verification ?? '', updatedAt: priorUpdatedAt ?? null, reason: values.reason },
    updatedAt: reassignedAt,
  };
  if (role === 'worker') {
    successor.binding = await startBinding(repo, successor);
    successor.checkout = successor.binding.checkout;
  }
  source.status = 'reassigned';
  source.reassignments = [...(Array.isArray(source.reassignments) ? source.reassignments : []), event];
  source.updatedAt = reassignedAt;
  entries.push(successor);
}

export function retireReassigned(entries, index, values) {
  if (index === -1) throw new Error('No entry matches that owner and task.');
  const source = entries[index];
  const hasRecordedReassignment = Array.isArray(source.reassignments) && source.reassignments.some((event) =>
    event && typeof event.owner === 'string' && event.task === source.task && typeof event.session === 'string' && typeof event.reason === 'string' && typeof event.at === 'string');
  if (source.status !== 'blocked' || !hasRecordedReassignment) throw new Error('Only blocked entries with a recorded reassignment can be retired as reassigned.');
  const retiredAt = new Date().toISOString();
  source.status = 'reassigned';
  source.reassignmentRetirement = { reason: values.reason, at: retiredAt };
  source.updatedAt = retiredAt;
}
