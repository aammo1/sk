import path from "node:path";
import sharp from "sharp";
import { isDeepStrictEqual } from "node:util";
import { readCatalog, readOffer, emitCatalog, emitOffer, collectionLabels, declaration, legacyLabels, hash } from "./source.mjs";
import { ReadSet, lock, commit, assertUnblocked } from "./transaction.mjs";

const slugPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const managedPattern = /^\/images\/products\/[a-z0-9]+(?:-[a-z0-9]+)*\.webp$/;
const tags = ["promotion", "best-seller", "new", "gift"];
const fields = ["name", "tagline", "description", "fabric", "care", "price", "compareAtPrice", "collections", "tags", "crossSellIds"];

function fail(message) { throw new Error(message); }
function object(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${label}: expected object`);
}
function keys(value, allowed, label) {
  object(value, label);
  for (const key of Object.keys(value)) if (!allowed.includes(key)) fail(`${label}: unknown field ${key}`);
}
function text(value, label) { if (typeof value !== "string" || !value.trim()) fail(`${label}: expected nonempty string`); }
function integer(value, label, minimum = 0) { if (!Number.isSafeInteger(value) || value < minimum) fail(`${label}: expected safe integer >= ${minimum}`); }
function array(value, label, minimum = 0, maximum = Infinity) {
  if (!Array.isArray(value) || value.length < minimum || value.length > maximum) fail(`${label}: expected ${minimum}..${maximum} entries`);
}
function unique(values, label) { if (new Set(values).size !== values.length) fail(`${label}: duplicate entries`); }
function resolve(products, target) {
  text(target, "target");
  const matches = products.filter((p) => p.id === target || p.slug === target);
  if (matches.length !== 1) fail(`Unknown or ambiguous product target: ${target}`);
  return matches[0];
}
const imagesOf = (products) => new Set(products.flatMap((p) => p.colorVariants.flatMap((c) => c.images)));

export function validateSizes(sizes) {
  array(sizes, "sizeVariants", 1);
  for (const s of sizes) {
    keys(s, ["label", "stock"], "sizeVariant");
    text(s.label, "size.label");
    integer(s.stock, "size.stock");
  }
  unique(sizes.map((s) => s.label), "size labels");
}

export function validateCatalog(products, collections) {
  const identities = new Map();
  for (const p of products) {
    keys(p, ["id", "slug", "colorVariants", ...fields], "product");
    for (const key of ["id", "slug"]) {
      if (typeof p[key] !== "string" || !slugPattern.test(p[key])) fail(`Invalid product ${key}`);
      if (identities.has(p[key]) && identities.get(p[key]) !== p) fail(`Duplicate product identity: ${p[key]}`);
      identities.set(p[key], p);
    }
    for (const key of ["name", "tagline", "description", "fabric", "care"]) text(p[key], key);
    integer(p.price, "price", 1);
    if (p.compareAtPrice !== undefined) integer(p.compareAtPrice, "compareAtPrice", p.price + 1);
    array(p.collections, "collections", 1);
    unique(p.collections, "collections");
    if (p.collections.some((c) => !collections.includes(c))) fail("Unknown collection");
    array(p.tags, "tags");
    unique(p.tags, "tags");
    if (p.tags.some((tag) => !tags.includes(tag))) fail("Unknown tag");
    if (p.tags.includes("promotion") && (!p.compareAtPrice || Math.floor((p.compareAtPrice - p.price) * 100 / p.compareAtPrice) < 1)) fail("promotion requires a discount of at least 1%");
    array(p.crossSellIds, "crossSellIds");
    unique(p.crossSellIds, "crossSellIds");
    array(p.colorVariants, "colorVariants", 1);
    unique(p.colorVariants.map((c) => c.id), "color IDs");
    for (const c of p.colorVariants) {
      keys(c, ["id", "label", "hex", "images", "sizeVariants"], "color");
      if (typeof c.id !== "string" || !slugPattern.test(c.id)) fail("Invalid color id");
      text(c.label, "color.label");
      if (typeof c.hex !== "string" || !/^#[0-9a-f]{6}$/i.test(c.hex)) fail("Invalid color hex");
      array(c.images, "images", 1, 8);
      unique(c.images, "images");
      for (const image of c.images) {
        text(image, "image");
        if (!image.startsWith("/images/") || image.includes("\\") || image.includes("?") || image.includes("#") || path.posix.normalize(image) !== image || image.includes("\0")) fail(`Invalid image path: ${image}`);
      }
      validateSizes(c.sizeVariants);
    }
  }
  for (const p of products) for (const id of p.crossSellIds) resolve(products, id);
}

export async function load(root) {
  const readSet = new ReadSet();
  const catalogPath = path.join(root, "lib/data/products.ts");
  const configPath = path.join(root, "lib/funnel-config.ts");
  const source = (await readSet.read(catalogPath)).toString();
  const config = (await readSet.read(configPath)).toString();
  const types = (await readSet.read(path.join(root, "lib/types.ts"))).toString();
  const catalog = readCatalog(source);
  const collections = collectionLabels(types);
  validateCatalog(catalog.products, collections);
  const offer = readOffer(config);
  if (offer.active) resolve(catalog.products, offer.productId);
  return { root, readSet, catalogPath, configPath, source, config, catalog, collections, offer, revision: hash(source) };
}

export const contract = {
  schemaVersion: 1,
  commands: ["capabilities", "list", "show <id-or-slug>", "add --from <file>", "edit <id-or-slug> --from <file>", "delete <id-or-slug> [--from <file>]"],
  flags: ["--json", "--dry-run", "--yes", "--expected-revision <sha256>"],
  edit: {
    version: 1,
    expectedRevision: "optional catalog SHA-256; REQUIRED for any stock delta",
    set: Object.fromEntries(fields.map((f) => [f, f === "compareAtPrice" ? "integer > price, or null to remove" : ["collections", "tags", "crossSellIds"].includes(f) ? "final string array (empty allowed except collections)" : f === "price" ? "positive safe integer MAD" : "nonempty string"])),
    colors: {
      add: "[{id,label,hex,images,sizeVariants:[{label,stock}]}]",
      update: "[{id,label?,hex?,images?,sizeVariants?,sizes?:{add:[{label,stock}],update:[{label,stock:number|{delta:signedSafeInteger}}],remove:[exactLabel]}}]",
      remove: "[stableColorId]",
    },
  },
  delete: { version: 1, expectedRevision: "optional SHA-256", upsell: "{disable:true} OR {replaceWith:idOrSlug}; required when deleting the active target" },
  images: "Final ordered array: existing catalog '/images/...' paths or {file:absoluteLocalPath}. First image is cover. Omit preserves. Include/omit entries to add/replace/remove/reorder. 1..8 per color.",
  creation: "Legacy --from product JSON is supported. Each colorways entry accepts stock:[n,n,n] OR sizeVariants:[{label,stock}], never both. Custom labels also work on creation. photosDir is absolute; 1..8 photos, sorted lexicographically.",
  semantics: "Omit preserves; compareAtPrice:null removes; [] clears tags/crossSellIds. Other null edits are rejected. IDs/slugs immutable. Color labels do not rename IDs. Exact size labels identify targets. sizeVariants replaces all sizes; sizes applies operations; mutually exclusive. A color/size may be targeted once per request.",
  concurrency: "Catalog revision is SHA-256 of source bytes. Deltas require expectedRevision. Replays/stale revisions conflict; no durable exactly-once receipts, no blind retries. All writers share a lock and read-set checks. Incomplete journals block writes pending manual reconciliation.",
};

export async function inspect(root, command, target) {
  await assertUnblocked(root);
  const state = await load(root);
  const base = { schemaVersion: 1, revision: state.revision };
  if (command === "capabilities") return { ...contract, ...base, collections: state.collections, tags, products: state.catalog.products.map(({ id, slug, name }) => ({ id, slug, name })), upsell: { active: state.offer.active, productId: state.offer.productId } };
  if (command === "show") return { ...base, product: resolve(state.catalog.products, target) };
  if (command === "list") return { ...base, products: state.catalog.products.map(({ id, slug, name, colorVariants }) => ({ id, slug, name, colors: colorVariants.map(({ id, label, sizeVariants }) => ({ id, label, sizeVariants })) })) };
  fail(`Unknown inspection command: ${command}`);
}

function stockValue(value, current, expectedRevision) {
  if (typeof value === "number") { integer(value, "stock"); return value; }
  keys(value, ["delta"], "stock");
  if (!Object.hasOwn(value, "delta") || !Number.isSafeInteger(value.delta)) fail("stock.delta must be a signed safe integer");
  if (!expectedRevision) fail("Stock delta requires expectedRevision from show/capabilities");
  const final = current + value.delta;
  integer(final, "stock delta final value");
  return final;
}

function editSizes(color, operations, revision) {
  keys(operations, ["add", "update", "remove"], "sizes");
  const targets = new Set();
  for (const op of ["remove", "update", "add"]) {
    if (operations[op] === undefined) continue;
    array(operations[op], `sizes.${op}`);
    for (const item of operations[op]) {
      if (op !== "remove") keys(item, ["label", "stock"], `sizes.${op}`);
      const label = op === "remove" ? item : item.label;
      text(label, "size label");
      if (targets.has(label)) fail(`Repeated size target: ${label}`);
      targets.add(label);
      const existing = color.sizeVariants.find((s) => s.label === label);
      if (op === "add") {
        if (existing) fail(`Size already exists: ${label}`);
        integer(item.stock, "size stock");
        color.sizeVariants.push({ label, stock: item.stock });
      } else {
        if (!existing) fail(`Unknown size target: ${label}`);
        if (op === "remove") color.sizeVariants = color.sizeVariants.filter((s) => s !== existing);
        else existing.stock = stockValue(item.stock, existing.stock, revision);
      }
    }
  }
}

async function gallery(inputs, product, color, state, staged) {
  array(inputs, "images", 1, 8);
  const known = imagesOf(state.catalog.products);
  const output = [];
  for (const input of inputs) {
    if (typeof input === "string") {
      if (!known.has(input)) fail(`Unknown existing image: ${input}; use {file:absolutePath} for new input`);
      await state.readSet.read(path.join(state.root, "public", input));
      output.push(input);
    } else {
      keys(input, ["file"], "image input");
      if (typeof input.file !== "string" || !path.isAbsolute(input.file)) fail("image.file requires an absolute local path");
      const source = await state.readSet.read(input.file);
      const buffer = await sharp(source).autoOrient().resize({ width: 1000, height: 1250, fit: "inside", withoutEnlargement: true }).webp({ quality: 82 }).toBuffer();
      const image = `/images/products/${product.slug}-${color.id}-${hash(buffer)}-${output.length + 1}.webp`;
      const destination = path.join(state.root, "public", image);
      const existing = await state.readSet.read(destination, false);
      if (existing && !existing.equals(buffer)) fail(`Image hash collision: ${image}`);
      staged.set(destination, buffer);
      output.push(image);
    }
  }
  return output;
}

async function editProduct(product, request, state, staged) {
  keys(request, ["version", "expectedRevision", "set", "colors"], "edit");
  if (request.set !== undefined) {
    keys(request.set, fields, "set");
    for (const [key, value] of Object.entries(request.set)) {
      if (key === "compareAtPrice" && value === null) delete product[key];
      else product[key] = value;
    }
  }
  if (request.colors === undefined) return;
  keys(request.colors, ["add", "update", "remove"], "colors");
  const targets = new Set();
  for (const op of ["remove", "update", "add"]) {
    if (request.colors[op] === undefined) continue;
    array(request.colors[op], `colors.${op}`);
    for (const item of request.colors[op]) {
      if (op !== "remove") keys(item, op === "add" ? ["id", "label", "hex", "images", "sizeVariants"] : ["id", "label", "hex", "images", "sizeVariants", "sizes"], `colors.${op}`);
      const id = op === "remove" ? item : item.id;
      text(id, "color id");
      if (targets.has(id)) fail(`Repeated color target: ${id}`);
      targets.add(id);
      const existing = product.colorVariants.find((c) => c.id === id);
      if (op === "remove") {
        if (!existing) fail(`Unknown color target: ${id}`);
        product.colorVariants = product.colorVariants.filter((c) => c !== existing);
      } else if (op === "add") {
        if (existing) fail(`Color already exists: ${id}`);
        const color = structuredClone(item);
        if (!slugPattern.test(id)) fail("Invalid color id");
        color.images = await gallery(item.images, product, color, state, staged);
        product.colorVariants.push(color);
      } else {
        if (!existing) fail(`Unknown color target: ${id}`);
        for (const field of ["label", "hex", "sizeVariants"]) if (Object.hasOwn(item, field)) existing[field] = item[field];
        if (item.sizeVariants !== undefined && item.sizes !== undefined) fail("Use sizeVariants OR sizes, not both");
        if (item.sizes !== undefined) editSizes(existing, item.sizes, request.expectedRevision);
        if (item.images !== undefined) existing.images = await gallery(item.images, product, existing, state, staged);
      }
    }
  }
}

async function createProduct(raw, state, staged, prepared) {
  const { validateJsonProduct } = await import("../add-product.mjs");
  const defaults = (name, fallback) => {
    try { return state.catalog.decode(declaration(state.catalog.file, name)); } catch { return fallback; }
  };
  const imageEntries = (await state.readSet.entries(path.join(state.root, "public/images/products"))).map((e) => e.name);
  let product = prepared;
  if (!product) {
    if (Array.isArray(raw.colorways)) {
      for (const color of raw.colorways) {
        if (typeof color?.photosDir === "string" && path.isAbsolute(color.photosDir)) {
          const entries = await state.readSet.entries(color.photosDir);
          for (const entry of entries) if (/\.(jpe?g|png|webp)$/i.test(entry.name)) await state.readSet.read(path.join(color.photosDir, entry.name));
        }
      }
    }
    const checked = await validateJsonProduct(raw, {
      existing: state.catalog.products, imageEntries, collectionSlugs: state.collections,
      fabricDefault: defaults("FABRIC", "100% coton peigné, certifié OEKO-TEX®"),
      careDefault: defaults("CARE", "Lavage machine 30° — sèche-linge déconseillé"),
    });
    if (checked.errors.length) fail(checked.errors.join("\n"));
    product = checked.product;
  }
  const result = {
    id: product.slug, slug: product.slug, name: product.name, tagline: product.tagline, price: product.price,
    ...(product.compareAtPrice == null ? {} : { compareAtPrice: product.compareAtPrice }),
    colorVariants: [], collections: product.collections, crossSellIds: product.crossSellIds, tags: product.tags,
    description: product.description, fabric: product.fabricValue, care: product.careValue,
  };
  if (state.catalog.products.some((p) => p.id === result.id || p.slug === result.slug)) fail(`Product already exists: ${result.slug}`);
  for (const c of product.colorways) {
    const mono = product.colorways.length === 1 && c.id === "ecru" && c.label === "Écru";
    const color = { id: c.id, label: c.label, hex: mono ? "#F5F0E6" : c.hex, images: [], sizeVariants: c.sizeVariants ?? c.stock.map((stock, i) => ({ label: legacyLabels[i], stock })) };
    // Detect additions/removals in the photosDir while conversion/checks run.
    for (const directory of new Set(c.photos.map((photo) => path.dirname(photo)))) await state.readSet.entries(directory);
    color.images = await gallery(c.photos.map((file) => ({ file })), result, color, state, staged);
    result.colorVariants.push(color);
  }
  return result;
}

// Only previously referenced managed files are candidates. Unknown/dynamic source
// references retain candidates rather than risking a deletion. No orphan sweep.
async function cleanup(state, remaining, staged, nextSource, nextConfig) {
  const candidates = [...imagesOf(state.catalog.products)].filter((image) => managedPattern.test(image) && !imagesOf(remaining).has(image));
  if (!candidates.length) return { deleted: [], retained: [] };
  const sources = [];
  let uncertain = false;
  const ignored = new Set(["node_modules", ".git", ".next", ".turbo", "scripts", "e2e", "tests", "test-results", "playwright-report", "specs", ".opencode"]);
  async function scan(directory) {
    const entries = await state.readSet.entries(directory);
    for (const entry of entries) {
      if (ignored.has(entry.name) || entry.name.startsWith(".catalog-cli")) continue;
      const file = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) { uncertain = true; continue; }
      if (entry.isDirectory()) {
        if (file !== path.join(state.root, "public/images/products")) await scan(file);
      } else if (/\.(?:[cm]?[jt]sx?|json|css|scss|html|mdx?|ya?ml|svg|txt)$/i.test(entry.name)) {
        if (file === state.catalogPath) {
          // Catalog array references are covered by remaining; retain references in helpers/comments outside it.
          sources.push(nextSource.slice(0, readCatalog(nextSource).array.getStart()) + nextSource.slice(readCatalog(nextSource).array.end));
        } else sources.push(file === state.configPath ? nextConfig : (await state.readSet.read(file)).toString());
      }
    }
  }
  await scan(state.root);
  // The supported catalog gallery helper is the only understood dynamic construction.
  // Ignore its exact known template; retain all for any other dynamic product path.
  const combined = sources.join("\n").replaceAll("`/images/products/${slug}-${index + 1}.webp`", '"catalog helper"');
  if (combined.replace(/([`"'])\/images\/products\/[a-zA-Z0-9._%-]+\1/g, "").includes("/images/products/")) uncertain = true;
  const deleted = [], retained = [];
  for (const image of candidates) {
    const stem = path.basename(image, ".webp");
    if (uncertain || combined.includes(image) || combined.includes(path.basename(image)) || combined.includes(stem)) { retained.push(image); continue; }
    const file = path.join(state.root, "public", image);
    if (await state.readSet.read(file, false) !== null) { staged.set(file, null); deleted.push(image); }
  }
  return { deleted, retained };
}

