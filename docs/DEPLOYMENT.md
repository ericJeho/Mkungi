# Deploying Mkungi on Supabase + Vercel

```
 browser ──► Vercel: mkungi-web  (Next.js, frontend/)
    │
    ├──► Vercel: mkungi-api  (FastAPI Python function, backend/)
    │        │  creates jobs, mints signed upload URLs, runs the conversion
    │        ▼
    └──► Supabase Storage  ◄── API reads uploads, writes .docx/.xlsx
         Supabase Postgres  ◄── API stores job rows (table: conversions)
```

- The browser uploads the scan **straight to Supabase Storage** through a signed URL. Vercel functions accept at most 4.5 MB per request, so files never pass through the API.
- The conversion runs inside one function call (up to 300 s). A two-page A4 PDF takes about 20 s on CPU.
- OCR uses **RapidOCR**: PaddleOCR's PP-OCR models run on ONNX Runtime. The whole backend bundle is about 380 MB, under Vercel's 500 MB limit for Python functions. PaddlePaddle itself does not fit.
- Only the API holds the Supabase **secret key**. The table has row-level security with no policies, and both buckets are private, so the publishable key can't read anything.

## Fastest: one-click deployment with GitHub Actions

`.github/workflows/deploy.yml` does a complete deployment:
- Creates (or updates) the `mkungi-api` and `mkungi-frontend` Vercel projects.
- Sets every environment variable, generating `CRON_SECRET` and the IP-hash salt on the first run.
- Makes both projects public.
- Deploys the API and checks `/health`.
- Deploys the web app pointed at the API, and checks its home page.
- Optionally sets the Supabase sign-in redirect URLs.

It runs again on every push to `main` that changes `backend/` or `frontend/`.

1. In GitHub, go to **ericJeho/Mkungi → Settings → Secrets and variables → Actions → New repository secret**, and add:

   | Secret | Where to get it |
   |---|---|
   | `VERCEL_TOKEN` | vercel.com → Account Settings → Tokens → Create |
   | `SUPABASE_SECRET_KEY` | Supabase → Project Settings → API Keys → secret key (`sb_secret_…`) |
   | `SUPABASE_ACCESS_TOKEN` (optional) | supabase.com/dashboard/account/tokens; lets the workflow set the sign-in Site URL and Redirect URLs for you |

2. Go to **Actions → Deploy → Run workflow** (branch `main`).
3. The run summary lists the web app and API URLs.

Custom SMTP for sign-in emails (step 4.2 below) is still a manual step.

The rest of this guide covers doing the same steps by hand in the dashboards.

## 1. Supabase

**Done for production:** project `mkungi` (ref `wluzawxnsblsgllpkvrj`, org Jehosoft, region `eu-west-1`), URL `https://wluzawxnsblsgllpkvrj.supabase.co`, with the migration applied. Only step 3 (copy the secret key) is left. The steps below are for setting up another environment, such as staging.

