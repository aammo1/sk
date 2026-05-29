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

Coolify generates `DATABASE_URL` with `postgres://`. SQLAlchemy 2.0+ requires `postgresql://`. Always normalize in both code and scripts:

```python
class Settings(BaseSettings):
    DATABASE_URL: str

    @property
    def database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
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

### Complete Entrypoint Template

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

### Next.js Frontend (Multi-stage)

```dockerfile
FROM node:20-alpine AS base

FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

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
.env.local
.env*.local
*.md
```

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
| `postgres://` in DATABASE_URL | SQLAlchemy crash | Normalize to `postgresql://` |
| `set -e` in entrypoint | Container crash loop | Remove, use explicit error handling |
| `exit 1` on DB failure | Restart loop | Log warning, start anyway |
| `NEXT_PUBLIC_*` only in env vars | Frontend sees `undefined` | Set in BOTH Build Args and Env Vars |
| `localhost` in Alpine healthcheck | Always fails | Use `127.0.0.1` |
| `curl` on Alpine | Command not found | Use `wget` |
| `docker-compose.yml` with Coolify | Config conflicts | Use separate Coolify resources |
| Missing CORS origins | Browser blocks API | Add all frontend domains |
| Default DB is `postgres` | Tables not found | Create app DB in entrypoint |
| Stale volumes after password change | Auth fails | Delete old volumes |
| `psycopg2` not `psycopg2-binary` | Build fails | Use binary package |
| No `cache: "no-store"` | Stale data | Add to all dynamic fetches |
| `notFound()` on any API error | 404 when backend down | Only on real 404s |
| `$` not escaped in Docker env vars | Corrupted hashes/passwords | Double every `$` → `$$` |
| Missing persistent volume | Uploads lost on redeploy | Mount volume to upload dir |
| `EXPOSE` without Coolify port set | 502 Bad Gateway | Set both |
| No health check defined | Unhealthy undetected | Add HEALTHCHECK to Dockerfile |
