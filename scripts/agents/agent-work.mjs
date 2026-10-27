import {
  finishSession,
  parseArguments,
  resolveCheckout,
  startSession,
  usage,
  writeError,
  writeOutput,
} from './agent-work-session.mjs';
import { cleanupSessions, listSessions } from './agent-work-cleanup.mjs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export { withOperationLock } from './agent-work-session.mjs';

async function main() {
  let options;
  try {
    options = parseArguments(process.argv.slice(2));
    if (options.help) return writeOutput(usage);
    const checkout = await resolveCheckout(options.root);
    if (options.command === 'start') await startSession(checkout, options.date, options.session);
    else if (options.command === 'finish') await finishSession(checkout, options.session.date, options.session.id);
    else if (options.command === 'list') await listSessions(checkout);
    else await cleanupSessions(checkout, options.session, options.apply);
  } catch (error) {
    const message = error && typeof error === 'object' && 'message' in error ? error.message : String(error);
    writeError(message);
    writeError(usage);
    process.exitCode = 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