1. Create a project at [supabase.com/dashboard](https://supabase.com/dashboard), in a region close to your users.
2. Apply the migration in `supabase/migrations/`. It creates the `conversions` table and the private `uploads` (25 MB) and `outputs` buckets. Use either:
   - **CLI:** `npx supabase login && npx supabase link --project-ref <ref> && npx supabase db push`
   - **Dashboard:** paste the SQL file into *SQL Editor* and run it.
   - **GitHub integration** (optional): connect the repo under *Project Settings → Integrations*, and later migrations are applied on merge.
3. From *Project Settings → API Keys*, copy the **Project URL** and a **secret key** (`sb_secret_…`). The legacy `service_role` key also works.

## 2. Vercel: API project

1. *Add New → Project →* import `ericJeho/Mkungi`.
2. **Root Directory:** `backend`. **Framework Preset:** Other.
3. Environment variables:

   | Name | Value |
   |---|---|
   | `MKUNGI_SUPABASE_URL` | `https://wluzawxnsblsgllpkvrj.supabase.co` |
   | `MKUNGI_SUPABASE_SECRET_KEY` | `sb_secret_…` (mark as Sensitive) |
   | `MKUNGI_CORS_ORIGINS` | `["https://<your-web-domain>"]` |
   | `MKUNGI_CORS_ORIGIN_REGEX` | `https://mkungi-frontend(-[a-z0-9-]+)?\.vercel\.app` (allows preview deployments) |
   | `CRON_SECRET` | a long random string, e.g. `openssl rand -hex 32` (Vercel sends it to the daily clean-up) |
   | `MKUNGI_IP_HASH_SALT` | another random string (salts the visitor hash used for rate limiting) |

4. Deploy, then open `https://<api-domain>/health`. It should return `"storage": "supabase"`.

`backend/vercel.json` sets the function to 300 s and 2 GB, routes every path to `api/index.py`, and schedules the daily clean-up (03:17 UTC) under *Settings → Cron Jobs*.

## 3. Vercel: web project

1. Import the same repo again as a second project, e.g. `mkungi-frontend`.
2. **Root Directory:** `frontend`. **Framework Preset:** Next.js.
3. Environment variables:

   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://<api-domain>` |
   | `NEXT_PUBLIC_SUPABASE_URL` | `https://wluzawxnsblsgllpkvrj.supabase.co` |
   | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | the `sb_publishable_…` key from *Project Settings → API Keys* (safe in the browser: RLS blocks it from all Mkungi data) |

4. Deploy, then add your custom domains (e.g. `mkungi.com` for the web app, `api.mkungi.com` for the API) and update `MKUNGI_CORS_ORIGINS` to match.

## 4. Supabase Auth (sign-in)

Users sign in with an emailed magic link. Converting requires an account; the landing page stays public. Each conversion belongs to the account that made it, and the API returns "not found" for anyone else's.

1. *Authentication → URL Configuration*:
   - **Site URL:** your web app's address, e.g. `https://mkungi.com` (or the `mkungi-frontend` Vercel URL until you have a domain).
   - **Redirect URLs:** add the same address, `http://localhost:3000`, and `https://mkungi-frontend-*.vercel.app` for preview deployments. The magic link only sends people back to addresses on this list.
2. **Set up custom SMTP before inviting real users.** Supabase's built-in email sender only delivers to members of your Supabase organization, and only a few emails an hour. Under *Authentication → Emails → SMTP Settings*, add a provider such as Resend, Postmark, Amazon SES or Brevo, sending from an address on your own domain.
3. Optional: under *Authentication → Emails → Templates*, brand the "Magic Link" and "Confirm signup" emails with the Mkungi name.

The browser verifies the link with PKCE, so it must be opened in the same browser that asked for it. The sign-in form says so.

In both projects, turn on *Settings → Git → Ignored Build Step → "Only build if there are changes in the root directory"*, so a frontend-only commit doesn't redeploy the API.

## Limits

| Limit | Value | Where it's set |
|---|---|---|
| Upload size | 25 MB | `uploads` bucket + `MKUNGI_MAX_UPLOAD_MB` |
| Pages per document | 20 | `MKUNGI_MAX_PAGES` |
| Conversion time | 300 s | `backend/vercel.json` (`maxDuration`; Pro plans can raise it to 800) |
| Function memory | 2 GB | `backend/vercel.json` |
| Conversions per visitor | 30 per hour (HTTP 429 after) | `MKUNGI_MAX_CONVERSIONS_PER_HOUR` |
| File retention | 24 h; the clean-up runs daily, so files go within 48 h at most | `MKUNGI_RETENTION_HOURS`, `crons` in `backend/vercel.json` |

## Before opening it to the public

- **Abuse limit and retention are built in:** 30 conversions per visitor per hour, and a daily Vercel Cron job deletes jobs and files older than 24 hours. The clean-up only runs if `CRON_SECRET` is set.
- **Sign-in is built in:** converting needs an account, jobs are private to their owner, and the hourly limit applies per account. Before real users arrive, set up custom SMTP (step 4). Without it, sign-in emails only reach your own team.

## Local development

Without the `MKUNGI_SUPABASE_*` variables, the API keeps jobs and files on local disk (`MKUNGI_STORAGE_DIR`), so no Supabase project is needed:

```bash
cd backend && pip install -r requirements-dev.txt && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

To develop against a local Supabase stack instead, run `npx supabase start`, which needs Docker and applies the migration automatically. Then point `MKUNGI_SUPABASE_URL`/`MKUNGI_SUPABASE_SECRET_KEY` at the values it prints.