/** Internal API: root/check/hook injection is for isolated fixtures, not CLI flags. */
export async function manage(root, command, target, request = {}, options = {}) {
  const run = async () => {
    await assertUnblocked(root);
    const state = await load(root);
    if (options.expectedSource !== undefined && options.expectedSource !== state.source) fail("Catalog revision conflict: source changed during creation interview");
    if (!["add", "edit", "delete"].includes(command)) fail(`Unknown mutation: ${command}`);
    object(request, command);
    if (command !== "add" && request.version !== 1) fail("Request version must be 1");
    const expected = options.expectedRevision ?? (command !== "add" ? request.expectedRevision : undefined);
    if (options.expectedRevision && request.expectedRevision && options.expectedRevision !== request.expectedRevision) fail("Conflicting expected revisions");
    if (expected !== undefined && (typeof expected !== "string" || expected !== state.revision)) fail("Catalog revision conflict; use show and review current state before retrying");
    request = structuredClone(request);
    if (command !== "add" && expected !== undefined) request.expectedRevision = expected;
    const products = structuredClone(state.catalog.products);
    const staged = new Map();
    let config = state.config;
    let product;
    const prunedCrossSells = [];
    if (command === "add") {
      product = await createProduct(request, state, staged, options.preparedProduct);
      products.unshift(product);
    } else {
      product = resolve(products, target);
      if (command === "edit") await editProduct(product, request, state, staged);
      else {
        keys(request, ["version", "expectedRevision", "upsell"], "delete");
        if (request.upsell !== undefined) {
          keys(request.upsell, ["disable", "replaceWith"], "upsell");
          if (Object.keys(request.upsell).length !== 1 || (Object.hasOwn(request.upsell, "disable") && request.upsell.disable !== true)) fail("upsell requires exactly {disable:true} OR {replaceWith:idOrSlug}");
        }
        const activeTarget = state.offer.active && resolve(products, state.offer.productId).id === product.id;
        if (activeTarget && request.upsell === undefined) {
          if (!options.dryRun) fail("Deleting active upsell target requires explicit upsell:{disable:true} or upsell:{replaceWith:idOrSlug}; --yes does not choose");
          return { schemaVersion: 1, dryRun: true, revision: state.revision, command, target: product.id, decisionRequired: { upsell: ["disable", "replaceWith"], currentTarget: state.offer.productId }, writes: [] };
        }
        if (request.upsell !== undefined && !activeTarget) fail("upsell decision supplied but deleted product is not the active upsell target");
        if (request.upsell?.disable) config = emitOffer(config, { active: false });
        if (Object.hasOwn(request.upsell ?? {}, "replaceWith")) {
          const replacement = resolve(products, request.upsell.replaceWith);
          if (replacement.id === product.id) fail("Upsell replacement cannot be the deleted product");
          config = emitOffer(config, { productId: replacement.id });
        }
        products.splice(products.indexOf(product), 1);
        for (const p of products) {
          const next = p.crossSellIds.filter((id) => id !== product.id && id !== product.slug);
          if (next.length !== p.crossSellIds.length) { p.crossSellIds = next; prunedCrossSells.push(p.id); }
        }
      }
    }
    validateCatalog(products, state.collections);
    const source = emitCatalog(state.source, state.catalog, products);
    if (!isDeepStrictEqual(readCatalog(source).products, products)) fail("Catalog roundtrip mismatch");
    const finalOffer = readOffer(config);
    if (finalOffer.active) resolve(products, finalOffer.productId);
    const imageCleanup = await cleanup(state, products, staged, source, config);
    const imageWrites = [...staged].filter(([, buffer]) => buffer !== null).map(([file]) => path.relative(path.join(root, "public"), file));
    if (source !== state.source) staged.set(state.catalogPath, Buffer.from(source));
    if (config !== state.config) staged.set(state.configPath, Buffer.from(config));
    const result = { schemaVersion: 1, dryRun: Boolean(options.dryRun), command, target: product.id, revision: state.revision, nextRevision: hash(source), product: command === "delete" ? null : product, prunedCrossSells, imageCleanup, imageWrites, writes: [...staged.keys()].map((file) => path.relative(root, file)) };
    if (options.dryRun) await state.readSet.assert();
    else await commit(root, state.readSet, staged, options);
    return result;
  };
  return options.dryRun ? run() : lock(root, run);
}
