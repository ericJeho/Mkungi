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

## 1. Supabase

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
   | `MKUNGI_SUPABASE_URL` | `https://<ref>.supabase.co` |
   | `MKUNGI_SUPABASE_SECRET_KEY` | `sb_secret_…` (mark as Sensitive) |
   | `MKUNGI_CORS_ORIGINS` | `["https://<your-web-domain>"]` |
   | `MKUNGI_CORS_ORIGIN_REGEX` | `https://mkungi-web(-[a-z0-9-]+)?\.vercel\.app` (allows preview deployments) |

4. Deploy, then open `https://<api-domain>/health`. It should return `"storage": "supabase"`.

`backend/vercel.json` sets the function to 300 s and 2 GB, and routes every path to `api/index.py`.

## 3. Vercel: web project

1. Import the same repo again as a second project, e.g. `mkungi-web`.
2. **Root Directory:** `frontend`. **Framework Preset:** Next.js.
3. Environment variable: `NEXT_PUBLIC_API_URL` = `https://<api-domain>`.
4. Deploy, then add your custom domains (e.g. `mkungi.com` for the web app, `api.mkungi.com` for the API) and update `MKUNGI_CORS_ORIGINS` to match.

In both projects, turn on *Settings → Git → Ignored Build Step → "Only build if there are changes in the root directory"*, so a frontend-only commit doesn't redeploy the API.

## Limits

| Limit | Value | Where it's set |
|---|---|---|
| Upload size | 25 MB | `uploads` bucket + `MKUNGI_MAX_UPLOAD_MB` |
| Pages per document | 20 | `MKUNGI_MAX_PAGES` |
| Conversion time | 300 s | `backend/vercel.json` (`maxDuration`; Pro plans can raise it to 800) |
| Function memory | 2 GB | `backend/vercel.json` |

## Before opening it to the public

- **Sign-in and quotas.** Right now anyone with the URL can convert documents, which uses your Vercel compute. Add Supabase Auth and per-user limits (build checklist, phase 2).
- **Retention.** Uploaded scans and outputs stay in Storage until deleted. Add a scheduled clean-up that deletes files older than N days.
- Job ids are random UUIDs and downloads use 5-minute signed URLs, but anyone holding a job id can fetch its result until retention removes it.

## Local development

Without the `MKUNGI_SUPABASE_*` variables, the API keeps jobs and files on local disk (`MKUNGI_STORAGE_DIR`), so no Supabase project is needed:

```bash
cd backend && pip install -r requirements-dev.txt && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

To develop against a local Supabase stack instead, run `npx supabase start`, which needs Docker and applies the migration automatically. Then point `MKUNGI_SUPABASE_URL`/`MKUNGI_SUPABASE_SECRET_KEY` at the values it prints.
