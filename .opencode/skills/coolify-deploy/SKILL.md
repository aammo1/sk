---
name: coolify-deploy
description: Deploy applications on Coolify — a self-hosted PaaS (like Heroku/Vercel) that runs on your own VPS. Covers project setup, Dockerfile templates, health checks, database configuration, environment variables, CORS, persistent volumes, DNS, and debugging. Use when the user is deploying to Coolify, setting up a Coolify project, troubleshooting a Coolify deployment, or mentions Coolify, self-hosting, VPS deployment, Traefik, or Docker-based PaaS.
---

# Coolify Deployment

## When to Use

Use this skill when the user:
- Is deploying any application (Python/Node.js/Go) on Coolify
- Is setting up a new Coolify project with backend + frontend + database
- Has a Coolify deployment that's broken (502, CORS errors, health check failures, etc.)
- Mentions Coolify, self-hosted PaaS, or needs a self-hosted Vercel/Heroku alternative
- Is writing Dockerfiles or entrypoint scripts for Coolify deployment
- Is configuring domains, SSL, or reverse proxy on Coolify

## Coolify Architecture

Coolify runs on your VPS. Each component of your application is a separate **Resource**:

- **Backend** → one resource (GitHub App with Dockerfile)
- **Frontend** → one resource (GitHub App with Dockerfile)
- **Database** → one resource (built-in PostgreSQL/MySQL/Redis)

Do NOT bundle services into a `docker-compose.yml`. Each resource gets its own container, domain, and env vars. Traefik acts as the reverse proxy, routing traffic from domains to containers.

## Planning Your Deployment

Before creating resources in Coolify, map out every component. Use a table:

| # | Resource | Type | Port | Domain | Base Dir |
|---|----------|------|------|--------|----------|
| 1 | PostgreSQL | Database | — | — | — |
| 2 | myapp-api | GitHub App | **8000** | api.myapp.com | backend |
| 3 | myapp-web | GitHub App | 3000 | myapp.com | frontend |

## Step-by-Step Setup

### 1. Database First

Create the database before the apps — they need the connection string.

1. **+ Add Resource → Database → PostgreSQL**
2. Set database name, username, password. Deploy.
3. Copy the **Internal URL** from the database resource.
4. **Normalize the URL**: Change `postgres://` to `postgresql://` and `/postgres` to `/<your_db_name>` at the end.

Coolify provisions the `postgres` database by default — not your app's database. You must either point to your own database or create it in your entrypoint (see Database Configuration below).

### 2. Backend

1. **+ Add Resource → GitHub App**, select repo
2. **Base Directory**: `backend` (or wherever your Dockerfile lives)
3. **Port**: match your app's listen port (⚠️ defaults to 3000 — change it!)
4. **Domain**: e.g., `api.myapp.com`
5. Enable **HTTPS / Let's Encrypt**
6. Add environment variables (see Environment Variables section)
7. **Add Persistent Volume** if your app writes files (e.g., uploads):
   - Source: `myapp-uploads`, Destination: `/app/uploads`, Type: Directory mount
8. Deploy

### 3. Frontend

Same process as backend, but Port is typically 3000 and you need `NEXT_PUBLIC_*` vars set in **both** Build Args and Environment Variables (see Frontend section).

### 4. DNS

Configure A records pointing to your VPS IP:
```
A  api.myapp.com  →  <VPS IP>
A  myapp.com      →  <VPS IP>
```

## The Port Mistake (Most Common Error)

Coolify defaults every resource to port 3000. If your app listens on 8000, 5000, or 8080, you get **502 Bad Gateway** because Traefik forwards traffic to where nothing listens.

Set the correct port in **Configuration → Port**. The `EXPOSE` directive in your Dockerfile is informational only — it does NOT tell Coolify where to route.

| Framework | Default Port | Action |
|-----------|-------------|--------|
| Next.js | 3000 | Keep default |
| FastAPI / Django / Gunicorn | 8000 | **Change from 3000** |
| Express | 3000 | Keep default |
| Flask | 5000 | **Change from 3000** |
| Go (net/http) | 8080 | **Change from 3000** |

