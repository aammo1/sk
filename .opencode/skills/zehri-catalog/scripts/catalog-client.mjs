#!/usr/bin/env node
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const MAX_BYTES = 5 * 1024 * 1024;
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
export function configuration(env = process.env) {
  const url = new URL(env.ZEHRI_STORE_URL || "https://zehri.ma");
  if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("ZEHRI_STORE_URL must be an HTTPS origin (no credentials, path, query or fragment).");
  }
  if (!env.ZEHRI_CATALOG_KEY || env.ZEHRI_CATALOG_KEY.length < 32) throw new Error("Set ZEHRI_CATALOG_KEY (at least 32 characters).");
  return { origin: url.origin, key: env.ZEHRI_CATALOG_KEY };
}

export async function api(config, query = "", body, upload) {
  const response = await fetch(`${config.origin}/api/catalog-agent${query}`, {
    method: body || upload ? "POST" : "GET",
    headers: { Authorization: `Bearer ${config.key}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: upload ?? (body ? JSON.stringify(body) : undefined), redirect: "error", signal: AbortSignal.timeout(60_000),
  });
  let result;
  try { result = await response.json(); } catch { throw new Error(`Store returned HTTP ${response.status} without JSON.`); }
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${result.error || "Catalog request failed"}`);
  return result;
}

function mime(bytes) {
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  if (bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) return "image/png";
  if (bytes.subarray(0, 4).toString() === "RIFF" && bytes.subarray(8, 12).toString() === "WEBP") return "image/webp";
  throw new Error("Only JPG, PNG and WebP input images are supported.");
}

async function uploadImage(config, bytes, dryRun) {
  const form = new FormData();
  form.set("file", new Blob([bytes], { type: mime(bytes) }), "product-image");
  return api(config, `/upload${dryRun ? "?dryRun=1" : ""}`, undefined, form);
}

async function sourceBytes(source, baseDir) {
  if (/^https?:\/\//i.test(source)) {
    const url = new URL(source);
    if (url.protocol !== "https:" || url.username || url.password) throw new Error("Image URLs must use HTTPS without credentials.");
    // External image requests never receive the store credential.
    const response = await fetch(url, { redirect: "error", signal: AbortSignal.timeout(30_000) });
    if (!response.ok || Number(response.headers.get("content-length")) > MAX_BYTES) throw new Error("Image download failed or exceeds 5 MB.");
    const chunks = [];
    let size = 0;
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > MAX_BYTES) throw new Error("Image exceeds 5 MB.");
      chunks.push(chunk);
    }
    return Buffer.concat(chunks);
  }
  return readFile(path.resolve(baseDir, source));
}

export async function prepare(config, inputFile, outputFile) {
  const operation = JSON.parse(await readFile(inputFile, "utf8"));
  operation.requestId ??= randomUUID();
  const uploads = [];
  const output = path.resolve(outputFile);
  const imageDir = `${output}.images`;
  for (const color of operation.data?.colors ?? []) {
    color.images = await Promise.all(color.images.map(async (image, index) => {
      if (typeof image !== "string") throw new Error("Images must be paths or HTTPS URLs.");
      if (image.startsWith("/api/media/") || image.startsWith("/images/")) return image;
      const bytes = await sourceBytes(image, path.dirname(path.resolve(inputFile)));
      if (!bytes.length || bytes.length > MAX_BYTES) throw new Error("Images must be between 1 byte and 5 MB.");
      const result = await uploadImage(config, bytes, true);
      const sha256 = digest(bytes);
      await mkdir(imageDir, { recursive: true, mode: 0o700 });
      const staged = path.join(imageDir, `${sha256}-${index}`);
      await writeFile(staged, bytes, { mode: 0o600 });
      uploads.push({ file: staged, sha256, path: result.path });
      return result.path;
    }));
  }
  const result = await api(config, "", { action: "preview", operation });
  if (result.alreadyApplied) return result;
  const plan = { version: 1, origin: config.origin, operation: result.operation, preview: result.preview, uploads };
  await writeFile(output, JSON.stringify(plan, null, 2), { mode: 0o600 });
  return { plan: output, origin: config.origin, ...result };
}

export async function apply(config, planFile) {
  const plan = JSON.parse(await readFile(planFile, "utf8"));
  if (plan.version !== 1 || plan.origin !== config.origin) throw new Error("Plan version or store origin mismatch. Prepare a new preview.");
  // A lost apply response must not cause another upload or another product creation.
  const found = await api(config, `?command=receipt&requestId=${encodeURIComponent(plan.operation.requestId)}`);
  if (!found.receipt) {
    // Validate every source before the first live upload.
    const files = await Promise.all(plan.uploads.map(async upload => {
      const bytes = await readFile(upload.file);
      if (digest(bytes) !== upload.sha256) throw new Error("A staged photo changed. Prepare and approve a new preview.");
      return { upload, bytes };
    }));
    for (const { upload, bytes } of files) {
      const result = await uploadImage(config, bytes, false);
      if (result.path !== upload.path) throw new Error("Image conversion changed. Prepare and approve a new preview.");
    }
  }
  const result = await api(config, "", { action: "apply", operation: plan.operation, preview: plan.preview });
  const current = await api(config, `?command=show&target=${encodeURIComponent(result.product.id)}`);
  return { ...result, currentProduct: current.product };
}

export async function main(args = process.argv.slice(2)) {
  const [command, ...rest] = args;
  if (!command || command === "--help") {
    return { usage: [
    "catalog-client.mjs capabilities | list | show <id-or-slug> | receipt <requestId>",
      "catalog-client.mjs preview <operation.json> <plan.json>",
      "catalog-client.mjs apply <plan.json> --yes",
    ], env: ["ZEHRI_STORE_URL=https://zehri.ma", "ZEHRI_CATALOG_KEY=<runtime secret>"] };
  }
  const config = configuration();
  if (["capabilities", "list"].includes(command) && rest.length === 0) return api(config, `?command=${command}`);
  if (["show", "receipt"].includes(command) && rest.length === 1) {
    return api(config, `?command=${command}&${command === "show" ? "target" : "requestId"}=${encodeURIComponent(rest[0])}`);
  }
  if (command === "preview" && rest.length === 2) return prepare(config, ...rest);
  if (command === "apply" && rest.length === 2 && rest[1] === "--yes") return apply(config, rest[0]);
  throw new Error("Invalid command. Apply requires --yes after the user approves the preview. See --help.");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then(result => console.log(JSON.stringify(result, null, 2))).catch(error => {
    // Fetch/network error messages can contain URLs. Emit only controlled details.
    console.error(error instanceof TypeError ? "Network request failed. Check the operation receipt before retrying." : error.message);
    process.exitCode = 1;
  });
}
