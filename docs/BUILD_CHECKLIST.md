# Mkungi — phase-by-phase build checklist

Source: the Mkungi product brief ([PRODUCT.md](PRODUCT.md)). Each phase ends with a **gate**: stop, demo what was built, and get sign-off before starting the next.

## Ground rules

- Every conversion is measured against the original scan. Keep a **golden set** of real documents (anonymised) per document type, and track scores per phase.
- Signatures, stamps, QR codes and barcodes are **never** OCR'd or redrawn — they are always carried over as images.
- Customer documents are confidential: encrypted at rest, deleted on the retention schedule, never used for training without written consent.
- The pipeline produces one layout model (`backend/app/models.py`); every new engine or writer reads or writes that model, so stages can be swapped independently.

## Quality targets

| Metric | MVP | Launch |
|---|---|---|
| Character accuracy (clean print) | ≥ 97% | ≥ 99% |
| Table structure (cells correctly placed) | ≥ 85% | ≥ 95% |
| Visual similarity of rendered output vs scan | ≥ 0.80 SSIM | ≥ 0.90 SSIM |
| Time per page (CPU / GPU) | < 15 s / < 3 s | < 8 s / < 1 s |

---

## Phase 0 — Foundation ✅ (this commit)

- [x] Repository layout: `backend/` (FastAPI), `frontend/` (Next.js + Tailwind + TypeScript), `docs/`
- [x] Layout model: pages → text lines (with bold/colour), tables (with merged cells), image regions (logo / signature / stamp / code / picture)
- [x] Image enhancement: deskew + denoise (OpenCV), multi-page TIFF, PDF rendering at 300 dpi (pdfium)
- [x] OCR engine interface: RapidOCR (PaddleOCR PP-OCR models on ONNX Runtime, default), PaddleOCR and Tesseract
- [x] Ruled-table detection with column-span merging (OpenCV morphology)
- [x] Non-text region detection and classification (logo, stamp, signature, QR/barcode)
- [x] Mkungi AI v0: keyword document-type classifier for all 13 template types; auto-picks Word or Excel
- [x] Word writer: page size, indents, tab stops, alignment, spacing, font size/bold/colour, bordered tables, pictures
- [x] Excel writer: one sheet per page, bordered/merged tables, numbers stored as numbers
- [x] API: create job → upload → process → download (`/v1/conversions…`)
- [x] Web app: drag-and-drop, batch upload, Auto/Word/Excel choice, live status, download
- [x] Tests on a synthetic invoice; Docker images; docker-compose

**Gate:** convert 20 real documents (invoices, GRNs, payroll) and review output side by side with the scans.

---

## Phase 1 — Accuracy on real documents

- [ ] Collect the golden set: ≥ 30 documents per type, scanned and phone-photographed, including poor-quality copies
- [ ] Scoring harness: CER, table-cell accuracy, SSIM of rendered output (LibreOffice → PDF → image) against the scan
- [ ] Perspective correction and shadow removal for phone photos
- [ ] Borderless tables (column alignment of text) in addition to ruled tables
- [ ] Row-span merging in tables
- [ ] Font family matching (serif / sans / mono) from glyph shape
- [ ] Multi-column text flow (newsletters, reports)
- [ ] Searchable PDF output (original image + invisible text layer)
- [ ] Automatic language detection; English, French, Portuguese, Swahili, Chichewa

**Gate:** MVP quality targets met on the golden set.

---

## Phase 2 — Production platform

- [x] Supabase Postgres for conversion jobs (`supabase/migrations/`), RLS on, secret key only on the server
- [x] Supabase Storage: private `uploads` / `outputs` buckets; browser uploads via signed URLs, downloads via 5-minute signed URLs
- [x] Deployment: Vercel projects for `frontend/` (Next.js) and `backend/` (Python function), see [DEPLOYMENT.md](DEPLOYMENT.md)
- [x] Supabase Auth: email magic-link sign-in (PKCE); conversions owned by a user (`user_id`), enforced by the API on every request; per-account rate limit; "Your conversions" list
- [ ] Custom SMTP for sign-in emails (the built-in sender only reaches the Supabase organization's own members)
- [ ] Google / Microsoft sign-in (needs OAuth apps in Google Cloud / Entra ID)
- [x] Per-visitor rate limit (30 conversions/hour on a salted IP hash) so public traffic can't exhaust Vercel compute; per-user quotas follow sign-in
- [x] Retention: daily Vercel Cron deletes jobs, uploads and outputs older than 24 hours
- [ ] Background workers for long documents (> 20 pages or > 300 s): a queue (Supabase Queues / pgmq) and a worker outside Vercel
- [ ] Accounts, organisations and teams; roles (owner, admin, member)
- [ ] API keys, per-key rate limits and usage metering
- [ ] Batch upload as a single job with a ZIP download
- [ ] Audit log: who uploaded, converted, downloaded or deleted what, and when
- [ ] Observability: structured logs, metrics, error tracking, per-stage timings
- [ ] Staging Supabase project + Vercel preview environment wired to it

**Gate:** a pilot organisation runs 1,000 pages through the platform without manual intervention.

---

## Phase 3 — Full reconstruction (Mkungi AI v1)

- [ ] Learned layout model (LayoutLMv3 or DiT) for regions: title, paragraph, table, figure, header, footer, signature block
- [ ] Transformer table-structure recognition (e.g. Table Transformer) for complex and borderless tables
- [ ] Headers and footers: detect repeated regions across pages and write them as real Word headers/footers
- [ ] Watermarks: detect faint background marks, remove from the page image, re-add as a Word watermark
- [ ] QR and barcode decoding; value stored with the document
- [ ] Learned document-type classifier replacing keywords
- [ ] GPU inference path

**Gate:** launch quality targets met on the golden set.

---

## Phase 4 — Templates and Cloud

- [ ] Mkungi Templates library: the 13 types, each as an editable Word/Excel template with formulas where relevant
- [ ] "Convert to template": map a scanned invoice/GRN/payslip onto its clean template
- [ ] Mkungi Cloud: folders, full-text search across all converted documents, version history, sharing
- [ ] Team collaboration: comments and assignment on documents

**Gate:** customers can find any converted document by its contents in under 2 seconds.

---

## Phase 5 — Document intelligence

- [ ] Invoice and receipt field extraction (supplier, date, number, line items, VAT, totals) with confidence scores
- [ ] Export extracted data to CSV / accounting systems
- [ ] Ask questions about a document; AI summaries
- [ ] Duplicate document detection
- [ ] Fraud signals: altered totals, mismatched VAT, reused invoice numbers
- [ ] Handwriting recognition
- [ ] Format-preserving translation

**Gate:** field extraction ≥ 95% accurate on the invoice golden set.

---

## Phase 6 — Ecosystem

- [ ] Mkungi Mobile: scan with edge detection and convert from a phone
- [ ] Mkungi Forms, Sign, Flow, Archive, Analytics
- [ ] Public API documentation, SDKs and developer portal
- [ ] Billing: free tier, per-page plans, enterprise contracts; mobile money payments

**Gate:** decided per product.
