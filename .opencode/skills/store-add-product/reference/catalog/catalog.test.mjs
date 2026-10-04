import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, readFile, readdir, rm, access, symlink } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import sharp from "sharp";
import { manage, inspect } from "./manager.mjs";
import { readCatalog, hash } from "./source.mjs";
import { lock } from "./transaction.mjs";
import { runManagementCli } from "./cli.mjs";
import { buildProductBlock, listPhotos, processProductImage, slugify } from "../add-product.mjs";

const helpers = `import type { Product, ColorVariant, SizeVariant, SizeLabel } from "../types";
export const FABRIC = "Cotton";
export const CARE = "Wash cold";
const DEFAULT_PHOTO_COUNT = 4;
export function variants(stock0: number, stock3: number, stock6: number): SizeVariant[] {
  const stock: Record<SizeLabel, number> = { "0-3 mois": stock0, "3-6 mois": stock3, "6-9 mois": stock6, };
  return (Object.keys(stock) as SizeLabel[]).map((label) => ({ label, stock: stock[label] }));
}
function images(slug: string, count = DEFAULT_PHOTO_COUNT): string[] {
  return Array.from({ length: count }, (_, index) => \`/images/products/\${slug}-\${index + 1}.webp\`);
}
export function defaultColorway(slug: string, stock: SizeVariant[], imageCount = DEFAULT_PHOTO_COUNT,): ColorVariant {
  return { id: "ecru", label: "Écru", hex: "#F5F0E6", images: images(slug, imageCount), sizeVariants: stock, };
}
// header untouched
export const PRODUCTS: Product[] = [
`;
function product(id, overrides = {}) {
  return { id, slug: id, name: id, tagline: "Soft", price: 100, compareAtPrice: 150, colorVariants: [{ id: "ecru", label: "Écru", hex: "#F5F0E6", images: [`/images/products/${id}-1.webp`, `/images/products/${id}-2.webp`], sizeVariants: [{ label: "0-3 mois", stock: 4 }, { label: "3-6 mois", stock: 5 }, { label: "6-9 mois", stock: 6 }] }], collections: ["naissance"], crossSellIds: [], tags: ["promotion"], description: "Description", fabric: "Cotton", care: "Wash cold", ...overrides };
}
const checks = async () => {};
async function fixture(t, { helper = false, shared = false } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "catalog-cli-fixture-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (const directory of ["lib/data", "public/images/products", "photos", "app", "components"]) await mkdir(path.join(root, directory), { recursive: true });
  const first = product("alpha", { slug: "alpha-slug", crossSellIds: ["beta"] });
  const second = product("beta", { crossSellIds: ["alpha", "alpha-slug"] });
  if (shared) second.colorVariants[0].images = [first.colorVariants[0].images[0]];
  const third = product("gamma");
  let firstSource = JSON.stringify(first, null, 2);
  if (helper) {
    firstSource = firstSource.replace(JSON.stringify(first.colorVariants, null, 2).split("\n").join("\n  "), '[defaultColorway("alpha", variants(4, 5, 6), 2)]');
    // Build directly so this fixture exercises all whitelisted helper calls.
    firstSource = `{id:"alpha",slug:"alpha-slug",name:"alpha",tagline:"Soft",price:100,compareAtPrice:150,colorVariants:[defaultColorway("alpha",variants(4,5,6),2)],collections:["naissance"],crossSellIds:["beta"],tags:["promotion"],description:"Description",fabric:FABRIC,care:CARE}`;
  }
  const source = helpers + firstSource + ",\n// between products must remain\n" + JSON.stringify(second, null, 2) + ",\n" + JSON.stringify(third, null, 2) + ",\n];\n// footer untouched\nexport const unrelated = 42;\n";
  const catalog = path.join(root, "lib/data/products.ts");
  const config = path.join(root, "lib/funnel-config.ts");
  await writeFile(catalog, source);
  await writeFile(config, 'export const UPSELL_OFFER = {\n  active: true, // keep active comment\n  productId: "alpha-slug",\n  discountPct: 25, // untouched\n  countdownSeconds: 15,\n  futureSetting: someExpression(),\n} as const;\n');
  await writeFile(path.join(root, "lib/types.ts"), 'export type CollectionSlug = "fille" | "garcon" | "naissance" | "accessoires";\n');
  for (const p of [first, second, third]) for (const image of p.colorVariants[0].images) await writeFile(path.join(root, "public", image), `original bytes ${image}`);
  await writeFile(path.join(root, "public/images/products/orphan.webp"), "never sweep");
  await sharp({ create: { width: 20, height: 30, channels: 3, background: "red" } }).png().toFile(path.join(root, "photos/01.png"));
  await sharp({ create: { width: 30, height: 20, channels: 3, background: "blue" } }).jpeg().toFile(path.join(root, "photos/02.jpg"));
  const mutation = (command, target, request, options = {}) => manage(root, command, target, request, { checks, ...options });
  return { root, catalog, config, source, mutation, show: (target = "alpha") => inspect(root, "show", target) };
}
async function tree(root) {
  const result = {};
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(file);
      else result[path.relative(root, file)] = (await readFile(file)).toString("base64");
    }
  }
  await walk(root);
  return result;
}
function createInput(root, extra = {}) {
  return { name: "Nouveau Cœur", slug: "nouveau-coeur", tagline: "Douceur", price: 200, collections: ["naissance"], description: "Une description.", colorways: [{ label: "Bleu", photosDir: path.join(root, "photos"), hex: "#123456", sizeVariants: [{ label: "12–18 mois", stock: 7 }, { label: "Taille unique", stock: 0 }] }], ...extra };
}
const colorUpdate = (update, expectedRevision) => ({ version: 1, ...(expectedRevision ? { expectedRevision } : {}), colors: { update: [{ id: "ecru", ...update }] } });

