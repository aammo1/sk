---
name: store-add-product
description: Full catalog management for any e-commerce store repo that follows the add-product CLI convention (a committed `scripts/add-product.mjs` exposing capabilities/list/show/add/edit/delete), discovering that store's contract, collections, sizes, and brand tone at runtime rather than assuming them. Adds products with automatic photo WebP conversion, edits/updates and deletes/removes products, changes prices, stock, sizes, photos, and copy through the store's versioned JSON contract, with dry-run previews, revision-guarded writes, and transactional rollback. Use when the user says "add a product", "add this product to my store", "upload product photos", "new product", "ajouter un produit", "nouveau produit", "edit a product", "update a product", "delete a product", "remove a product", "change the price", "update stock", "add sizes", "change product photos", "modifier un produit", "supprimer un produit", "changer le prix", "mettre à jour le stock", or asks to manage a store's catalog or products in a repo with the add-product script. Do not use for generic e-commerce advice in repos that do not have `scripts/add-product.mjs`.
---

# Store Catalog Management (add / edit / delete products)

Playbook for managing any store repo's catalog through its committed CLI `scripts/add-product.mjs`. All store specifics (language, sizes, collections, image conventions, tone) are discovered at runtime — never trust remembered values. Never mutate the catalog file, funnel config, or product images by hand; every change goes through the CLI.

## 1. Detect the store

- The target repo must contain `scripts/add-product.mjs`; verify with `ls`.
- If absent: stop, explain the add-product CLI convention, and offer to bootstrap the store's script from this skill's `reference/` directory (copy `add-product.mjs` + `catalog/` and follow `reference/ADAPTATION.md`). Once bootstrapped (verified with `--help` and `capabilities --json`), resume below.
- If the script predates the management commands (nothing under `scripts/catalog/`, no `capabilities` support), treat it as add-only: do not mutate the catalog any other way — explain the limitation and offer to upgrade the store's script from the bundled reference (section 8).

## 2. Discover the contract (always first)

- Run `node scripts/add-product.mjs --help` then `node scripts/add-product.mjs capabilities --json` (cwd = repo). `capabilities` is authoritative: schemaVersion, supported commands and flags, editable fields, collections, tags, the product list, upsell status, and the current catalog revision (SHA-256).
- `list --json` gives ids/slugs/names with colors and sizes; `show <id-or-slug> --json` gives the full current product JSON.
- Read the store's types file (commonly `lib/types.ts`) for collection slugs and the size model, and the catalog file (commonly `lib/data/products.ts`) for insertion style and brand tone. Never assume baby sizes, French, or any store-specific detail (a shoe store: sizes 39-45, different collections).
- Record the revision reported by show/capabilities — it is the `--expected-revision` value for guarded writes.

## 3. Command and flag contract

```bash
node scripts/add-product.mjs capabilities --json
node scripts/add-product.mjs list --json
node scripts/add-product.mjs show <id-or-slug> --json
node scripts/add-product.mjs add --from product.json [--dry-run] [--yes] [--json]
node scripts/add-product.mjs edit <id-or-slug> --from edit.json [--dry-run] [--yes] [--json]
node scripts/add-product.mjs delete <id-or-slug> [--from decision.json] [--dry-run] [--yes] [--json]
```

- `--expected-revision <sha256>` may guard any mutation; stock deltas REQUIRE it. Stale/mismatched revision = conflict error — re-run `show`, rebuild the request, never blind-retry.
- `--from` without a command remains legacy creation; no arguments starts the interactive (French) interview. Both are preserved.
- Mutations without `--yes` on a TTY preview then prompt `Confirm? [y/N]` (accepts y/yes/o/oui); non-interactive runs require `--yes`. Dry-run never prompts and never writes.
- Every result echoes `revision` and `nextRevision` — capture the new revision if another guarded mutation follows.
- Result shape: `{ schemaVersion, dryRun, command, target, revision, nextRevision, product|null, prunedCrossSells, imageCleanup: {deleted, retained}, imageWrites, writes }` (`writes` = repo-relative paths touched).

## 4. Adding a product