## Health Checks

Health checks tell Coolify whether your container is actually alive. Without them, Coolify uses basic process checks that can pass even when the app is broken.

### Python Backend

```dockerfile
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=10 \
  CMD curl -f http://localhost:8000/api/health || exit 1
```

Define the endpoint:
```python
@app.get("/api/health")
def health_check():
    return {"status": "ok"}
```

### Next.js Frontend (Alpine)

```dockerfile
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/ || exit 1
```

Use `127.0.0.1` NOT `localhost` — Alpine's `wget` resolves `localhost` to IPv6 `[::1]` but Node.js standalone only listens on IPv4. Use `wget` not `curl` on Alpine (curl not installed by default).

### Parameters

| Parameter | Recommended | Why |
|-----------|-------------|-----|
| `start-period` | 60-120s | Time for DB migrations, builds, startup |
| `interval` | 10-15s | How often to check |
| `timeout` | 5s | Max wait for response |
| `retries` | 5-10 | Failures before marking unhealthy |

## Environment Variables

### General Rules

- Set variables in Coolify's **Environment Variables** section for each resource
- For Next.js, `NEXT_PUBLIC_*` vars must be set in **both** Environment Variables AND Build Args
- Never log secrets in entrypoint scripts (`echo $DATABASE_URL` leaks the password)

### Docker Escapes `$` Signs

Docker interprets `$` in env var values. For literal `$` (e.g., bcrypt hashes like `$2b$12$...`), **double every `$`**:
```
ADMIN_PASSWORD_HASH=$$2b$$12$$...   # Correct
ADMIN_PASSWORD_HASH=$2b$12$...     # Wrong — Docker mangles it
```

### Real-World Example

```
DATABASE_URL=postgresql://user:pass@host:5432/myapp
SECRET_KEY=<random-64-char-string>
ADMIN_PASSWORD_HASH=$$2b$$12$$...
CORS_ORIGINS=https://myapp.com,https://www.myapp.com
COOKIE_DOMAIN=.myapp.com
UPLOAD_DIR=./uploads
```

## Database Configuration

### 1. `postgres://` vs `postgresql://`

Coolify generates `DATABASE_URL` with `postgres://`. SQLAlchemy 2.0+ and Prisma's `@prisma/adapter-pg` require `postgresql://`. Always normalize in both code and scripts:

```python
# Python / SQLAlchemy
class Settings(BaseSettings):
    DATABASE_URL: str

    @property
    def database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
```

```typescript
// TypeScript / Prisma 7+
function getDatabaseUrl(): string {
  let url = process.env.DATABASE_URL || "";
  if (url.startsWith("postgres://")) {
    url = url.replace("postgres://", "postgresql://");
  }
  return url;
}
```

### 2. Default Database Is `postgres` — Not Yours

Coolify's `DATABASE_URL` points to the `postgres` database. Create your app's database in the entrypoint:

```sh
DB_NAME=$(echo "$DATABASE_URL" | sed 's|.*\/||')
if [ "$DB_NAME" = "postgres" ]; then
  python -c "
from sqlalchemy import create_engine, text
engine = create_engine('${DATABASE_URL}')
with engine.connect() as conn:
    conn.execute(text('COMMIT'))
    exists = conn.execute(text(\"SELECT 1 FROM pg_database WHERE datname='myapp'\")).fetchone()
    if not exists:
        conn.execute(text('COMMIT'))
        conn.execute(text('CREATE DATABASE myapp'))
"
  export DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|/postgres$|/myapp|')
fi
```

Never DROP and recreate the database — only create if it doesn't exist.

### 3. Use `psycopg2-binary`, Never `psycopg2`

`psycopg2` needs `libpq-dev` + `gcc` to compile. `psycopg2-binary` is a pre-compiled wheel.

### 4. SQLite for Local, PostgreSQL for Production