test("inspection, AST helpers, immutable source, and dry-run edit", async (t) => {
  const f = await fixture(t, { helper: true });
  const before = await tree(f.root);
  const show = await f.show("alpha-slug");
  assert.equal(show.revision, hash(f.source));
  assert.deepEqual(show.product.colorVariants[0].sizeVariants.map((s) => s.stock), [4, 5, 6]);
  assert.equal((await inspect(f.root, "capabilities")).schemaVersion, 1);
  assert.equal((await inspect(f.root, "list")).products.length, 3);
  const preview = await f.mutation("edit", "alpha", { version: 1, set: { name: 'A "quote"\nbackslash \\ and \u2028 separator' } }, { dryRun: true });
  assert.equal(preview.product.slug, "alpha-slug");
  assert.deepEqual(await tree(f.root), before);
  await f.mutation("edit", "alpha", { version: 1, set: { name: preview.product.name } });
  const after = await readFile(f.catalog, "utf8");
  assert.ok(after.startsWith(helpers));
  assert.ok(after.includes('// between products must remain\n' + JSON.stringify(product("beta", { crossSellIds: ["alpha", "alpha-slug"] }), null, 2)));
  assert.ok(after.endsWith('// footer untouched\nexport const unrelated = 42;\n'));
  assert.deepEqual((await f.show()).product, { ...show.product, name: preview.product.name });
});

test("full add dry-run and custom-size creation; old stock triplet remains valid", async (t) => {
  const f = await fixture(t);
  const before = await tree(f.root);
  const input = createInput(f.root);
  const preview = await f.mutation("add", undefined, input, { dryRun: true });
  assert.deepEqual(await tree(f.root), before);
  assert.equal(preview.product.colorVariants[0].sizeVariants[0].label, "12–18 mois");
  const added = await f.mutation("add", undefined, input);
  assert.equal(readCatalog(await readFile(f.catalog, "utf8")).products[0].id, input.slug);
  assert.deepEqual((await f.show(input.slug)).product, added.product);
  const image = added.product.colorVariants[0].images[0];
  assert.equal((await sharp(path.join(f.root, "public", image)).metadata()).format, "webp");
  const legacy = createInput(f.root, { slug: "old-triplet", colorways: [{ label: "Écru", photosDir: path.join(f.root, "photos"), stock: [0, 2, 3] }] });
  const result = await f.mutation("add", undefined, legacy);
  assert.deepEqual(result.product.colorVariants[0].sizeVariants.map((s) => s.stock), [0, 2, 3]);
  assert.equal(result.product.colorVariants[0].hex, "#F5F0E6");
});

test("partial text edits, explicit optional removal and final validation", async (t) => {
  const f = await fixture(t);
  const old = (await f.show()).product;
  const changed = await f.mutation("edit", "alpha", { version: 1, set: { fabric: "Wool", care: "Hand wash", price: 90, compareAtPrice: null, tags: [], crossSellIds: [], collections: ["fille"] } });
  assert.equal(changed.product.description, old.description);
  assert.equal(changed.product.compareAtPrice, undefined);
  assert.deepEqual(changed.product.colorVariants, old.colorVariants);
  await assert.rejects(f.mutation("edit", "alpha", { version: 1, set: { tags: ["promotion"] } }), /promotion/);
  await assert.rejects(f.mutation("edit", "alpha", { version: 1, set: { fabric: null } }), /fabric/);
});

