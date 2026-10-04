import { readFile, open, rename, unlink, lstat, readdir } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { hash } from "./source.mjs";

export async function bytes(file) {
  try {
    const stat = await lstat(file);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Refusing non-regular file: ${file}`);
    return await readFile(file);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}
const equal = (a, b) => a === null ? b === null : b !== null && a.equals(b);

export class ReadSet {
  files = new Map();
  directories = new Map();
  async read(file, required = true) {
    if (!this.files.has(file)) this.files.set(file, await bytes(file));
    const value = this.files.get(file);
    if (required && value === null) throw new Error(`Missing file: ${file}`);
    return value;
  }
  async entries(dir) {
    let entries;
    try {
      if ((await lstat(dir)).isSymbolicLink()) throw new Error(`Refusing symlink directory: ${dir}`);
      entries = await readdir(dir, { withFileTypes: true });
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      entries = [];
    }
    const signature = entries.map((e) => `${e.name}:${e.isDirectory() ? "d" : e.isSymbolicLink() ? "l" : "f"}`).sort().join("\n");
    this.directories.set(dir, signature);
    return entries;
  }
  async assert(except = new Set(), skipDirectories = false) {
    for (const [file, expected] of this.files) {
      if (!except.has(file) && !equal(expected, await bytes(file))) throw new Error(`Concurrent change conflict: ${file}`);
    }
    if (!skipDirectories) {
      for (const [dir, signature] of this.directories) {
        const probe = new ReadSet();
        await probe.entries(dir);
        if (probe.directories.get(dir) !== signature) throw new Error(`Concurrent directory change conflict: ${dir}`);
      }
    }
  }
}

export async function assertUnblocked(root) {
  const journal = path.join(root, ".catalog-cli.transaction.json");
  if (await bytes(journal) !== null) throw new Error(`Incomplete transaction: ${journal}. Inspect before/after snapshots and current files; reconcile manually before removing the journal. Do not retry blindly.`);
}

export async function lock(root, fn) {
  const file = path.join(root, ".catalog-cli.lock");
  let handle;
  try { handle = await open(file, "wx", 0o600); }
  catch (error) {
    if (error.code === "EEXIST") throw new Error(`Catalog CLI locked: ${file}. If its owner crashed, inspect the transaction journal before manually removing the stale lock.`);
    throw error;
  }
  const token = JSON.stringify({ pid: process.pid, token: randomUUID(), started: new Date().toISOString() });
  try {
    await handle.writeFile(token);
    await handle.sync();
    await assertUnblocked(root);
    return await fn();
  } finally {
    await handle.close();
    if ((await bytes(file))?.toString() === token) await unlink(file);
  }
}

export function productionChecks(root) {
  for (const [command, args] of [["npx", ["tsc", "--noEmit"]], ["npm", ["run", "lint"]]]) {
    const result = spawnSync(command, args, { cwd: root, encoding: "utf8" });
    if (result.error || result.status !== 0) throw new Error(`Verification failed: ${command} ${args.join(" ")}\n${result.stderr || ""}\n${result.stdout || ""}`);
  }
}

async function publish(file, value) {
  if (value === null) { await unlink(file); return; }
  const temporary = `${file}.catalog-${randomUUID()}.tmp`;
  try {
    let mode = 0o644;
    try { mode = (await lstat(file)).mode & 0o777; } catch (error) { if (error.code !== "ENOENT") throw error; }
    const handle = await open(temporary, "wx", mode);
    try { await handle.writeFile(value); await handle.sync(); } finally { await handle.close(); }
    await rename(temporary, file);
  } finally {
    try { await unlink(temporary); } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
}

// Caller holds the shared lock. Sharp buffers have already been staged in memory.
export async function commit(root, readSet, writes, { checks = productionChecks, hook = async () => {} } = {}) {
  const journalPath = path.join(root, ".catalog-cli.transaction.json");
  const changes = [];
  for (const [file, after] of writes) {
    const relative = path.relative(root, file);
    if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error(`Write outside fixture/store root: ${file}`);
    let directory = path.dirname(file);
    while (directory !== root) {
      const stat = await lstat(directory);
      if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error(`Unsafe write directory: ${directory}`);
      directory = path.dirname(directory);
    }
    const before = await readSet.read(file, false);
    if (!equal(before, after)) changes.push({ file, before, after });
  }
  if (!changes.length) return;
  await hook("beforeCommit");
  await readSet.assert();
  const journal = { version: 1, pid: process.pid, state: "pending", changes: changes.map(({ file, before, after }) => ({ file, before: before?.toString("base64") ?? null, after: after?.toString("base64") ?? null, beforeHash: before && hash(before), afterHash: after && hash(after) })) };
  const handle = await open(journalPath, "wx", 0o600);
  try { await handle.writeFile(JSON.stringify(journal, null, 2)); await handle.sync(); } finally { await handle.close(); }
  const applied = [];
  try {
    for (const change of changes) {
      if (!equal(await bytes(change.file), change.before)) throw new Error(`Concurrent write conflict: ${change.file}`);
      await publish(change.file, change.after);
      applied.push(change);
      await hook("afterWrite", change.file);
    }
    await checks(root);
    await hook("afterChecks");
    await readSet.assert(new Set(changes.map((c) => c.file)), true);
    for (const change of changes) if (!equal(await bytes(change.file), change.after)) throw new Error(`Concurrent post-write conflict: ${change.file}`);
    await unlink(journalPath);
  } catch (error) {
    const conflicts = [];
    for (const change of applied.reverse()) {
      try {
        const current = await bytes(change.file);
        if (equal(current, change.before)) continue;
        if (!equal(current, change.after)) { conflicts.push(change.file); continue; }
        await publish(change.file, change.before);
      } catch { conflicts.push(change.file); }
    }
    if (!conflicts.length) await unlink(journalPath);
    else throw new Error(`${error.message}\nIncomplete rollback; external changes retained: ${conflicts.join(", ")}. Journal: ${journalPath}`, { cause: error });
    throw error;
  }
}