```python
connect_args = {}
if "sqlite" in database_url:
    connect_args["check_same_thread"] = False
engine = create_engine(database_url, connect_args=connect_args)
```

### 5. Stale Volumes After Password Changes

If you change the database password or recreate PostgreSQL, delete the old Docker volume — PostgreSQL won't reinitialize if data exists:
```bash
docker volume ls | grep postgres
docker volume rm <volume_name>
```

## Persistent Volumes

When your app writes files (uploads, media, generated content), mount a persistent volume so data survives container redeploys:

1. In Coolify resource → **Configuration → Persistent Volumes**
2. Add mount: Source name → Container path (e.g., `myapp-uploads` → `/app/uploads`)
3. Use Directory mount type (not File)

Without this, every redeploy wipes uploaded files.

## Entrypoint Script Best Practices

### 1. Never Use `set -e`

`set -e` causes the container to die on any command failure (DB unreachable, migration error). Coolify sees a dead container and it never stabilizes. Use explicit `|| echo "warning"` and `if/then` blocks instead.

### 2. Use `exec` for the Final Command

```sh
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
```
`exec` replaces the shell process with your app so SIGTERM signals propagate correctly for graceful shutdown.

### 3. Wait for Database but Don't Exit on Failure

```sh
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if python -c "from app.database import engine; engine.connect()" 2>/dev/null; then
    break
  fi
  RETRY_COUNT=$((RETRY_COUNT + 1))
  sleep 3
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "WARNING: Could not connect to database, starting anyway"
fi
```

### Complete Entrypoint Template (Python)

```sh
#!/bin/sh

echo "Checking database connection..."
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if python -c "from app.database import engine; engine.connect()" 2>/dev/null; then
    echo "Database connected."
    break
  fi
  RETRY_COUNT=$((RETRY_COUNT + 1))
  sleep 3
done
[ $RETRY_COUNT -eq $MAX_RETRIES ] && echo "WARNING: Database unreachable"

echo "Running migrations..."
alembic upgrade head || echo "WARNING: Migration failed"

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Complete Entrypoint Template (Next.js with Prisma 7+)

```sh
#!/bin/sh
# NO set -e — per Coolify deployment guide

DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|^postgres://|postgresql://|')
export DATABASE_URL

echo "Checking database connection..."
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if node db-check.js 2>&1; then
    break
  fi
  RETRY_COUNT=$((RETRY_COUNT + 1))
  echo "Retry $RETRY_COUNT/$MAX_RETRIES..."
  sleep 3
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "WARNING: Could not connect to database, starting anyway"
fi

exec node server.js
```

Where `db-check.js` is a standalone script at the project root:
```javascript
const { PrismaPg } = require("@prisma/adapter-pg");
const { PrismaClient } = require("@prisma/client");

let url = process.env.DATABASE_URL || "";
if (url.startsWith("postgres://")) {
  url = url.replace("postgres://", "postgresql://");
}

const adapter = new PrismaPg({ connectionString: url });
const p = new PrismaClient({ adapter });

p.$connect()
  .then(() => { console.log("Database connected"); return p.$disconnect(); })
  .then(() => process.exit(0))
  .catch((e) => { console.error("Database connection failed:", e.message); process.exit(1); });
```

## Frontend (Next.js) on Coolify

### 1. `NEXT_PUBLIC_*` Must Be Set in Both Places

Next.js bakes `NEXT_PUBLIC_*` into the JS bundle at **build time**. Set them in both Coolify's **Build Args** AND **Environment Variables**. Missing build args → browser sees `undefined`.

### 2. `output: "standalone"` Is Required

```ts
// next.config.ts
const nextConfig: NextConfig = {
  output: "standalone",
  images: { unoptimized: true },
};
```

Standalone output includes only the files needed to run — essential for Docker.

### 3. Copy All Three Standalone Output Pieces

```dockerfile
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
```

Missing any line → broken app. `rewrites()` in `next.config.ts` don't work in standalone mode — the browser must call the API directly.

### 4. Server-Side API Calls Need Internal URL

Server components run inside the Docker container and may not resolve the public domain:

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
const API_BASE_SERVER = process.env.API_URL_INTERNAL || API_BASE;

function getApiBase(): string {
  if (typeof window === "undefined") return API_BASE_SERVER;
  return API_BASE;
}
```

