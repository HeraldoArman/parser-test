# BRP Assessment Parser

Bulk-parse UI BRP / silabus documents (PDF, DOCX, XLSX) into assessment components
and weights, review them in the browser, then export JSON or CSV.

No LLM: detection is structural (numeric weight columns and percentage line runs),
so results are reproducible and auditable. Every component keeps its `source_ref`.

## Run locally

```sh
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser   # optional, for /admin/
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/ and upload one or more files (≤ 20 MB each).
Pages: upload → batch → review → approve. `/coverage/` shows status counts and
structural families (files that will need the same parser attention).

## Run with Docker

```sh
docker build -t brp-parser .
docker run -p 8000:8000 \
  -e DJANGO_SECRET_KEY=change-me \
  -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
  -v "$PWD/db.sqlite3:/app/db.sqlite3" \
  -v "$PWD/media:/app/media" \
  brp-parser
```

## Corpus triage without the database

```sh
uv run python manage.py parse_doc docs-example --verbose
```

Prints status, fingerprint, item count and weight sum per file. The same
pipeline runs on upload; identical files are deduplicated by SHA-256.

## Scanned PDFs

Pages without a text layer are rendered at 200 dpi and OCR'd with
RapidOCR (ONNX, models bundled — no system tesseract). The recognized lines
are fed through the same detectors, so a scanned BRP reaches `ok`/`bonus`
like a digital one. OCR is capped at 40 pages per file and the reason list
says so; a scanned file is never silently skipped. To turn OCR off, remove
`rapidocr-onnxruntime` — the reader falls back to the old
`needs_review: no text layer` result.

## Learned ranker (optional)

Structural rules decide everything by default. Once documents are approved,
`assessments/extraction/ranker.py` can learn **which candidate the reviewer
picked** from 11 structural signals and use that as a tie-breaker inside the
same validation tier (it can never promote something the rules reject).

```sh
uv run python manage.py train_ranker
```

It refuses to train below 20 candidate rows / 5 approvals, so nothing
overfits a handful of files. The model is plain JSON at `ranker.json`
(override with `settings.RANKER_PATH`), no dependency beyond the standard
library. `/coverage/` shows whether a model is active and on how many labels.

## Status meanings

| Status | Meaning |
| --- | --- |
| `ok` | weights sum to 100% |
| `bonus` | base sums to 100%, extra component marked bonus |
| `ambiguous` | two plausible representations (e.g. detail table vs summary list) |
| `needs_review` | candidates exist but are below the confidence gate, or the PDF has no text layer |
| `not_found` | no assessment section detected |

Nothing is trusted automatically: review, edit and approve. Approving stores the
section heading as an anchor, which sharpens ranking for later documents.