- Gather info conversationally (user's language, never a rigid interrogation): name, price (+ optional compareAtPrice), collection(s), colorways (label + folder of photos + stock per size), description, cross-sells. Ask only what's missing.
- Photos: the folder must contain only the extensions the store's script accepts (reference: jpg/jpeg/png/webp), within its count rule (reference: 1-8), and lexicographic filename order = gallery order. Wrong order: copy/rename to zero-padded sequential names in `/tmp/opencode/...`. URLs: download first. Convert nothing yourself — the script converts to WebP.
- Colors: set `hex: null` to auto-detect from the first photo, or pick a swatch hex yourself after viewing the photo.
- Copy: polish rough user text into clean, on-brand copy in the store's language, matching the tone learned in section 2. Leave default-field keys (fabric/care or equivalent) null unless the user wants custom text.
- Cross-sells: 1-2 complementary existing product ids from the catalog (must exist); propose them to the user.
- Write JSON to `/tmp/opencode/` (never inside the repo), then ALWAYS dry-run, show the user the plan, and only then run for real:

```json
{
  "name": "...",
  "slug": "optional",
  "tagline": "...",
  "price": 249,
  "compareAtPrice": 299,
  "collections": ["..."],
  "colorways": [{ "label": "...", "photosDir": "/abs/path", "hex": null, "sizeVariants": [{ "label": "...", "stock": 3 }] }],
  "description": "...",
  "fabric": null,
  "care": null,
  "crossSellIds": ["existing-id"],
  "tags": ["new"]
}
```

- `sizeVariants` uses this store's exact size labels (from list/capabilities; custom labels are valid). Some stores also accept a legacy `stock: [n,n,n]` shorthand per colorway — never both in one colorway; prefer `sizeVariants`.
- Tags: allowed set comes from capabilities (reference: promotion, best-seller, new, gift, emitted in that order). `promotion` requires compareAtPrice > price and a floored discount of at least 1%.
- Run `node scripts/add-product.mjs add --from /tmp/opencode/store-product.json --yes --json`, then verify with `show` and `git status --short`.

## 5. Editing a product

Workflow: `show` → build edit JSON → `--dry-run` → show the user the plan → confirm → `edit --yes --json` → `show` again to verify.

Edit request `{"version": 1, ...}`: omitted fields preserve existing values; never resend the whole product.

- `"set"`: name/tagline/description/fabric/care (nonempty strings); price (positive safe integer); compareAtPrice (integer > price, or explicit null to remove); collections/tags/crossSellIds (final ordered arrays = full replacement; empty allowed except collections). Explicit null on any other field is rejected; product id/slug are immutable.
- `"colors"`: `{ "add": [...], "update": [...], "remove": [...colorIds] }`. Colors are keyed by stable id (label changes rename display only). `add` items: `{id, label, hex, images, sizeVariants}`. `update` items: `{id, label?, hex?, images?, sizeVariants?, sizes?}` where sizes come from EITHER `sizeVariants` (full ordered replacement `[{label, stock}]`) OR `sizes` operations `{add: [{label, stock}], update: [{label, stock: <number> | {"delta": <±n>}}], remove: [<exactLabel>]}` — never both. A color/size may be targeted once per request. Custom size labels are allowed.
- Stock deltas (`{"delta": n}`) REQUIRE `--expected-revision <sha256>` from show/capabilities. Absolute stock numbers do not, but guard busy-store edits anyway. A delta must not underflow/overflow below 0.
- Unknown fields, unknown targets, invalid final states, and repeated targets all reject without writing anything.

## 6. Photos on edit

- `images` is the FINAL ordered gallery (1..8 per color): strings = existing catalog `/images/...` paths (sharing images across products is allowed), objects = `{"file": "/abs/local/path.jpg"}` for new inputs. Omit `images` entirely to preserve the current gallery.
- Include/omit entries to add/replace/remove/reorder; array order = storefront order; first image is the cover. Reorder by resending existing paths in the new order.
- New inputs are converted to WebP by the script (auto-orient, fit inside its configured box — reference 1000x1250 with no upscale — quality 82) and get versioned, content-hashed filenames. Removed/replaced images are auto-deleted only when no other product references them; shared images are retained; there is no orphan sweep. The result reports `imageCleanup {deleted, retained}` and `imageWrites`.

## 7. Deleting a product

Workflow: `show` → `--dry-run` → handle any decision → `delete --yes --json`.

- If the product is the active upsell target (see capabilities `upsell`), dry-run returns `decisionRequired` and writes nothing. Ask the user to choose: disable the upsell (`{"version": 1, "upsell": {"disable": true}}`) or replace it (`{"version": 1, "upsell": {"replaceWith": "<existing id-or-slug>"}}` — the target must exist and cannot be the deleted product). Never pick for them: `--yes` never invents the decision, and a real run without one fails.
- Inbound cross-sells referencing the deleted product (by id OR slug) are auto-pruned and reported in `prunedCrossSells`.
- Image cleanup follows section 6 rules.

## 8. Older add-only scripts and upgrades

- If management commands are unavailable, do NOT edit the catalog, funnel config, or images directly — no manual products.ts edits, no hand-moved webp files. Adding a product through the store's existing legacy flow is fine; for edits/deletes, explain the gap and offer to upgrade the store's script: copy `reference/add-product.mjs` + `reference/catalog/` from this skill, adapt per `reference/ADAPTATION.md`, run its fixture test suite, then re-discover the contract via `capabilities --json`.

## 9. Safety and rollback

- ALWAYS dry-run first for every mutation and show the user the plan (writes, imageCleanup, prunedCrossSells, nextRevision) before `--yes`. Never set `--yes` before the user approves the dry-run plan.
- Handled failures (validation, conflicts, write errors) restore exact bytes automatically. An interrupted write leaves `.catalog-cli.transaction.json` which BLOCKS further writes — never delete it blindly; inspect the snapshots and reconcile manually.
- To undo a completed, unpushed mutation: `git status --short` first, then restore exactly the paths the result's `writes` listed (`git restore -- <paths>` for tracked files) and remove only the untracked new files it created. Never use wildcard deletions. After push: revert via a new commit. Going LIVE = user commits, pushes, and their deploy pipeline rebuilds — never push without asking.

## 10. Beyond the contract

- New badge/size/collection or schema gaps: read the types file + script first. Small additions = edit types + script together (then re-read `--help` and `capabilities --json`). Structural changes = suggest a short planning session instead of improvising.
- New store without the script: bootstrap from `reference/` + `reference/ADAPTATION.md`, then re-discover the contract.

## 11. Storefront expectations (context when advising)

- Custom size labels render in the size selector; the size guide shows the store's placeholder (reference store: « Non renseigné ») for labels without guide text.
- Saved carts auto-refresh text/photo/price on next load, drop unavailable lines, cap quantities to stock, and show a dismissible notice. Submitted orders and upsell snapshots are stored as-submitted and never rewritten.
- If the target store lacks these reconciliation behaviors, catalog editing can strand saved carts/orders — plan that side as part of any upgrade.