### 5. Disable Caching for Dynamic Data

```typescript
const res = await fetch(url, { cache: "no-store" });
```

### 6. Handle API Errors Gracefully

Never call `notFound()` on network errors — only on real 404s:
```tsx
try {
  product = await getProduct(slug);
} catch (e) {
  if (e instanceof Error && e.message.includes("404")) notFound();
  throw e; // Let error boundary handle other errors
}
```

## Next.js + Prisma 7+ on Coolify (Critical Gotchas)

Prisma 7.x has breaking changes that affect Docker deployments. These are the most common deployment failures.

### 1. Prisma 7 Requires Node ≥ 22

Prisma 7.8+ requires Node.js 22 or later. Using `node:20-alpine` causes runtime errors:

```dockerfile
# WRONG
FROM node:20-alpine AS base

# CORRECT
FROM node:22-alpine AS base
```

### 2. Prisma 7 Uses "Client" Engine — Requires Driver Adapter

Prisma 7.x switched from the binary engine to a "client" engine. For PostgreSQL, you **must** install `@prisma/adapter-pg` and `pg`, then configure PrismaClient with the adapter:

```bash
npm install @prisma/adapter-pg pg
```

```typescript
// src/lib/db.ts
import { PrismaClient } from "@prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";

function getDatabaseUrl(): string {
  let url = process.env.DATABASE_URL || "";
  if (url.startsWith("postgres://")) {
    url = url.replace("postgres://", "postgresql://");
  }
  return url;
}

const globalForPrisma = globalThis as unknown as { prisma: PrismaClient };

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({
    adapter: new PrismaPg({ connectionString: getDatabaseUrl() }),
    log:
      process.env.NODE_ENV === "development"
        ? ["query", "error", "warn"]
        : ["error"],
  });

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;
```

Without the adapter, you get:
```
PrismaClientConstructorValidationError: Using engine type "client" requires
either "adapter" or "accelerateUrl" to be provided to PrismaClient constructor.
```

### 3. `npm ci` Fails in Docker — Use `npm install --legacy-peer-deps`

Local npm v11+ generates a lock file that Docker's npm v10 can't read. The error:
```
npm ci can only install packages when your package.json and package-lock.json
are in sync. Missing: @swc/helpers@0.5.23 from lock file
```

**Fix**: Use `npm install --legacy-peer-deps` instead of `npm ci` in the Dockerfile:

```dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --legacy-peer-deps
```

### 4. Standalone Output Missing Required Packages

Next.js standalone output (`output: "standalone"`) creates a minimal `node_modules/` that excludes many packages your app needs at runtime. You **must** manually copy missing packages from the builder stage.

Always check after building which packages are missing:
```bash
# After local build, check what's in standalone vs full node_modules
ls .next/standalone/node_modules/@prisma/
# If packages like adapter-pg are missing, copy them in the Dockerfile
```

**Prerequisites to copy for Prisma 7 with PostgreSQL:**

```dockerfile
# Standalone output already includes @prisma/client, @prisma/client-runtime-utils, .prisma/client
# But you MUST copy these additional packages:
COPY --from=builder /app/prisma ./prisma
COPY --from=builder /app/node_modules/prisma ./node_modules/prisma
COPY --from=builder /app/node_modules/@prisma ./node_modules/@prisma
COPY --from=builder /app/node_modules/.prisma ./node_modules/.prisma
COPY --from=builder /app/node_modules/@prisma/adapter-pg ./node_modules/@prisma/adapter-pg
COPY --from=builder /app/node_modules/@prisma/driver-adapter-utils ./node_modules/@prisma/driver-adapter-utils
COPY --from=builder /app/node_modules/postgres-array ./node_modules/postgres-array
```