test("unknown fields/targets, immutable IDs and invalid final values reject without changes", async (t) => {
  const f = await fixture(t);
  const before = await tree(f.root);
  const invalid = [
    { version: 2 }, { version: 1, typo: 1 }, { version: 1, set: { slug: "rename" } },
    { version: 1, set: { price: Number.MAX_SAFE_INTEGER + 1 } },
    { version: 1, set: { crossSellIds: ["missing"] } },
    { version: 1, colors: { remove: ["missing"] } },
    { version: 1, colors: { remove: ["ecru"] } },
    colorUpdate({ sizes: { remove: ["0-3 mois", "3-6 mois", "6-9 mois"] } }),
    colorUpdate({ sizes: { update: [{ label: "missing", stock: 1 }] } }),
    colorUpdate({ images: [] }), colorUpdate({ images: ["/images/products/missing.webp"] }),
    colorUpdate({ images: Array(9).fill("/images/products/alpha-1.webp") }),
    colorUpdate({ sizeVariants: [{ label: "X", stock: 1 }], sizes: {} }),
    colorUpdate({ sizeVariants: [{ label: "X", stock: -1 }] }),
    colorUpdate({ sizeVariants: [{ label: "X", stock: 1, typo: true }] }),
  ];
  for (const request of invalid) await assert.rejects(f.mutation("edit", "alpha", request));
  await assert.rejects(f.mutation("delete", "missing", { version: 1 }));
  await assert.rejects(f.mutation("add", undefined, createInput(f.root, { surprise: true })));
  const both = createInput(f.root);
  both.colorways[0].stock = [1, 2, 3];
  await assert.rejects(f.mutation("add", undefined, both), /stock OU sizeVariants/);
  assert.deepEqual(await tree(f.root), before);
});

test("colors and arbitrary sizes add/update/remove; labels keep stable color identifiers", async (t) => {
  const f = await fixture(t);
  await f.mutation("edit", "alpha", colorUpdate({ label: "Renamed Écru", hex: "#112233", sizes: { add: [{ label: "XXL / adulte", stock: 9 }], update: [{ label: "0-3 mois", stock: 0 }], remove: ["6-9 mois"] } }));
  const updated = (await f.show()).product.colorVariants[0];
  assert.equal(updated.id, "ecru");
  assert.equal(updated.label, "Renamed Écru");
  assert.deepEqual(updated.sizeVariants, [{ label: "0-3 mois", stock: 0 }, { label: "3-6 mois", stock: 5 }, { label: "XXL / adulte", stock: 9 }]);
  await f.mutation("edit", "alpha", { version: 1, colors: { add: [{ id: "blue", label: "Blue", hex: "#0000FF", images: [{ file: path.join(f.root, "photos/01.png") }], sizeVariants: [{ label: "One", stock: 1 }] }], remove: ["ecru"] } });
  assert.equal((await f.show()).product.colorVariants[0].id, "blue");
  await f.mutation("edit", "alpha", { version: 1, colors: { update: [{ id: "blue", sizeVariants: [{ label: "All", stock: 3 }] }] } });
  assert.equal((await f.show()).product.colorVariants[0].sizeVariants[0].label, "All");
});

test("absolute stocks and guarded signed deltas reject stale/replay/underflow/overflow", async (t) => {
  const f = await fixture(t);
  const delta = (amount, revision) => colorUpdate({ sizes: { update: [{ label: "0-3 mois", stock: { delta: amount } }] } }, revision);
  await assert.rejects(f.mutation("edit", "alpha", delta(1)), /requires expectedRevision/);
  const revision = (await f.show()).revision;
  const request = delta(-2, revision);
  await f.mutation("edit", "alpha", request);
  assert.equal((await f.show()).product.colorVariants[0].sizeVariants[0].stock, 2);
  await assert.rejects(f.mutation("edit", "alpha", request), /revision conflict/);
  let current = (await f.show()).revision;
  await assert.rejects(f.mutation("edit", "alpha", delta(-3, current)), /safe integer/);
  await assert.rejects(f.mutation("edit", "alpha", delta(Number.MAX_SAFE_INTEGER, current)), /safe integer/);
  await f.mutation("edit", "alpha", delta(3, current));
  current = (await f.show()).revision;
  await f.mutation("edit", "alpha", colorUpdate({ sizes: { update: [{ label: "0-3 mois", stock: 8 }] } }, current));
  assert.equal((await f.show()).product.colorVariants[0].sizeVariants[0].stock, 8);
  await assert.rejects(f.mutation("edit", "alpha", { version: 1, expectedRevision: revision, set: { name: "Stale" } }), /revision conflict/);
});

