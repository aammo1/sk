# Setup

## Server (one-time)

Deploy the app version containing `/api/catalog-agent` and `/api/catalog-agent/upload`.
Generate a dedicated random secret with `openssl rand -hex 32`. Set it as the
server's runtime secret **`CATALOG_AGENT_KEY`** and restart/redeploy. No build-time
or `NEXT_PUBLIC_` variable is needed. Missing/short keys disable the API (503).

This credential is accepted only by the catalog-agent endpoints; it does not
authenticate against `/api/admin`, `/api/crm`, Auth.js or Ozon. It grants catalog
reads, create/edit/archive/restore, image uploads, and initial stock on creation.
Rotate by replacing the server secret and updating the client secret. Rotation
also invalidates outstanding previews; committed receipts remain usable.

The skill uses existing catalog/inventory services and persistent upload storage.
It does not need direct database or SSH access. Existing deployments already
persist `/app/data` (database and uploads).

## Client

Use Node.js 22+ on the machine running the skill. No npm dependencies are needed.
Provide these environment variables through your secret manager or a private
env file outside the repository, recommended at `~/.config/zehri/catalog-agent.env`:

```dotenv
ZEHRI_STORE_URL=https://zehri.ma
ZEHRI_CATALOG_KEY=<the same secret as server CATALOG_AGENT_KEY>
```

`ZEHRI_STORE_URL` must be an HTTPS origin, without a path, embedded credentials,
query or fragment. The default is `https://zehri.ma`. The client refuses redirects
on authenticated requests, so use the final canonical hostname. It also refuses
redirecting image URLs; use the direct image URL.

After privately provisioning that file with the variables above, run from any directory:

```bash
node --env-file="$HOME/.config/zehri/catalog-agent.env" "$HOME/.agents/skills/zehri-catalog/scripts/catalog-client.mjs" capabilities
```

Use the same `--env-file` prefix for all commands, or load the variables in the
agent's environment. Do not display the file or the key. Keep the file readable
only by the owner (`chmod 600 "$HOME/.config/zehri/catalog-agent.env"`).

The default installation is global at `~/.agents/skills/zehri-catalog/`.
Reload the agent to discover it. Its client is a standalone copy and works outside
the repo; no project-local duplicate skill is needed. The repository's
`scripts/catalog-agent-client.mjs` is the versioned, testable client source.
When upgrading the API/client, sync that source to
`$HOME/.agents/skills/zehri-catalog/scripts/catalog-client.mjs` and update these
references as needed. Preserve the existing generic `store-add-product` skill
for other stores.

## Connection problems

- 401: check that the client/server secrets match.
- 503: configure a server key of at least 32 characters and restart the app.
- 404 or HTML instead of JSON: deploy the API changes or fix the store origin.
- 409 during apply: inspect the receipt; if absent, create a new preview and get
  approval. Do not overwrite another operator's changes.
- An image upload succeeded but applying failed: retry the approved plan if
  still valid. Upload paths are content-addressed, so retries reuse the same file.
- The skill cannot deploy or verify the live connection without access to your
  hosting environment and credential. Local tests do not imply live activation.