⚠️ Always check `node_modules/postgres-array` in your standalone output. Next.js creates a "stub" (only `package.json`, no `index.js`) for some packages. If the stub has no real code, you must copy the full package from the builder stage.

### 5. `npx prisma db push` Doesn't Work in Standalone Mode

In the Next.js standalone Docker runner, `npx prisma` will fail because:
- The standalone `node_modules/.bin/` doesn't have the `prisma` binary
- Even if you copy `prisma`, it depends on `@prisma/config` which needs `effect` and other packages not in standalone output
- The Prisma CLI is ~60MB+ with all its dependencies

**Solutions** (pick one):

**Option A: Create tables via Coolify's PostgreSQL terminal (recommended)**
1. Go to your PostgreSQL resource in Coolify
2. Click **Exec** / **Terminal**
3. Run: `psql -U youruser -d yourdb`
4. Create tables with raw SQL
5. This is the cleanest approach — no bloat in the Docker image

**Option B: Create tables via app container terminal using PrismaClient**
1. Go to your app resource in Coolify
2. Click **Exec** / **Terminal**
3. `cd /app` (you may start at `/`)
4. Run a Node.js one-liner to create tables:

```sh
node -e "
const { PrismaPg } = require('@prisma/adapter-pg');
const { PrismaClient } = require('@prisma/client');
let url = process.env.DATABASE_URL;
if (url.startsWith('postgres://')) url = url.replace('postgres://', 'postgresql://');
const adapter = new PrismaPg({ connectionString: url });
const p = new PrismaClient({ adapter });
p.\$executeRawUnsafe('CREATE TABLE IF NOT EXISTS \\\"Lead\\\" (...)').then(() => { console.log('Done'); p.\$disconnect(); }).catch(e => { console.error(e.message); p.\$disconnect(); });
"
```

**Option C: Use a `db-check.js` file for health checks, create tables manually once**

Include a `db-check.js` in your project that uses PrismaClient (not Prisma CLI) to test connectivity. Create tables once after first deploy via Option A or B.

### 6. Missing Environment Variables Crash Services at Import Time

Libraries like `resend` throw errors if instantiated without required API keys:

```typescript
// WRONG — crashes if RESEND_API_KEY is not set
import { Resend } from "resend";
const resend = new Resend(process.env.RESEND_API_KEY);

// CORRECT — lazily initialize, gracefully skip if not configured
import { Resend } from "resend";

const resend = process.env.RESEND_API_KEY
  ? new Resend(process.env.RESEND_API_KEY)
  : null;

export async function sendEmail(data: any) {
  if (!resend) {
    console.warn("RESEND_API_KEY not configured, skipping email");
    return;
  }
  return resend.emails.send(data);
}
```

Any service that requires configuration at import time (API keys, URLs, credentials) must be initialized lazily or wrapped in try/catch.

### 7. Normalizing `postgres://` to `postgresql://` in Code

Coolify generates `DATABASE_URL` with `postgres://`. The `@prisma/adapter-pg` driver requires `postgresql://`. Normalize in your `db.ts`, NOT just the entrypoint:

```typescript
// db.ts — normalize at the application level
function getDatabaseUrl(): string {
  let url = process.env.DATABASE_URL || "";
  if (url.startsWith("postgres://")) {
    url = url.replace("postgres://", "postgresql://");
  }
  return url;
}
```

Also normalize in `db-check.js` and any shell scripts:
```sh
DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|^postgres://|postgresql://|')
export DATABASE_URL
```

## Dockerfile Templates

### Python Backend (FastAPI/Django/Flask)

```dockerfile
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=10 \
  CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["sh", "entrypoint.sh"]
```

### Next.js + Prisma 7 (Complete Template)