test("image reorder/cover preserves paths, replacement versions content, cleanup retains shared/orphans", async (t) => {
  const f = await fixture(t, { shared: true });
  const original = (await f.show()).product.colorVariants[0].images;
  await f.mutation("edit", "alpha", colorUpdate({ images: [...original].reverse() }));
  assert.deepEqual((await f.show()).product.colorVariants[0].images, [...original].reverse());
  const changed = await f.mutation("edit", "alpha", colorUpdate({ images: [{ file: path.join(f.root, "photos/01.png") }] }));
  const first = changed.product.colorVariants[0].images[0];
  assert.match(first, /-[0-9a-f]{64}-1\.webp$/);
  assert.deepEqual(changed.imageCleanup.deleted, [original[1]]);
  await access(path.join(f.root, "public", original[0]));
  await assert.rejects(access(path.join(f.root, "public", original[1])));
  const replacement = await f.mutation("edit", "alpha", colorUpdate({ images: [{ file: path.join(f.root, "photos/02.jpg") }] }));
  assert.notEqual(replacement.product.colorVariants[0].images[0], first);
  await assert.rejects(access(path.join(f.root, "public", first)));
  assert.equal(await readFile(path.join(f.root, "public/images/products/orphan.webp"), "utf8"), "never sweep");
});

test("cleanup keeps source references and uncertain dynamic image references", async (t) => {
  const f = await fixture(t);
  await writeFile(path.join(f.root, "components/banner.ts"), 'export const banner = "/images/products/alpha-1.webp";');
  let result = await f.mutation("edit", "alpha", colorUpdate({ images: ["/images/products/alpha-2.webp"] }));
  assert.deepEqual(result.imageCleanup.retained, ["/images/products/alpha-1.webp"]);
  await writeFile(path.join(f.root, "app/dynamic.ts"), 'const prefix = "/images/products/"; export const src = prefix + name;');
  result = await f.mutation("edit", "alpha", colorUpdate({ images: [{ file: path.join(f.root, "photos/01.png") }] }));
  assert.deepEqual(result.imageCleanup.retained, ["/images/products/alpha-2.webp"]);
});

test("delete dry-run reports explicit upsell decision; disable prunes id/slug cross-sells and preserves config", async (t) => {
  const f = await fixture(t);
  const before = await tree(f.root);
  const decision = await f.mutation("delete", "alpha", { version: 1 }, { dryRun: true });
  assert.deepEqual(decision.decisionRequired.upsell, ["disable", "replaceWith"]);
  assert.deepEqual(decision.writes, []);
  assert.deepEqual(await tree(f.root), before);
  await assert.rejects(f.mutation("delete", "alpha", { version: 1 }), /explicit upsell/);
  const request = { version: 1, upsell: { disable: true } };
  await f.mutation("delete", "alpha", request, { dryRun: true });
  assert.deepEqual(await tree(f.root), before);
  const result = await f.mutation("delete", "alpha", request);
  assert.deepEqual(result.prunedCrossSells, ["beta"]);
  assert.deepEqual((await f.show("beta")).product.crossSellIds, []);
  await assert.rejects(f.show("alpha"), /Unknown/);
  const config = await readFile(f.config, "utf8");
  assert.equal(config, Buffer.from(before["lib/funnel-config.ts"], "base64").toString().replace("active: true", "active: false"));
  assert.ok((await readFile(f.catalog, "utf8")).includes("// between products must remain"));
});

