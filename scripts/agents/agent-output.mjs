import { lstat, open, realpath } from 'node:fs/promises';
import { realpathSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { TextDecoder } from 'node:util';
import { fileURLToPath } from 'node:url';
import {
  assertDirectoryStat,
  existingManagedRoot,
  idPattern,
  managedRootPath,
  readManifest,
  reservedWindowsNamePattern,
  statOrNull,
  validateDate,
} from './agent-work-session.mjs';
import { atomicWrite, inside, repository, samePath } from './agent-store.mjs';

const maxInputBytes = 256 * 1024;
const maxTailBytes = 16 * 1024;
const maxTailLines = 100;
const usage = `Usage:
  node scripts/agents/agent-output.mjs --workspace <checkout> --session <date/id> --output <file.json> [--log <file>]

Read one UTF-8 JSON object from stdin, write it into the active session, and print a JSON receipt.
The optional log tail is limited to ${maxTailBytes} bytes and ${maxTailLines} lines.`;

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function parseArguments(argv) {
  if (argv.length === 1 && ['--help', '-h'].includes(argv[0])) return { help: true };
  const values = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const option = argv[index];
    if (!['--workspace', '--session', '--output', '--log'].includes(option)) {
      throw new Error(`Unknown option or positional argument: ${option}`);
    }
    if (values.has(option)) throw new Error(`Duplicate option: ${option}`);
    const value = argv[index + 1];
    if (typeof value !== 'string' || value.length === 0 || value.startsWith('--')) {
      throw new Error(`${option} requires a value`);
    }
    values.set(option, value);
    index += 1;
  }
  for (const required of ['--workspace', '--session', '--output']) {
    if (!values.has(required)) throw new Error(`Missing required option: ${required}`);
  }
  return {
    workspace: values.get('--workspace'),
    session: values.get('--session'),
    output: validateFileName(values.get('--output'), true),
    log: values.has('--log') ? validateFileName(values.get('--log')) : null,
  };
}

function validateFileName(value, json = false) {
  const pattern = json ? /^[A-Za-z0-9][A-Za-z0-9._-]{0,122}\.json$/i : /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
  const deviceName = value.split('.')[0];
  if (!pattern.test(value) || value === '.' || value === '..' || reservedWindowsNamePattern.test(deviceName)) {
    throw new Error(`Invalid session file name: ${value}`);
  }
  return value;
}

function parseSession(value) {
  if (typeof value !== 'string') throw new Error('Session must use <date>/<id> form');
  const segments = value.split('/');
  if (segments.length !== 2) throw new Error('Session must use <date>/<id> form');
  if (!idPattern.test(segments[1]) || reservedWindowsNamePattern.test(segments[1])) {
    throw new Error('Invalid session ID');
  }
  return { date: validateDate(segments[0]), id: segments[1] };
}

async function readInput() {
  const chunks = [];
  let byteLength = 0;
  for await (const chunk of process.stdin) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    byteLength += bytes.length;
    if (byteLength > maxInputBytes) throw new Error(`JSON input exceeds ${maxInputBytes} bytes`);
    chunks.push(bytes);
  }
  if (byteLength === 0) throw new Error('Expected one UTF-8 JSON object on stdin');
  const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(Buffer.concat(chunks));
  if (text.startsWith('\uFEFF')) throw new Error('JSON input must not start with a UTF-8 BOM');
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error('Invalid JSON input');
  }
  if (!isObject(value)) throw new Error('JSON input must be an object');
  validateExitObservation(value.exitObservation);
  return value;
}

function validateExitObservation(value) {
  if (value === undefined) return;
  if (!isObject(value) || Object.keys(value).some((key) => !['code', 'signal'].includes(key))) {
    throw new Error('exitObservation must contain only code and signal');
  }
  if ('code' in value && value.code !== null && !Number.isSafeInteger(value.code)) {
    throw new Error('exitObservation.code must be a safe integer or null');
  }
  if ('signal' in value && value.signal !== null && (typeof value.signal !== 'string' || value.signal.length > 64)) {
    throw new Error('exitObservation.signal must be a string of at most 64 characters or null');
  }
}

async function assertRealDirectory(parent, path, label) {
  if (!inside(parent, path)) throw new Error(`${label} escapes its managed parent`);
  assertDirectoryStat(await statOrNull(path), path, label);
  if (!(await samePath(path, await realpath(path)))) throw new Error(`${label} resolves outside its exact workspace path`);
}