```dockerfile
FROM node:22-alpine AS base

FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --legacy-peer-deps

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npx prisma generate
RUN npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy standalone Next.js output
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Copy Prisma schema + full @prisma packages for PrismaClient with adapter
COPY --from=builder /app/prisma ./prisma
COPY --from=builder /app/node_modules/prisma ./node_modules/prisma
COPY --from=builder /app/node_modules/@prisma ./node_modules/@prisma
COPY --from=builder /app/node_modules/.prisma ./node_modules/.prisma

# Copy PG driver adapter packages (not included in standalone output)
# ⚠️ Always verify these are missing from .next/standalone/node_modules/ after build
COPY --from=builder /app/node_modules/@prisma/adapter-pg ./node_modules/@prisma/adapter-pg
COPY --from=builder /app/node_modules/@prisma/driver-adapter-utils ./node_modules/@prisma/driver-adapter-utils
COPY --from=builder /app/node_modules/postgres-array ./node_modules/postgres-array

# Copy db check script and entrypoint
COPY --from=builder /app/db-check.js ./db-check.js
COPY --from=builder /app/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/ || exit 1

CMD ["sh", "entrypoint.sh"]
```

### Next.js Frontend (Simple, No Prisma)

```dockerfile
FROM node:22-alpine AS base

FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --legacy-peer-deps

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME="0.0.0.0"
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/ || exit 1
CMD ["node", "server.js"]
```

## .dockerignore

### Python
```
venv/
.venv/
__pycache__/
*.pyc
*.db
.env
.env.example
```

### Node.js
```
node_modules/
.next/
.git/
.env
.env.local
.env*.local
```

⚠️ Do NOT include `*.md` in `.dockerignore` — it can exclude important files like entrypoint documentation. Be specific about what to exclude.

## Post-Deploy Database Setup

After deploying to Coolify, you must create the database and tables. Do NOT rely on `npx prisma db push` in the entrypoint — it doesn't work in standalone mode.

### Step 1: Create the Database

The Coolify PostgreSQL `DATABASE_URL` points to the `postgres` database by default. Create your app database:

1. Go to your app container **Terminal** in Coolify
2. `cd /app`
3. Run:
```sh
node -e "
const { PrismaPg } = require('@prisma/adapter-pg');
const { PrismaClient } = require('@prisma/client');
let url = process.env.DATABASE_URL;
if (url.startsWith('postgres://')) url = url.replace('postgres://', 'postgresql://');
const adapter = new PrismaPg({ connectionString: url.replace(/\/[^\/]*$/, '/postgres') });
const p = new PrismaClient({ adapter });
p.\$executeRawUnsafe('CREATE DATABASE myapp').then(() => { console.log('Database created'); p.\$disconnect(); }).catch(e => { console.log(e.message); p.\$disconnect(); });
"
```

### Step 2: Update DATABASE_URL

In Coolify's **Environment Variables**, change `DATABASE_URL` to point to your new database:
```
# From:
postgres://user:pass@host:5432/postgres
# To:
postgresql://user:pass@host:5432/myapp
```

### Step 3: Create Tables

Method A — Via app container terminal:
```sh
# Connect to your app container terminal, then:
node -e "
const { PrismaPg } = require('@prisma/adapter-pg');
const { PrismaClient } = require('@prisma/client');
let url = process.env.DATABASE_URL;
if (url.startsWith('postgres://')) url = url.replace('postgres://', 'postgresql://');
const adapter = new PrismaPg({ connectionString: url });
const p = new PrismaClient({ adapter });
p.\$executeRawUnsafe('CREATE TABLE IF NOT EXISTS \\\"Lead\\\" (...)').then(() => { console.log('Done'); p.\$disconnect(); }).catch(e => { console.error(e.message); p.\$disconnect(); });
"
```

Method B — Via PostgreSQL container terminal (simpler):
1. Go to your PostgreSQL resource in Coolify
2. Click **Terminal**
3. Run: `psql -U youruser -d yourdb`
4. Paste your CREATE TABLE SQL

### Step 4: Redeploy

After creating the database and tables, redeploy the app so it picks up the new `DATABASE_URL`.

## CORS & Cross-Domain Configuration