test("upsell replace validates targets, preserves settings, delete last array element", async (t) => {
  const f = await fixture(t);
  for (const upsell of [{ replaceWith: "missing" }, { replaceWith: "alpha-slug" }, { disable: false }, { disable: true, replaceWith: "beta" }, {}]) await assert.rejects(f.mutation("delete", "alpha", { version: 1, upsell }));
  const previous = await readFile(f.config, "utf8");
  await f.mutation("delete", "alpha", { version: 1, upsell: { replaceWith: "beta" } });
  assert.equal(await readFile(f.config, "utf8"), previous.replace('productId: "alpha-slug"', 'productId: "beta"'));
  await assert.rejects(f.mutation("delete", "gamma", { version: 1, upsell: { disable: true } }), /not the active/);
  await f.mutation("delete", "gamma", { version: 1 });
  assert.equal((await inspect(f.root, "list")).products.length, 1);
  await f.mutation("delete", "beta", { version: 1, upsell: { disable: true } });
  assert.equal((await inspect(f.root, "list")).products.length, 0);
});

test("unsupported TypeScript and modified helper semantics reject without execution", async (t) => {
  const f = await fixture(t, { helper: true });
  const variants = [
    f.source.replace('fabric:FABRIC', 'fabric:(globalThis.catalogExploit = "oops")'),
    f.source.replace('variants(4,5,6)', 'unknown(4,5,6)'),
    f.source.replace('stock: stock[label]', 'stock: 999'),
    f.source.replace('DEFAULT_PHOTO_COUNT = 4', 'DEFAULT_PHOTO_COUNT = 8'),
    f.source.replace('price:100', 'price:100, price:200'),
    f.source.replace('fabric:FABRIC', '...spread'),
  ];
  for (const source of variants) {
    await writeFile(f.catalog, source);
    await assert.rejects(f.mutation("edit", "alpha", { version: 1, set: { name: "Never" } }));
    assert.equal(await readFile(f.catalog, "utf8"), source);
  }
  assert.equal(globalThis.catalogExploit, undefined);
});

test("handled check/write failures restore exact catalog/config/image bytes", async (t) => {
  const f = await fixture(t);
  const before = await tree(f.root);
  await assert.rejects(f.mutation("delete", "alpha", { version: 1, upsell: { disable: true } }, { checks: async () => { throw new Error("fixture check failed"); } }), /fixture check failed/);
  assert.deepEqual(await tree(f.root), before);
  await assert.rejects(f.mutation("edit", "alpha", colorUpdate({ images: [{ file: path.join(f.root, "photos/01.png") }] }), { hook: async (stage) => { if (stage === "afterWrite") throw new Error("fixture publish failed"); } }), /fixture publish failed/);
  assert.deepEqual(await tree(f.root), before);
  await assert.rejects(f.mutation("add", undefined, createInput(f.root), { checks: async () => { throw new Error("add failed"); } }), /add failed/);
  assert.deepEqual(await tree(f.root), before);
});

test("concurrent read-set edits conflict before publication and external changes survive rollback", async (t) => {
  const f = await fixture(t);
  const external = f.source + "// external edit\n";
  await assert.rejects(f.mutation("edit", "alpha", { version: 1, set: { name: "Ours" } }, { hook: async (stage) => { if (stage === "beforeCommit") await writeFile(f.catalog, external); } }), /Concurrent change conflict/);
  assert.equal(await readFile(f.catalog, "utf8"), external);
  await assert.rejects(f.mutation("edit", "alpha", { version: 1, set: { name: "Ours again" } }, { checks: async () => { await writeFile(f.catalog, external + "// external during check\n"); throw new Error("check failure"); } }), /Incomplete rollback/);
  assert.equal(await readFile(f.catalog, "utf8"), external + "// external during check\n");
  const journal = JSON.parse(await readFile(path.join(f.root, ".catalog-cli.transaction.json"), "utf8"));
  assert.equal(journal.version, 1);
  assert.equal(Buffer.from(journal.changes[0].before, "base64").toString(), external);
  await assert.rejects(f.mutation("edit", "alpha", { version: 1 }), /Incomplete transaction/);
});

test("shared lock blocks creation/edit/delete and legacy prepared creation detects stale interview", async (t) => {
  const f = await fixture(t);
  await lock(f.root, async () => {
    await assert.rejects(f.mutation("edit", "alpha", { version: 1 }), /locked/);
    await assert.rejects(f.mutation("add", undefined, createInput(f.root)), /locked/);
    await assert.rejects(f.mutation("delete", "gamma", { version: 1 }), /locked/);
  });
  await assert.rejects(f.mutation("add", undefined, {}, { expectedSource: "stale interview", preparedProduct: {} }), /source changed/);
});

