---
name: zehri-catalog
description: >-
  Manages the live Zehri shoe-store catalog through its dedicated authenticated API.
  Creates products from local photos or image URLs with French copy, WebP galleries
  and initial stock; edits names, prices, copy, colors, sizes and photos; archives
  and restores products. Use for “add a product to Zehri”, “ajouter un produit”,
  “change product photos”, “modifier le prix”, “archive this product” and similar
  Zehri catalog requests. Prefer this skill over store-add-product for Zehri:
  its catalog is in SQLite, not source files. Stock is supported ONLY as initial
  stock during new-product creation. Existing-stock receipts, corrections,
  reservations, quarantine, orders, shipping and returns are outside its scope.
---

# Zehri live catalog

This skill is installed globally at `~/.agents/skills/zehri-catalog/`. Use its standalone `$HOME/.agents/skills/zehri-catalog/scripts/catalog-client.mjs` with Node.js 22+ from any working directory. It connects to the live API; catalog changes take effect without a rebuild. Read `references/setup.md` if credentials or the API are unavailable, and `references/contract.md` when constructing requests.

## Boundaries

- Manage products through this client, not SQLite, seed files, SQL, SSH, browser form automation or the old add-product CLI.
- Enter initial stock only when **creating a new product**. An edit cannot set stock, even for a newly added color or size. Direct the merchant to CRM → Stock for subsequent stock changes.
- Preserve order history and stock movements. “Delete/remove a product” means propose **archive**, explaining that it hides the product; do not hard-delete it.
- Keep all storefront text French; prices are integer MAD. Do not add a comparison price or a −30% promotion: the store reserves that discount for its upsell flow.
- Never expose credentials or put them in request JSON, command arguments, preview files or Git. The client reads them from the environment.

## Workflow

Track these steps for each request:
- [ ] Discover live capabilities and identify the exact product, if editing.
- [ ] Gather missing facts and prepare copy/photos.
- [ ] Create a preview and explain the changes.
- [ ] Obtain the user's approval of that specific preview.
- [ ] Apply, then verify and summarize the saved result.

### 1. Discover

Use the recommended private client env file `~/.config/zehri/catalog-agent.env` (see setup), or load the variables into the agent's environment and omit `--env-file`:

```bash
node --env-file="$HOME/.config/zehri/catalog-agent.env" "$HOME/.agents/skills/zehri-catalog/scripts/catalog-client.mjs" capabilities
node --env-file="$HOME/.config/zehri/catalog-agent.env" "$HOME/.agents/skills/zehri-catalog/scripts/catalog-client.mjs" list
node --env-file="$HOME/.config/zehri/catalog-agent.env" "$HOME/.agents/skills/zehri-catalog/scripts/catalog-client.mjs" show <exact-id-or-slug>
```

Use the current server capabilities and current product, not remembered catalog values. The list includes archived products. Search it to identify candidates; if the user's description matches more than one, ask them to choose before proceeding. `show` accepts an exact ID or slug, not a fuzzy name.

### 2. Gather and prepare

**Creation:** obtain price, sizes, quantities by color/size, photos, and factual details such as materials. Draft a suitable French name, concise description and brand-appropriate story. Suggest category, color labels and swatches after viewing the photos. Default to no badge and `isBestSeller: false`; only mark a best-seller if requested. Omit `upsellRef` unless explicitly requested.

Do not invent material, fit, heel height, comfort or durability claims. Ask for missing required facts. Confirm absent quantities rather than silently inventing inventory; explicitly approved zero stock is valid. The store creates the same size list for each active color; a color/size with zero stock remains unavailable. Explain this if the input has different size ranges per color.

**Editing:** send only changed scalar fields. `colors` and `sizes` are final selections, not patches. Start from the current active colors and variants, preserve their photos, and include every active color intended to remain. Include the desired final `sizes` whenever changing colors, so a wholly new palette gets its intended variants.

Colors match by exact name: changing “Noir” to “Ébène” creates a different color and deactivates the old variants; it does not move their stock. Explain and obtain approval of that consequence. Genuinely new variants start at zero; reactivated variants retain historical stock. Removed variants are deactivated, never deleted.

**Photos:** accept JPG/PNG/WebP local files, folders or HTTPS image URLs. Inspect images first. Expand folders into an explicit ordered list; propose the cover and gallery order. Preserve requested order. Relative local paths resolve against the operation JSON directory. Existing `/api/media/...` and `/images/...` paths preserve/reorder current photos. Other local paths and HTTPS URLs are new image sources.

The client stages sources locally and asks the server to compute a WebP preview without writing live files. Actual uploads happen only after approval. Images are auto-oriented, fit within 1600×2000 without upscaling, and encoded at WebP quality 82; input limit is 5 MB and 40 million pixels. If a URL redirects or cannot be downloaded, ask for a direct image URL or a local file instead of guessing.

### 3. Preview and approve

Write operation JSON and plans outside the repo, preferably `/tmp/opencode/`. See `references/contract.md` for examples. Use a fresh request ID for each distinct intended change; the client generates one if absent.

```bash
node --env-file="$HOME/.config/zehri/catalog-agent.env" "$HOME/.agents/skills/zehri-catalog/scripts/catalog-client.mjs" preview /tmp/opencode/product.json /tmp/opencode/product-plan.json
```

Present the live store origin, action, product ID/name, changed fields, category, price, colors/sizes, ordered image galleries and initial-stock matrix if creating. For structural edits, show which variants are added, deactivated or reactivated and what happens to their stock. Preview IDs for new colors/variants are provisional. Show the expiry time; previews last 30 minutes.

Ask for explicit approval of this preview. A request to add/edit a product, or approval of a general workflow, does not approve a particular mutation. If the user changes anything, prepare and obtain approval of a new preview. Never alter a prepared plan to bypass a new preview.

### 4. Apply and verify

Only after approval:

```bash
node --env-file="$HOME/.config/zehri/catalog-agent.env" "$HOME/.agents/skills/zehri-catalog/scripts/catalog-client.mjs" apply /tmp/opencode/product-plan.json --yes
```

The client uploads the staged photos, applies the signed operation, and reads back the current product. Compare the approved values with the saved receipt and current product; report the product ID, changes and final active/archive state. Use the storefront route from the repo when giving a product-page URL. If someone changed the product after the apply, disclose the difference rather than overwriting it.

If the preview conflicts or expires, refresh and seek approval again. Stock availability changes can invalidate a preview too. Never silently regenerate a request ID or retry a changed payload.

If a request times out or the response is lost:

```bash
node --env-file="$HOME/.config/zehri/catalog-agent.env" "$HOME/.agents/skills/zehri-catalog/scripts/catalog-client.mjs" receipt <requestId>
```

An existing receipt means that request committed; inspect it and `show` the product. Otherwise retry the **same approved plan**, which checks for a receipt again. No receipt plus an expired/conflicting preview requires a new preview and approval. Failed requests may leave unreferenced uploaded files; do not delete media or restore an old database backup to undo a catalog change. Prepare a new compensating edit/archive preview instead.

## Out-of-scope examples

- “Add 10 pairs to these existing shoes” → explain this belongs in CRM → Stock; do not create a duplicate product.
- “Confirm this order / receive this return” → explain this skill manages the catalog only.
- “Clear this badge / remove the upsell reference” → the current update contract cannot clear these nullable fields; explain the limitation rather than claiming it worked.