When frontend and backend are on different subdomains (`myapp.com` and `api.myapp.com`), the backend must allow cross-origin requests:

```python
# FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://myapp.com", "https://www.myapp.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

If using auth cookies across subdomains, set the cookie domain:
```python
response.set_cookie(
    key="token", value=jwt_token,
    httponly=True, secure=True,
    samesite="none",
    domain=".myapp.com"  # Shared across subdomains
)
```

## Redeploying

1. Push code to git — Coolify auto-deploys (or manually trigger)
2. During redeploy, Coolify builds a new container, then swaps it in (zero-downtime)
3. **Never delete database volumes** during redeploy unless you want to lose all data
4. If migrations changed, your entrypoint runs them automatically
5. Persistent volumes survive redeploys — uploaded files remain intact

## Verification Checklist

After deploying, verify every endpoint:

| Check | URL | Expected |
|-------|-----|----------|
| Backend health | `https://api.myapp.com/api/health` | `{"status":"ok"}` |
| API data | `https://api.myapp.com/api/products` | Data array (not empty/error) |
| Frontend homepage | `https://myapp.com` | Renders with data |
| Frontend dynamic page | `https://myapp.com/shop` | Content loads from API |
| Login flow | `https://myapp.com/admin/login` | Login works, cookies set |
| HTTPS | All URLs | Padlock icon, no mixed content |

## Debugging by Symptom

### 502 Bad Gateway
- [ ] Port in Coolify Configuration matches what the app listens on? (NOT 3000 if backend is 8000)
- [ ] Container actually running? Check logs
- [ ] Health check passing? Check health check logs
- [ ] App starts successfully? Look for uvicorn/node startup messages

### `npm ci` Fails with Lock File Out of Sync
- [ ] Using `npm ci` in Dockerfile with lock file generated by npm v11+?
- [ ] **Fix**: Change `RUN npm ci` to `RUN npm install --legacy-peer-deps`
- [ ] Or regenerate lock file inside Docker with matching npm version
- [ ] This happens because npm v11 lock files are incompatible with npm v10 used in Docker

### Prisma 7 `PrismaClientConstructorValidationError`
- [ ] Error: "Using engine type 'client' requires either 'adapter' or 'accelerateUrl'"?
- [ ] **Fix**: Install `@prisma/adapter-pg` and `pg`, configure PrismaClient with the adapter
- [ ] Prisma 7 defaults to "client" engine type which requires a driver adapter

### `Cannot find module 'postgres-array'` or Other Missing Packages
- [ ] Running Next.js standalone in Docker?
- [ ] Next.js standalone creates stub packages (just `package.json`, no real code)
- [ ] **Fix**: Copy the full package from builder stage in Dockerfile
- [ ] Always check `.next/standalone/node_modules/` after building for stubs vs real packages

### `npx prisma db push` Gives "sh: prisma: not found"
- [ ] Running inside Next.js standalone Docker container?
- [ ] The `prisma` CLI binary is NOT in standalone's `node_modules/.bin/`
- [ ] Even copying it manually doesn't work — it has too many transitive dependencies
- [ ] **Fix**: Use PrismaClient (not CLI) for DB checks, create tables via Coolify terminal or raw SQL

### Database `does not exist` Error
- [ ] Coolify's `DATABASE_URL` points to `/postgres` database by default
- [ ] **Fix**: Create your app database via terminal (see Post-Deploy Database Setup)
- [ ] Update `DATABASE_URL` in Coolify env vars to point to `/your_db_name`

### `Lead` Table Does Not Exist
- [ ] First deployment? Tables haven't been created yet
- [ ] **Fix**: Create tables via Coolify terminal (see Post-Deploy Database Setup)
- [ ] Don't rely on `npx prisma db push` in entrypoint for standalone mode

### Service Crashes at Import Time (Resend, etc.)
- [ ] Library instantiated at module level without required API key?
- [ ] **Fix**: Initialize lazily, skip functionality if key is not set
- [ ] `new Resend(undefined)` crashes — wrap in conditional