async function resolveSessionDirectory(root, value) {
  const { date, id } = parseSession(value);
  const managedRoot = await existingManagedRoot(root);
  if (!managedRoot) throw new Error('Managed work root does not exist');
  const dateDirectory = join(managedRoot, date);
  await assertRealDirectory(managedRoot, dateDirectory, 'Session date directory');
  const sessionDirectory = join(dateDirectory, id);
  await assertRealDirectory(managedRoot, sessionDirectory, 'Session directory');
  const manifest = await readManifest(sessionDirectory, date, id);
  if (manifest.status !== 'active') throw new Error('Session must be active before writing output');
  return sessionDirectory;
}

function boundUtf8(text, limit) {
  const bytes = Buffer.from(text, 'utf8');
  if (bytes.length <= limit) return text;
  let start = bytes.length - limit;
  while (start < bytes.length && (bytes[start] & 0xc0) === 0x80) start += 1;
  return bytes.subarray(start).toString('utf8');
}

async function namedLogIo(file, operation) {
  try {
    return await operation();
  } catch (error) {
    if (error?.code === 'ENOENT') throw new Error(`Log file not found in session: ${file}`, { cause: error });
    throw error;
  }
}

async function readLogTail(sessionDirectory, file) {
  const path = join(sessionDirectory, file);
  if (!inside(sessionDirectory, path)) throw new Error('Log path escapes its session');
  const linkStat = await namedLogIo(file, () => lstat(path));
  if (!linkStat.isFile() || linkStat.isSymbolicLink()) throw new Error('Log must be a regular file');
  if (!(await samePath(path, await namedLogIo(file, () => realpath(path))))) throw new Error('Log path resolves outside its session');
  const handle = await namedLogIo(file, () => open(path, 'r'));
  try {
    const fileStat = await handle.stat();
    if (!fileStat.isFile() || fileStat.dev !== linkStat.dev || fileStat.ino !== linkStat.ino) {
      throw new Error('Log file changed while it was being opened');
    }
    const offset = Math.max(0, fileStat.size - maxTailBytes);
    const buffer = Buffer.alloc(fileStat.size - offset);
    const { bytesRead } = buffer.length > 0
      ? await handle.read(buffer, 0, buffer.length, offset)
      : { bytesRead: 0 };
    let start = 0;
    if (offset > 0) {
      while (start < bytesRead && (buffer[start] & 0xc0) === 0x80) start += 1;
    }
    let text = new TextDecoder('utf-8').decode(buffer.subarray(start, bytesRead));
    let truncated = offset > 0;
    if (offset > 0) {
      const newline = text.search(/[\r\n]/);
      if (newline >= 0) {
        text = text.slice(newline + (text.startsWith('\r\n', newline) ? 2 : 1));
      }
    }
    const endsWithNewline = /[\r\n]$/.test(text);
    let lines = text.split(/\r\n|\n|\r/);
    if (endsWithNewline) lines.pop();
    if (lines.length > maxTailLines) {
      lines = lines.slice(-maxTailLines);
      truncated = true;
    }
    let tail = lines.join('\n');
    if (endsWithNewline && tail.length > 0) tail += '\n';
    const unboundedTailBytes = Buffer.byteLength(tail, 'utf8');
    tail = boundUtf8(tail, maxTailBytes);
    return {
      file,
      fileBytes: fileStat.size,
      tailBytes: Buffer.byteLength(tail, 'utf8'),
      tailLines: tail.length === 0 ? 0 : tail.split('\n').length - Number(tail.endsWith('\n')),
      truncated: truncated || unboundedTailBytes > Buffer.byteLength(tail, 'utf8'),
      tail,
    };
  } finally {
    await handle.close();
  }
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(`${usage}\n`);
    return;
  }
  const input = await readInput();
  const repo = await repository(resolve(options.workspace));
  const sessionDirectory = await resolveSessionDirectory(repo.root, options.session);
  const log = options.log ? await readLogTail(sessionDirectory, options.log) : null;
  await assertRealDirectory(managedRootPath(repo.root), sessionDirectory, 'Session directory');
  const outputPath = join(sessionDirectory, options.output);
  if (!inside(sessionDirectory, outputPath)) throw new Error('Output path escapes its session');
  const content = `${JSON.stringify(input, null, 2)}\n`;
  await atomicWrite(outputPath, content, { exclusive: true });
  process.stdout.write(`${JSON.stringify({
    status: 'written',
    output: options.output,
    bytes: Buffer.byteLength(content, 'utf8'),
    exitObservation: input.exitObservation ?? null,
    log,
  })}\n`);
}

if (process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
