# Adapting the bundled catalog CLI to a new store

The bundled reference is a working snapshot from a baby-clothing store (HelloBaby): `add-product.mjs` (entrypoint + legacy creation pipeline) and `catalog/` (management engine: `cli.mjs` argument parsing and confirmation, `manager.mjs` validation/edits/images/cleanup, `source.mjs` TypeScript parse/decode/patch, `transaction.mjs` lock/read-set/commit, `catalog.test.mjs` fixture suite). Copy BOTH into `<repo>/scripts/` preserving the layout — `scripts/add-product.mjs` + `scripts/catalog/` — then adapt every store-specific point below before first use. The engine reads and patches the store's TypeScript catalog via AST (interpreted, never executed), writes with snapshot + staged + locked transactions, and refuses anything it cannot decode exactly.

## Step 0 — Prereqs

- The store must already have: a hardcoded TS catalog with a single top-level `export const PRODUCTS … = [` array literal (e.g. `lib/data/products.ts`), a types file with `export type CollectionSlug = …` as a string-literal union (e.g. `lib/types.ts`), a funnel config exporting `UPSELL_OFFER = { active: boolean, productId: string }` (e.g. `lib/funnel-config.ts`), and a product images dir (`public/images/products`).
- Node deps: `sharp` and `typescript` installed in the store repo (used by the CLI and the test suite).
- Read all three first: the catalog's insertion style and constants, the types' collection slugs / size model, the funnel config, and the actual image dimensions used by existing products.

## Store-specific points — find and adapt each

1. **Paths + root** — `add-product.mjs` derives `ROOT` from `import.meta.dirname/..`, so scripts must live in `<repo>/scripts/`. Constants `PRODUCTS_PATH`, `TYPES_PATH`, `IMAGES_DIR` sit at the top. The management engine ALSO hardcodes the catalog/config/types paths in `catalog/manager.mjs` `load()` (`lib/data/products.ts`, `lib/funnel-config.ts`, `lib/types.ts`) — keep both in sync if locations differ. `cleanup()` in manager.mjs scans source files under the repo root for image references (see its ignore-list of directories).
2. **Collections** — `collectionLabels` (source.mjs) reads the `CollectionSlug` string-literal union; repoint it to the store's types file/union name. `FALLBACK_COLLECTIONS` / `COLLECTION_LABELS` in add-product.mjs feed only the legacy interview.
3. **Size model** — three valid shapes: (a) keep the legacy three labels (source.mjs `legacyLabels` + the `variants(stock0, stock3, stock6)` helper), (b) use custom labels everywhere via `sizeVariants` (validation already accepts any nonempty unique labels), or (c) extend to N fixed labels. If the store's catalog helpers differ, update `helperSources` in source.mjs to match them EXACTLY — helpers are decoded by token-structure comparison, never executed, and a mismatched helper is rejected at read time. `DEFAULT_PHOTO_COUNT` is verified in the same place.
4. **Catalog file conventions** — `emitCatalog` (source.mjs) patches the PRODUCTS array in place, preserving formatting and comments outside changed elements; products decode as plain data (string/number/bool/null/arrays/objects plus the whitelisted helpers `variants`/`images`/`defaultColorway`). If the store's catalog uses other helper calls or extra constants (e.g. `FABRIC`/`CARE`), extend `decoder`/`helperSources` in source.mjs and the creation defaults in manager.mjs `createProduct` consistently.
5. **Funnel config** — `readOffer`/`emitOffer` (source.mjs) expect `UPSELL_OFFER` with `active`/`productId`; rename/relocate for the store and update the manager paths. Delete's upsell decision (`disable` / `replaceWith`) writes there.
6. **Image pipeline** — sharp conversion in manager.mjs `gallery()` (reference: auto-orient, fit inside 1000x1250, no enlargement, quality 82) mirrors add-product.mjs constants `IMAGE_WIDTH` / `IMAGE_HEIGHT` / `WEBP_QUALITY`; keep them consistent. Match the store's existing dimensions/quality (check a current `.webp`) and the `IMAGES_DIR` / managed-path pattern. Photos per color: 1..8 via `MIN_PHOTO_COUNT`/`MAX_PHOTO_COUNT` and the same bounds in validation; adapt if the store's contract differs.
7. **Interactive language + routes** — interview, errors, recap, and USAGE are French; success output hardcodes `/produits/<slug>` and `/collections/<collection>` plus deploy reminders. Translate/repath to the store, and keep `askYes` accepting the right yes-letters. The capabilities contract wording (e.g. "positive safe integer MAD" for price) should match the store's currency.
8. **Legacy creation JSON** — creation accepts `name, slug, tagline, price, compareAtPrice, collections (legacy singular `collection` normalized), colorways [{label, photosDir, hex, stock | sizeVariants}], description, fabric, care, crossSellIds, tags`; `hex: null` auto-detects from photo 1. Trim or extend `JSON_KEYS`/`COLORWAY_KEYS` to the store's model.

## Keep as-is (store-agnostic)

Slug engine (`slugify` + `SLUG_REGEX`); TS parse/decode/patch with round-trip verification; revision hashing (SHA-256 of catalog source bytes); read-set concurrency detection; shared CLI lock + journal (`.catalog-cli.transaction.json`) with manual reconciliation on incomplete transactions; staged writes with byte-exact restore on handled failures; partial edit semantics (omit = unchanged, arrays = full replacement, ids/slugs immutable); image versioning/cleanup rules; `--json` / `--dry-run` / `--yes` / `--expected-revision` handling; stock-delta revision requirement; legacy `--from` creation and the French interview.

## Test protocol before committing the adapted CLI

1. `node --test scripts/catalog/catalog.test.mjs` — the fixture suite builds isolated temp repos (mkdtemp) and is injectable; adapt its fixtures (helper sources, types, sizes, collections) to the store's model and extend with store-specific cases. It imports `sharp`/`typescript` from the repo's node_modules.
2. Read-only discovery on the real repo: `--help`, `capabilities --json`, `list --json`, `show <existing> --json`.
3. In a scratch copy of the repo: a `--dry-run` add and a `--dry-run` edit (check the `writes` list), then a real run; verify `npx tsc --noEmit` and `npm run lint` pass and the catalog block matches the store's formatting.
4. Clean the scratch tree (restore exactly the listed writes; remove generated webp files); only then commit the adapted script.

## Storefront expectations the implementation assumes

- Size selectors render `sizeVariants` labels as-is, including custom labels; the size guide shows a placeholder (HelloBaby: « Non renseigné ») for labels without guide text.
- Saved carts reconcile against the live catalog: text/photo/price refreshed, unavailable lines dropped, quantities capped to stock, dismissible notice shown. Submitted orders and upsell snapshots are stored as-submitted and never rewritten.
- If the target store lacks these reconciliation behaviors, enabling catalog edits can strand saved carts/orders — plan that side as part of the upgrade.

## Version note

This snapshot is a fallback for stores without a catalog CLI. If the store repo already ships a newer `scripts/add-product.mjs` + `scripts/catalog/`, prefer adapting that one and re-verify with `capabilities --json`. The CLI help references `scripts/catalog/README.md` for examples; the bundled reference does not ship one — capabilities remains the authoritative contract.