### CORS Errors (Browser DevTools)
- [ ] `CORS_ORIGINS` set in backend env vars?
- [ ] Includes all frontend domains with `https://` prefix?
- [ ] `allow_credentials=True` and `allow_methods=["*"]`?

### Frontend Blank / No Data
- [ ] `NEXT_PUBLIC_API_URL` in both Build Args AND Environment Variables?
- [ ] `API_URL_INTERNAL` set for server-side rendering?
- [ ] CORS configured on backend?
- [ ] `cache: "no-store"` on all dynamic API fetches?

### Database Connection Failures
- [ ] `DATABASE_URL` uses `postgresql://` not `postgres://`?
- [ ] Normalized in both code AND entrypoint script?
- [ ] Points to your app database, not `/postgres`?
- [ ] App database created in entrypoint?

### Authentication Fails
- [ ] `$` signs in password hashes escaped with `$$`?
- [ ] `COOKIE_DOMAIN` set to `.myapp.com` for cross-subdomain auth?
- [ ] Cookies set with `SameSite=None; Secure` for cross-domain?

### Container Keeps Restarting
- [ ] `set -e` in entrypoint? Remove it
- [ ] Entrypoint `exit 1` on DB failure? Change to warning
- [ ] Check container logs for the actual error

### Health Check Fails
- [ ] `127.0.0.1` not `localhost` in Alpine containers?
- [ ] `wget` not `curl` on Alpine?
- [ ] `start-period` long enough (60-120s)?

## Common Mistakes Reference

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Wrong port (3000 default) | 502 Bad Gateway | Set port to match app listen port |
| `postgres://` in DATABASE_URL | Prisma/SQLAlchemy crash | Normalize to `postgresql://` |
| `set -e` in entrypoint | Container crash loop | Remove, use explicit error handling |
| `exit 1` on DB failure | Restart loop | Log warning, start anyway |
| `NEXT_PUBLIC_*` only in env vars | Frontend sees `undefined` | Set in BOTH Build Args and Env Vars |
| `localhost` in Alpine healthcheck | Always fails | Use `127.0.0.1` |
| `curl` on Alpine | Command not found | Use `wget` |
| `docker-compose.yml` with Coolify | Config conflicts | Use separate Coolify resources |
| Missing CORS origins | Browser blocks API | Add all frontend domains |
| Default DB is `postgres` | Tables not found | Create app DB, update DATABASE_URL |
| Stale volumes after password change | Auth fails | Delete old volumes |
| `psycopg2` not `psycopg2-binary` | Build fails | Use binary package |
| No `cache: "no-store"` | Stale data | Add to all dynamic fetches |
| `notFound()` on any API error | 404 when backend down | Only on real 404s |
| `$` not escaped in Docker env vars | Corrupted hashes/passwords | Double every `$` → `$$` |
| Missing persistent volume | Uploads lost on redeploy | Mount volume to upload dir |
| `EXPOSE` without Coolify port set | 502 Bad Gateway | Set both |
| No health check defined | Unhealthy undetected | Add HEALTHCHECK to Dockerfile |
| `npm ci` fails in Docker | Lock file out of sync | Use `npm install --legacy-peer-deps` |
| Prisma 7 without adapter | `PrismaClientConstructorValidationError` | Install `@prisma/adapter-pg` + `pg`, configure adapter |
| Node 20 with Prisma 7 | `EBADENGINE` warning → runtime crash | Use `node:22-alpine` |
| Standalone missing packages | `Cannot find module` runtime errors | Copy missing packages from builder stage |
| `npx prisma db push` in standalone | `sh: prisma: not found` | Use PrismaClient or raw SQL for DB setup |
| `new Resend(undefined)` | `Missing API key` crash | Initialize lazily with null check |
| `postgres-array` stub in standalone | `Cannot find module` at runtime | Copy full package from builder stage |
| `*.md` in .dockerignore | Important docs excluded | Be specific, don't blanket exclude |
