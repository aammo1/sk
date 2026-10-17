# Catalog operation contract (v1)

- [Discovery](#discovery)
- [Create](#create)
- [Edit](#edit)
- [Archive / restore](#archive--restore)
- [Direct HTTP contract](#direct-http-contract)

## Discovery

`capabilities` returns live categories, badges, sizes, currency and supported
operations. `list` includes active/archived products, full color galleries and
variant availability. `show <id-or-slug>` returns one exact product. No fuzzy
matching, automatic duplicate selection or hard-delete operation exists.

## Create

The request ID is optional in client input; `preview` generates and saves it in
the plan. It is required in direct API input. Choose a new ID for a genuinely new
operation, but retain it across retries of an approved plan.

```json
{
  "command": "create",
  "data": {
    "name": "Mocassins Élise",
    "category": "mocassins",
    "price": 299,
    "description": "Une silhouette sobre pour accompagner vos tenues du quotidien.",
    "story": "Élise apporte une touche élégante à votre vestiaire, du bureau aux sorties.",
    "materials": ["Matière synthétique confirmée par le marchand"],
    "isBestSeller": false,
    "colors": [{
      "name": "Noir",
      "hex": "#191919",
      "images": ["/absolute/path/cover.jpg", "https://example.com/detail.jpg"]
    }],
    "sizes": [37, 38, 39],
    "initialStock": [
      {"colorKey": "Noir", "size": "37", "qty": 2},
      {"colorKey": "Noir", "size": "38", "qty": 3},
      {"colorKey": "Noir", "size": "39", "qty": 0}
    ]
  }
}
```

Replace example facts and URLs with the merchant's actual inputs. Required fields:
name, category, price, description, story, nonempty materials, isBestSeller,
colors, sizes. Optional: slug (creation only), badge, upsellRef, initialStock.
Categories: escarpins, sandales, bottines, mocassins. Sizes: integer 30–45.
Price: positive integer MAD. Badge: Nouveau, Best-seller, Édition limitée.
Each color has name, six-digit hex and an ordered images array (maximum 30).
Initial stock uses exact color names and size **strings**. It must be a nonnegative
safe integer; duplicate color/size entries fail. Omitted opening quantities mean
zero on the server; obtain explicit merchant agreement before omitting them.

The client converts local/HTTPS sources into `/api/media/catalog-<hash>.webp`
paths. Direct API requests accept only local `/api/media/...` or existing public
`/images/...` paths, not image URLs or local filesystem paths.

## Edit

```json
{
  "command": "edit",
  "target": "mocassins-elise",
  "data": {"price": 319, "description": "Le nouveau texte français approuvé."}
}
```

Omitted scalar fields stay unchanged. ID/slug cannot be changed through this
API. Stock, `initialStock`, arbitrary fields, unknown nested keys and empty edits
are rejected. The current store does not support clearing `badge` or `upsellRef`
with null or empty text. Materials must remain nonempty.

For colors/images/sizes, provide the **full desired active selection**, including
unchanged entries. When sending colors, send final sizes too. Gallery order is
array order; its first image is the cover. No media file is deleted on edit.
Colors match by exact name, not ID. Removed colors remain in historical data
with inactive variants; `show` can still include them. A renamed color is a new
color; it does not inherit old stock. Re-adding an old color/size can reactivate
its existing variant and existing stock. Newly created variants have zero stock.

## Archive / restore

```json
{"command":"archive","target":"mocassins-elise"}
```

Use `"restore"` for the inverse. Neither action changes physical stock, reservations,
orders or historical records. Restoring can make existing available stock sellable
again; include that effect in the approval preview.

## Direct HTTP contract

All requests use `Authorization: Bearer <CATALOG_AGENT_KEY>`. Never put it in a URL.

- `GET /api/catalog-agent?command=capabilities|list`
- `GET /api/catalog-agent?command=show&target=<id-or-slug>`
- `GET /api/catalog-agent?command=receipt&requestId=<requestId>` → `{receipt: null|...}`
- `POST /api/catalog-agent` with `{action:"preview", operation:{...}}`
- `POST /api/catalog-agent` with `{action:"apply", operation:{...}, preview:"<signed proof>"}`
- `POST /api/catalog-agent/upload?dryRun=1`, multipart `file`: compute WebP path, no write.
- `POST /api/catalog-agent/upload`, multipart `file`: persist WebP at that path.

Preview returns operation, before/after snapshots, signed proof, expiry and notes.
The proof binds the normalized request and full catalog snapshot, including variant
availability. Approval is a skill/client workflow step; the API verifies a signed
preview, not human identity. Apply checks the proof under an immediate SQLite
transaction and writes a receipt atomically with the mutation. Same request ID and
payload return the existing receipt even after preview expiry; a changed payload
with that ID fails. Receipts contain the saved product snapshot, command and time;
`show` returns the current state, which may differ after later legitimate edits.

Uploads are separate from the catalog transaction and happen after approval.
Failed applies can leave unreferenced content-addressed files. Keep these files:
there is no media cleanup or database-restore rollback in this skill.
