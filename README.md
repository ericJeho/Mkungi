# Mkungi

**From Paper to Perfectly Editable.**

Mkungi is an AI document-reconstruction platform. Ordinary OCR extracts the words; Mkungi rebuilds the whole document — layout, fonts, tables, borders, logos, stamps and signatures — as an editable Word or Excel file that looks like the original.

*Mkungi* evokes a bundle or collection in Chichewa: everything on the page, gathered and put back together.

![Scan (left) and the rebuilt Word document (right)](docs/reconstruction-sample.png)

- **Product brief** — vision, mission, products, customers, ecosystem: [docs/PRODUCT.md](docs/PRODUCT.md)
- **Build plan** — phase-by-phase checklist with gates and quality targets: [docs/BUILD_CHECKLIST.md](docs/BUILD_CHECKLIST.md)

## How it works

```
upload ─► enhance ─► OCR ─► layout analysis ─► classify ─► write
 PDF/      deskew,    Paddle   tables + merged     Mkungi AI    .docx (Word)
 image     denoise    OCR      cells, logos,       picks doc    .xlsx (Excel)
                               stamps, signatures, type and
                               QR codes, styles    format
```

| Stage | Code |
|---|---|
| Layout model shared by all stages | `backend/app/models.py` |
| Image enhancement, PDF/TIFF pages | `backend/app/pipeline/preprocess.py` |
| OCR engines (PaddleOCR, Tesseract) | `backend/app/pipeline/ocr.py` |
| Tables, image regions, text style | `backend/app/pipeline/layout.py` |
| Document-type detection | `backend/app/pipeline/classify.py` |
| Word / Excel reconstruction | `backend/app/pipeline/writers/` |
| API | `backend/app/main.py` |
| Web app | `frontend/` |

Signatures, stamps, QR codes and barcodes are always carried over as images, never re-drawn. Excel output stores amounts as real numbers (`1,250.00` → `1250`, `(300)` → `-300`) so totals can be recalculated.

## Run it

**Docker** (API on :8000, web app on :3000):

```bash
docker compose up --build
```

**Locally:**

```bash
# API
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt -r requirements-ocr.txt
uvicorn app.main:app --reload            # http://localhost:8000/docs

# Web app
cd frontend
cp .env.example .env.local
npm install && npm run dev               # http://localhost:3000
```

Set `MKUNGI_OCR_ENGINE=tesseract` to use Tesseract instead of PaddleOCR (needs `pip install pytesseract` and the `tesseract` binary).

## API

```bash
# Start a conversion (output_format: auto | docx | xlsx)
curl -F file=@invoice.pdf -F output_format=auto http://localhost:8000/v1/conversions
# → {"id": "…", "status": "queued", …}

curl http://localhost:8000/v1/conversions/<id>            # status, doc_type, pages, tables, images
curl -OJ http://localhost:8000/v1/conversions/<id>/download
```

## Tests

```bash
cd backend && pytest        # pipeline + API, using a stub OCR engine (no PaddleOCR needed)
cd frontend && npm run typecheck && npm run build
```

## Stack

Next.js · React · Tailwind CSS · TypeScript · FastAPI · OpenCV · PaddleOCR · python-docx · openpyxl · PyMuPDF · Docker. PostgreSQL, Redis, LayoutLMv3/DiT and transformer table detection come in phases 2–3 of the build plan. Word files are written with python-docx, which produces the same Office Open XML as the .NET OpenXML SDK, so the backend stays in one language.
