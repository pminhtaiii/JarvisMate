export const sides = ['primary', 'submission'];

export function command(call, args, repo, timeout = 30_000) {
  const result = call('gh', args, repo.root, timeout);
  return typeof result === 'string' ? result.trim() : String(result?.stdout ?? '').trim();
}

export function json(call, args, repo, description) {
  try { return JSON.parse(command(call, args, repo)); }
  catch (error) { throw new Error(`Could not read ${description}: ${error.message}`, { cause: error }); }
}

export function pages(output, description) {
  let parsed;
  try { parsed = JSON.parse(output); }
  catch { throw new Error(`GitHub returned invalid ${description} JSON.`); }
  if (!Array.isArray(parsed) || parsed.some((page) => !Array.isArray(page))) throw new Error(`Could not confirm complete ${description} pagination.`);
  return parsed.flat();
}