test("source-reference changes and new files during cleanup conflict", async (t) => {
  const f = await fixture(t);
  const before = await readFile(f.catalog);
  await assert.rejects(f.mutation("edit", "alpha", colorUpdate({ images: ["/images/products/alpha-2.webp"] }), { hook: async (stage) => { if (stage === "beforeCommit") await writeFile(path.join(f.root, "app/new.ts"), 'const image = "/images/products/alpha-1.webp";'); } }), /directory change conflict/);
  assert.deepEqual(await readFile(f.catalog), before);
  await access(path.join(f.root, "public/images/products/alpha-1.webp"));
});

test("Sharp failures publish nothing and symlink image writes are refused", async (t) => {
  const f = await fixture(t);
  await writeFile(path.join(f.root, "photos/broken.png"), "not an image");
  const before = await tree(f.root);
  await assert.rejects(f.mutation("edit", "alpha", colorUpdate({ images: [{ file: path.join(f.root, "photos/broken.png") }] })));
  assert.deepEqual(await tree(f.root), before);
  await rm(path.join(f.root, "public/images/products"), { recursive: true });
  await symlink(path.join(f.root, "photos"), path.join(f.root, "public/images/products"));
  await assert.rejects(f.mutation("edit", "alpha", colorUpdate({ images: [{ file: path.join(f.root, "photos/01.png") }] })), /symlink|Unsafe/);
});

test("CLI JSON commands exercise add/edit/delete dry-runs and --yes never invents upsell decision", async (t) => {
  const f = await fixture(t);
  const output = [];
  t.mock.method(console, "log", (line) => output.push(JSON.parse(line)));
  const input = path.join(f.root, "request.json");
  await writeFile(input, JSON.stringify(createInput(f.root)));
  const before = await tree(f.root);
  await runManagementCli(f.root, ["--from", input, "--dry-run", "--json"], { checks });
  assert.equal(output.at(-1).command, "add");
  assert.deepEqual(await tree(f.root), before);
  await runManagementCli(f.root, ["add", "--from", input, "--yes", "--json"], { checks });
  await writeFile(input, JSON.stringify({ version: 1, set: { name: "Edited CLI" } }));
  await runManagementCli(f.root, ["edit", "nouveau-coeur", "--from", input, "--yes", "--json"], { checks });
  assert.equal(output.at(-1).product.name, "Edited CLI");
  await runManagementCli(f.root, ["show", "nouveau-coeur", "--json"], { checks });
  assert.equal(output.at(-1).product.name, "Edited CLI");
  await runManagementCli(f.root, ["delete", "alpha", "--dry-run", "--json"], { checks });
  assert.ok(output.at(-1).decisionRequired);
  await assert.rejects(runManagementCli(f.root, ["delete", "alpha", "--yes", "--json"], { checks }), /explicit upsell/);
  await runManagementCli(f.root, ["delete", "nouveau-coeur", "--yes", "--json"], { checks });
  assert.equal(output.at(-1).product, null);
  await assert.rejects(runManagementCli(f.root, ["list", "--dry-run"], { checks }), /Mutation flags/);
  await assert.rejects(runManagementCli(f.root, ["edit", "alpha", "--from", input, "--skip-checks"], { checks }), /Unknown flag/);
});

test("legacy exported helpers retain gallery syntax and process real photos", async (t) => {
  const f = await fixture(t);
  assert.equal(slugify("Écru à cœurs rouges"), "ecru-a-coeurs-rouges");
  assert.equal((await listPhotos(path.join(f.root, "photos"))).photos.length, 2);
  for (const count of [1, 4, 8]) {
    const p = { slug: "sample", name: "Quote\n\" \\", tagline: "Tag", price: 1, compareAtPrice: null, colorways: [{ id: "ecru", label: "Écru", hex: "#FFFFFF", stock: [1, 2, 3], photos: Array(count).fill("photo.jpg") }], collections: ["naissance"], crossSellIds: [], tags: [], description: "Desc", fabricRef: true, careRef: true };
    const block = buildProductBlock(p);
    assert.ok(block.includes(`defaultColorway("sample", variants(1, 2, 3)${count === 4 ? "" : `, ${count}`})`));
    assert.equal(readCatalog(helpers + block + "\n];").products[0].name, p.name);
  }
  const destination = path.join(f.root, "photos/converted.webp");
  await processProductImage(path.join(f.root, "photos/01.png"), destination);
  assert.deepEqual(await sharp(destination).metadata().then(({ format, width, height }) => ({ format, width, height })), { format: "webp", width: 20, height: 30 });
});
